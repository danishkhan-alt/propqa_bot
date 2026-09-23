"""Memory behaviour from the architecture spec.

Recall must not leak a budget into an RTA question. "Cheaper" narrows price.
An explicit correction replaces a slot. An inferred claim does not.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.context import AgentContext
from agent.enums.routing import Route, TurnKind
from agent.graphs.chat import build_chat_graph
from agent.memory.write.upsert import write_memories
from agent.memory.maintenance.consolidate import consolidate_user
from agent.memory.read.personalize import apply_saved_preferences
from agent.memory.write.extract import extract_explicit, extract_turn
from agent.memory.safety.reject_unsafe import MemoryRejected, validate_memory
from agent.memory.storage.cache import WorkingMemoryCache
from agent.memory.session.search_results import summarize_search_results
from agent.memory.read.prompt_text import disclosure_line
from agent.memory.maintenance.privacy import export_user_memory, forget_memory, set_memory_enabled
from agent.memory.read.recall import classify_clusters, recall_for_user
from agent.memory.session.follow_up import update_search_from_message
from agent.memory.storage.repository import InMemoryRepository
from agent.memory.routes import router
from agent.memory.session.bootstrap import set_hot, set_repository
from agent.memory.read.scoring import score_memory
from agent.memory.storage.langgraph_store import PropQAMemoryStore
from agent.memory.models.types import MemoryOp, empty_frame, utcnow
from agent.memory.write.worker import drain, process_job
from agent.schemas.routes import QueryRoute
from agent.tests.test_router import ScriptedModels


def _preference(slot: str, column: str, op: str, value, *, cluster: str, provenance: str = "explicit", confidence: float = 0.9, importance: float = 0.7, action: str = "add", memory_type: str = "preference"):
    return MemoryOp(
        op=action,
        type=memory_type,
        cluster=cluster,
        slot=slot,
        content=f"{slot} {op} {value}",
        structured={"col": column, "op": op, "val": value},
        provenance=provenance,
        confidence=confidence,
        importance=importance,
        evidence="test",
    )


def test_cheaper_uses_the_lower_quartile_and_the_second_row():
    frame = empty_frame()
    frame["domain"] = "property_search"
    frame["predicates"] = {"purpose": "sale"}
    frame["result_meta"] = {"p25_price": 1_200_000, "ids": ["a", "b", "c"], "row_count": 3}
    frame["turn"] = 1
    cheaper = update_search_from_message("cheaper", frame, None, now=utcnow())
    assert cheaper["query_frame"]["predicates"]["price"] == {"lte": 1_200_000}

    second = update_search_from_message("the second one", frame, None, now=utcnow())
    assert second["query_frame"]["predicates"]["id"] == {"in": ["b"]}


def test_budget_does_not_leak_into_rta():
    frame = empty_frame()
    memories = [
        {
            "slot": "budget_max",
            "cluster": "budget",
            "type": "preference",
            "content": "Budget ≤ AED 2M",
            "confidence": 0.9,
            "provenance": "explicit",
            "structured": {"col": "properties.price", "op": "lte", "val": 2_000_000, "currency": "AED"},
            "created_at": "2026-08-14T00:00:00+00:00",
        }
    ]
    merged, labels, block = apply_saved_preferences(
        frame, memories, {}, ["rta_intel"], ignore=False
    )
    assert "price" not in merged["predicates"]
    assert labels == []
    assert "2M" not in block

    kept, labels, _block = apply_saved_preferences(
        frame, memories, {}, ["property_search"], ignore=False
    )
    assert kept["predicates"]["price"] == {"lte": 2_000_000}
    assert labels == ["≤ AED 2M"]
    assert disclosure_line(labels) == "Searched for ≤ AED 2M."


def test_ignore_defaults_skips_saved_filters():
    memories = [
        {
            "slot": "bedrooms",
            "cluster": "property_prefs",
            "type": "preference",
            "content": "Prefers 2-bedroom apartments",
            "confidence": 0.9,
            "provenance": "explicit",
            "structured": {"col": "properties.bedrooms", "op": "eq", "val": 2},
        }
    ]
    merged, labels, _block = apply_saved_preferences(
        empty_frame(), memories, {}, ["property_search"], ignore=True
    )
    assert merged["predicates"] == {}
    assert labels == []


def test_explicit_correction_replaces_a_slot_and_inferred_does_not():
    repo = InMemoryRepository()
    user = "user-1"
    write_memories(
        repo,
        user,
        [_preference("bedrooms", "properties.bedrooms", "eq", 2, cluster="property_prefs")],
    )
    write_memories(
        repo,
        user,
        [
            _preference(
                "bedrooms",
                "properties.bedrooms",
                "eq",
                3,
                cluster="property_prefs",
                action="update",
            )
        ],
    )
    active = repo.get_active_slot(user, "bedrooms")
    assert active is not None
    assert active.structured["val"] == 3
    assert active.supersedes_id

    write_memories(
        repo,
        user,
        [
            _preference(
                "purpose",
                "properties.purpose",
                "eq",
                "sale",
                cluster="property_prefs",
                memory_type="preference",
            )
        ],
    )
    write_memories(
        repo,
        user,
        [
            _preference(
                "purpose",
                "properties.purpose",
                "eq",
                "rent",
                cluster="property_prefs",
                provenance="inferred",
                confidence=0.55,
            )
        ],
    )
    purpose = repo.get_active_slot(user, "purpose")
    assert purpose is not None and purpose.structured["val"] == "sale"
    assert repo.count_events(user, "contradiction_flagged") == 1


def test_overlapping_bedroom_counts_become_one_semantic_value():
    repo = InMemoryRepository()
    write_memories(
        repo,
        "user-1",
        [_preference("bedrooms", "properties.bedrooms", "eq", 2, cluster="property_prefs")],
    )
    write_memories(
        repo,
        "user-1",
        [_preference("bedrooms", "properties.bedrooms", "eq", 3, cluster="property_prefs")],
    )
    active = repo.get_active_slot("user-1", "bedrooms")
    assert active is not None
    assert active.type == "semantic"
    assert active.structured["op"] == "in"
    assert active.structured["val"] == [2, 3]


def test_sql_phone_and_unknown_columns_are_rejected():
    repo = InMemoryRepository()
    columns = repo.columns()
    with pytest.raises(MemoryRejected):
        validate_memory(
            MemoryOp(
                op="add",
                type="preference",
                cluster="budget",
                content="SELECT price FROM properties WHERE id = 1",
                provenance="explicit",
                confidence=0.9,
                importance=0.7,
            ),
            columns,
        )
    cleaned = validate_memory(
        MemoryOp(
            op="add",
            type="preference",
            cluster="personal",
            content="Call me at +971 50 123 4567",
            provenance="explicit",
            confidence=0.9,
            importance=0.7,
        ),
        columns,
    )
    assert "[redacted]" in cleaned.content
    assert write_memories(
        repo,
        "user-1",
        [
            MemoryOp(
                op="add",
                type="preference",
                cluster="property_prefs",
                slot="bedrooms",
                content="show me this listing",
                structured={"col": "properties.not_a_column", "op": "eq", "val": 1},
                provenance="explicit",
                confidence=0.9,
                importance=0.2,
            )
        ],
    ) == []


def test_forget_export_and_kill_switch():
    repo = InMemoryRepository()
    user = "user-1"
    write_memories(
        repo,
        user,
        [
            _preference("budget_max", "properties.price", "lte", 2_000_000, cluster="budget"),
            _preference("bedrooms", "properties.bedrooms", "eq", 2, cluster="property_prefs"),
        ],
    )
    exported = export_user_memory(repo, user)
    assert len(exported) == 2
    assert "embedding" not in exported[0]
    assert all("location_id" not in item["content"] for item in exported)

    assert forget_memory(repo, user, cluster="budget") == 1
    assert repo.get_active_slot(user, "budget_max") is None
    assert repo.count_events(user, "deleted_by_user") == 1
    assert repo.get_active_slot(user, "bedrooms") is not None

    set_memory_enabled(repo, user, False)
    recalled = recall_for_user(repo, user, "2 bedroom apartment in Marina")
    assert recalled["memory_context"] == []


def test_three_episodes_become_a_semantic_memory_and_old_rows_expire():
    repo = InMemoryRepository()
    user = "user-1"
    now = utcnow()
    for count in (10, 12, 8):
        frame = empty_frame()
        frame["domain"] = "property_search"
        frame["predicates"] = {"bedrooms": {"eq": 2}}
        job = {
            "user_id": user,
            "thread_id": "t",
            "message": "show me 2 bedrooms",
            "query_frame": frame,
            "result_meta": {"row_count": count},
        }
        process_job(job, repo, now=now)
    episodic = [row for row in repo.list_active(user) if row.type == "episodic"]
    assert len(episodic) == 3
    consolidate_user(repo, user, now=now)
    semantic = [row for row in repo.list_active(user) if row.type == "semantic"]
    assert semantic and semantic[0].confidence == 0.6
    assert "2 bedrooms" in semantic[0].content

    stale = repo.get_active_slot(user, "bedrooms")
    assert stale is None or stale.type == "semantic"
    profile = repo.get_profile(user)
    assert profile is not None
    assert len(profile["summary"].split()) <= 150

    deleted = repo.list_all(user)[0]
    deleted.status = "deleted"
    deleted.updated_at = now - timedelta(days=31)
    repo.update(deleted)
    consolidate_user(repo, user, now=now)
    assert repo.get(user, deleted.id) is None


def test_extraction_keeps_explicit_preferences_and_drops_a_click():
    ops = extract_explicit("I prefer 2 bedroom apartments under 2 million")
    slots = {op.slot for op in ops}
    assert "bedrooms" in slots
    assert "budget_max" in slots
    budget = next(op for op in ops if op.slot == "budget_max")
    assert budget.structured["val"] == 2_000_000
    assert budget.provenance == "explicit"
    assert budget.confidence >= 0.85

    correction = extract_explicit("I don't care about Marina anymore")
    assert any(op.op == "delete" and op.slot == "preferred_location" for op in correction)

    job = {
        "message": "show me this listing",
        "query_frame": empty_frame(),
        "events": [{"type": "click", "bedrooms": 2}, {"type": "save", "bedrooms": 3}],
    }
    turned = extract_turn(job)
    assert all(op.provenance != "explicit" or op.slot != "bedrooms" for op in turned)
    assert any(op.provenance == "inferred" and op.structured["val"] == 3 for op in turned)


def test_store_search_and_score_follow_the_spec_weights():
    repo = InMemoryRepository()
    store = PropQAMemoryStore(repo)
    now = utcnow()
    memory_id = str(uuid.uuid4())
    store.put(
        ("users", "user-1"),
        memory_id,
        {
            "type": "preference",
            "cluster": "budget",
            "slot": "budget_max",
            "content": "Budget under 2 million",
            "structured": {"col": "properties.price", "op": "lte", "val": 2_000_000},
            "confidence": 1,
            "importance": 1,
            "provenance": "explicit",
        },
    )
    found = store.search(("users", "user-1"), query="budget million", filter={"status": "active", "cluster": ["budget"]})
    assert found and found[0].key == memory_id
    perfect = score_memory(
        {
            "type": "preference",
            "similarity": 1,
            "confidence": 1,
            "importance": 1,
            "updated_at": now,
        },
        now=now,
    )
    assert perfect == pytest.approx(1.0)
    aged = score_memory(
        {
            "type": "preference",
            "similarity": 1,
            "confidence": 1,
            "importance": 1,
            "updated_at": now - timedelta(days=90),
        },
        now=now,
    )
    assert aged == pytest.approx(0.95)


def test_recall_of_many_users_stays_inside_the_latency_budget():
    repo = InMemoryRepository()
    now = utcnow()
    for index in range(30):
        write_memories(
            repo,
            f"user-{index}",
            [_preference("bedrooms", "properties.bedrooms", "eq", 2, cluster="property_prefs")],
            now=now,
        )
    samples = []
    for index in range(30):
        started = time.perf_counter()
        recalled = recall_for_user(repo, f"user-{index}", "2 bedroom apartment", now=now)
        samples.append(time.perf_counter() - started)
        assert recalled["memory_context"]
        assert recalled["memory_context"][0]["structured"]["col"] == "properties.bedrooms"
        rta, labels, _block = apply_saved_preferences(
            empty_frame(), recalled["memory_context"], {}, ["rta_intel"], ignore=False
        )
        assert "bedrooms" not in rta["predicates"]
        assert labels == []
    samples.sort()
    p95 = samples[int(len(samples) * 0.95) - 1]
    assert p95 < 0.15


def test_result_meta_captures_the_quartile_used_by_cheaper():
    meta = summarize_search_results(
        [
            {"id": "a", "price": 100},
            {"id": "b", "price": 200},
            {"id": "c", "price": 300},
            {"id": "d", "price": 400},
        ]
    )
    assert meta["row_count"] == 4
    assert meta["p25_price"] == 200
    assert meta["ids"] == ["a", "b", "c", "d"]
    assert "sql" not in meta


def test_graph_cheaper_narrows_the_saved_frame_and_forget_asks_first():
    hot = WorkingMemoryCache()
    set_hot(hot)
    repo = InMemoryRepository()
    set_repository(repo)
    thread_id = "t-cheap"
    frame = empty_frame()
    frame["domain"] = "property_search"
    frame["turn"] = 1
    frame["result_meta"] = {"p25_price": 900_000, "ids": ["a", "b"]}
    hot.set(f"wm:{thread_id}", {"query_frame": frame, "goal": None, "ignore_defaults": False})

    models = ScriptedModels()
    graph = build_chat_graph(InMemorySaver(), store=PropQAMemoryStore(repo))
    config = {"configurable": {"thread_id": thread_id, "user_id": "user-1"}}
    result = graph.invoke(
        {"messages": [HumanMessage(content="cheaper")]},
        config=config,
        context=AgentContext(user_id="user-1", models=models),
        version="v2",
    )
    value = getattr(result, "value", result)
    if not isinstance(value, dict):
        value = dict(value)
    assert value["query_frame"]["predicates"]["price"]["lte"] == 900_000

    forget_config = {"configurable": {"thread_id": "t-forget", "user_id": "user-1"}}
    paused = graph.invoke(
        {"messages": [HumanMessage(content="Forget all property preferences")]},
        config=forget_config,
        context=AgentContext(user_id="user-1", models=models),
        version="v2",
    )
    assert paused.interrupts[0].value == "Forget all property preferences? yes/no"
    assert models.query_calls == 1
    resumed = graph.invoke(
        Command(resume="no"),
        config=forget_config,
        context=AgentContext(user_id="user-1", models=models),
        version="v2",
    )
    assert resumed.value["messages"][-1].content == "Kept your saved preferences."


def test_worker_drains_the_memory_queue_without_sql():
    hot = WorkingMemoryCache()
    repo = InMemoryRepository()
    frame = empty_frame()
    frame["sql"] = "select * from properties"
    frame["domain"] = "property_search"
    frame["predicates"] = {"purpose": "sale"}
    hot.push(
        {
            "user_id": "user-1",
            "thread_id": "t",
            "message": "I prefer apartments for sale",
            "query_frame": {key: value for key, value in frame.items() if key != "sql"},
            "result_meta": {},
            "events": [],
        }
    )
    assert drain(hot, repo) == 1
    purpose = repo.get_active_slot("user-1", "purpose")
    assert purpose is not None and purpose.structured["val"] == "sale"
    assert all("select" not in row.content.lower() for row in repo.list_all("user-1"))


def test_memory_http_export_and_delete():
    repo = InMemoryRepository()
    set_repository(repo)
    write_memories(
        repo,
        "user-9",
        [_preference("bedrooms", "properties.bedrooms", "eq", 2, cluster="property_prefs")],
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    exported = client.get("/users/user-9/memory")
    assert exported.status_code == 200
    assert exported.json()[0]["content"].startswith("bedrooms")
    removed = client.delete("/users/user-9/memory", params={"cluster": "property_prefs"})
    assert removed.status_code == 200
    assert removed.json()["count"] == 1
    missing = client.delete("/users/user-9/memory")
    assert missing.status_code == 400


def test_off_topic_text_recalls_nothing():
    assert classify_clusters("Hi, what can you help with?") == []


def test_rename_points_a_logical_column_at_a_new_physical_name():
    repo = InMemoryRepository()
    repo.rename_column("properties.price", "listings.asking_price")
    assert repo.columns()["properties.price"].physical_col == "listings.asking_price"


def test_direct_models_still_route_a_greeting():
    models = ScriptedModels()
    graph = build_chat_graph(InMemorySaver())
    result = graph.invoke(
        {"messages": [HumanMessage(content="Hi, what can you help with?")]},
        config={"configurable": {"thread_id": "t-hi"}},
        context=AgentContext(user_id="user-1", models=models),
        version="v2",
    )
    value = getattr(result, "value", result)
    if not isinstance(value, dict):
        value = dict(value)
    route = value["query_route"]
    parsed = route if isinstance(route, QueryRoute) else QueryRoute.model_validate(route)
    assert parsed.route is Route.DIRECT_ANSWER
    assert parsed.turn_kind is TurnKind.NEW
    assert value["messages"][-1].content.startswith("I can explain")
    assert models.domain_calls == 0
