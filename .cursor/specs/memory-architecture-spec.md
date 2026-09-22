# PropQA Text2SQL Chatbot — Memory Architecture Spec

**Stack constraints:** LangGraph · PostgreSQL (`chatbot_ai`, AWS RDS) · Redis · Anthropic Claude
**Bot type:** Text2SQL — cognitive layer → SQL router (fan-out) → domain ReAct agents (`property_search`, `communities_intel`, `market_intel`, `location_intel`, `offplan_projects`, `rta_intel`)
**Decision up front:** No new database. Postgres + pgvector holds everything durable; Redis holds the hot/ephemeral tier; LangGraph's checkpointer + `BaseStore` provide the plumbing.

---

## 1. Feature-to-tier mapping

The 21 requested features collapse into 4 memory tiers, 1 schema, 3 graph nodes, and 1 background worker.

| Tier | LangGraph primitive | Storage | Features covered |
|---|---|---|---|
| **Thread state** (working + short-term) | Graph state + checkpointer (`RedisSaver`) | Redis (TTL) | Short-term memory, Working memory, Task/goal memory |
| **Long-term memory items** | Custom `BaseStore` subclass over `user_memories` (pgvector) | Postgres | Long-term, Preferences, Profile/facts, Episodic, Semantic, Confidence, Provenance, Clustering, TTL, Correction, Deletion, Contradiction, Preference evolution, Privacy |
| **Retrieval** | `recall_memory` node before cognitive layer | pgvector + SQL filters; Redis cache | Memory retrieval, Context-aware personalisation |
| **Consolidation** | Background worker (off the request path) | Postgres | Importance scoring, Summarisation, Clustering, Contradiction sweep, Expiry |

### Store implementation choice

- **Option A (chosen):** own table `user_memories` with first-class columns (confidence, provenance, TTL, status, cluster, slot) + a thin `PropQAMemoryStore(BaseStore)` so nodes/tools use the standard `store.put / search` API while consolidation runs as plain SQL.
- **Option B (rejected):** stock `PostgresStore` from `langgraph-checkpoint-postgres` with metadata in the `value` JSON. Faster start, worse for SQL-driven consolidation, reporting, and audit.

> Verify current class names/signatures (`RedisSaver`, `AsyncPostgresSaver`, `BaseStore`, `IndexConfig`) against docs.langchain.com before implementation — the persistence packages change frequently.

---

## 2. Text2SQL-specific principles

Memory items are **SQL-shaped, not prose-shaped**.

1. **Working memory is a canonical query object** (`QueryFrame`), not chat history. Follow-ups are deltas on predicates, never re-derived from the message list.
2. **Long-term `structured` holds resolved predicate fragments** bound to real columns and IDs (`locations_v2.id`), never SQL text and never free text only.
3. **SQL text is never stored long-term.** It is schema-bound and a disclosure risk. Episodic memory stores query signatures (domain + intent + predicates + result meta).
4. **Entity resolution happens at extraction time** using the same gazetteer as the streaming QU service. Memory pins `locations_v2` only — this forces the dual-location (`locations` vs `locations_v2`) risk closed for the memory layer.
5. **Domain table whitelists are the personalisation gate.** A memory whose `col` is not in the routed domain's whitelisted tables is never injected (e.g. `properties.price` cannot leak into an `rta_intel` query).
6. **Silent personalisation is forbidden.** Every injected default is surfaced once in the answer with an opt-out phrase.

---

## 3. Postgres schema (`chatbot_ai`)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE memory_type       AS ENUM ('profile','preference','semantic','episodic','goal','ephemeral');
CREATE TYPE memory_provenance AS ENUM ('explicit','inferred','system','summarized');
CREATE TYPE memory_status     AS ENUM ('active','superseded','expired','deleted','contradicted');

CREATE TABLE user_memories (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           text NOT NULL,
  type              memory_type NOT NULL,
  cluster           text NOT NULL,             -- property_prefs | budget | location | persona | goal | personal | work | travel
  slot              text,                      -- canonical key for single-valued facts (see §4)
  content           text NOT NULL,             -- human-readable statement, e.g. "Prefers 2BR apartments"
  structured        jsonb,                     -- resolved predicate fragment (see §4)
  embedding         vector(1024),
  confidence        real NOT NULL,             -- 0..1
  importance        real NOT NULL,             -- 0..1
  provenance        memory_provenance NOT NULL,
  source_thread_id  text,
  source_message_id text,
  status            memory_status NOT NULL DEFAULT 'active',
  supersedes_id     uuid REFERENCES user_memories(id),
  valid_from        timestamptz NOT NULL DEFAULT now(),
  expires_at        timestamptz,               -- NULL = no TTL
  last_accessed_at  timestamptz,
  access_count      int NOT NULL DEFAULT 0,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON user_memories (user_id, status, cluster);
CREATE INDEX ON user_memories (user_id, slot) WHERE status = 'active';
CREATE INDEX ON user_memories USING hnsw (embedding vector_cosine_ops);
-- one active value per slot per user
CREATE UNIQUE INDEX ON user_memories (user_id, slot) WHERE status = 'active' AND slot IS NOT NULL;

CREATE TABLE user_profile_summary (            -- consolidated view, rebuilt by worker
  user_id     text PRIMARY KEY,
  summary     text NOT NULL,                   -- ≤150 words
  structured  jsonb NOT NULL,                  -- merged predicate defaults, FilterSpec-compatible
  version     int NOT NULL DEFAULT 1,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memory_events (                   -- audit / provenance / deletion trail
  id          bigserial PRIMARY KEY,
  user_id     text NOT NULL,
  memory_id   uuid,
  event       text NOT NULL,                   -- created|updated|superseded|contradiction_flagged|expired|deleted_by_user|consolidated
  actor       text NOT NULL,                   -- extractor|worker|user|admin
  detail      jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_memory_settings (            -- privacy controls
  user_id          text PRIMARY KEY,
  memory_enabled   bool NOT NULL DEFAULT true,
  allowed_clusters text[] NOT NULL DEFAULT '{property_prefs,budget,location,persona,goal}',
  retention_days   int
);

CREATE TABLE memory_column_map (               -- survives schema renames
  logical_col  text PRIMARY KEY,               -- e.g. 'properties.price'
  physical_col text NOT NULL,
  domain       text NOT NULL,                  -- which domain whitelist owns it
  value_type   text NOT NULL                   -- int|numeric|text|id_list|bool
);
```

**How columns map to features**

| Feature | Mechanism |
|---|---|
| Preference evolution, Correction | `slot` + unique partial index: new value supersedes old; old row → `status='superseded'`, linked via `supersedes_id` (history retained: "used to prefer Downtown") |
| TTL / expiration | `expires_at`, nightly sweep |
| Confidence, Provenance | `confidence`, `provenance` columns |
| Clustering | fixed `cluster` taxonomy assigned at extraction |
| Provenance trail, Deletion audit | `memory_events` |
| Privacy controls | `user_memory_settings` + column allowlist |
| Contradiction | same `slot`, disjoint predicate values (deterministic) or high-similarity opposite-polarity free text (LLM judge) |

---

## 4. Memory item format (predicate fragments)

Every slotted memory stores a resolved, typed predicate in `structured`. `col` values are **logical** names mapped through `memory_column_map`.

| Memory | `slot` | `structured` |
|---|---|---|
| Prefers 2BR | `bedrooms` | `{"col":"properties.bedrooms","op":"eq","val":2}` |
| Prefers Dubai Marina | `preferred_location` | `{"col":"properties.location_id_v2","op":"in","val":[412],"label":"Dubai Marina"}` |
| Budget ≤ AED 2M | `budget_max` | `{"col":"properties.price","op":"lte","val":2000000,"currency":"AED"}` |
| Investor | `persona` | `{"persona":"investor","default_projection":["roi","rental_yield","price_per_sqft"]}` |
| Near metro | `proximity_metro` | `{"col":"properties.metro_distance_m","op":"lte","val":800}` |
| Wants price/sqft shown | `projection_pref` | `{"add_columns":["price_per_sqft"]}` |
| Purpose | `purpose` | `{"col":"properties.purpose","op":"eq","val":"sale"}` |
| Furnishing | `furnished` | `{"col":"properties.is_furnished","op":"eq","val":false}` |

**Episodic item** (unslotted, `type='episodic'`):

```json
{"domain":"property_search","intent":"list",
 "predicates":{"purpose":"sale","bedrooms":{"eq":2},"location_id_v2":{"in":[412]},"price":{"lte":2000000}},
 "result_meta":{"row_count":37,"median_price":1650000},
 "at":"2026-08-14T10:22:00Z"}
```

**Semantic item** (generalised, usually inferred): `content` = "Generally prefers properties within 800m of a metro station", `structured` = the `proximity_metro` predicate, `provenance='inferred'`, `confidence≈0.6`, backed by ≥3 episodic items.

---

## 5. Redis layer

| Key | Content | TTL |
|---|---|---|
| `checkpoint:*` | LangGraph checkpointer (`RedisSaver`) | 24 h |
| `wm:{thread_id}` | `QueryFrame` (working memory), active goal, thread flags (`ignore_defaults`) | 2 h idle |
| `recall:{user_id}:{hash(clusters+query)}` | Cached retrieval result | 5 min |
| `profile:{user_id}` | Cached `user_profile_summary` | 15 min; invalidated on write |
| `memq` (stream) | Extraction jobs `{user_id, thread_id, turn, query_frame, result_meta, events}` | — |

- Checkpointer: `RedisSaver` (`langgraph-checkpoint-redis`) for latency + TTL; long-term memory lives only in Postgres.
- **Redis becomes mandatory**, not optional (closes the resilience gap from the v1 architecture review).

---

## 6. Working memory — `QueryFrame`

```python
class QueryFrame(TypedDict):
    domain: str                      # property_search | market_intel | ...
    intent: str                      # list | aggregate | compare | rank
    predicates: dict                 # {"purpose":"sale","bedrooms":{"eq":2},"location_id_v2":{"in":[412]},"price":{"lte":2_000_000}}
    projection: list[str]            # columns the user cares about
    order_by: list[tuple[str, str]]  # [("price","asc")]
    limit: int
    sql: str                         # last executed SQL — Redis only, never long-term
    result_meta: dict                # {"row_count":37,"min_price":..,"p25_price":..,"max_price":..,"ids":[...top 50]}
    turn: int

class Goal(TypedDict):
    type: str                        # investment_search | rental_search | area_research | ...
    constraints: dict                # predicate fragments
    started_at: str
    expires_at: str                  # 45 days, refreshed on each related query
```

`QueryFrame.predicates` is serialised in the existing `FilterSpec` format so downstream filter code (`llm_filter_extractor.py`, `spec_adapter.py`, `property_filters.py`) is unchanged. `FilterSpec.merge_with_prior` is subsumed by the `refine_or_new` node.

`result_meta` is what makes "cheaper", "the closest to metro", "the second one", "the other three" answerable without re-running prior SQL.

---

## 7. Graph topology

```
START
 └─ load_context        Redis wm + profile cache; fallback Postgres
 └─ recall_memory       top-k relevant long-term items, gated by domain/cluster
 └─ refine_or_new       classify turn: refine | pivot | new → mutate QueryFrame
 └─ cognitive_layer     existing intent/persona; receives memory_context
 └─ sql_router → domain agents   predicate defaults merged (lowest precedence)
 └─ respond             answer-writer receives <user_memory> block
 └─ enqueue_extraction  fire-and-forget push to Redis stream `memq`
END

Background worker (separate process, consumes memq):
 extract → validate → dedupe/upsert → contradiction check → importance score → expire → periodic consolidate
```

### 7.1 State additions

```python
class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
    query_frame: QueryFrame | None        # working memory
    goal: Goal | None                     # task/goal memory
    memory_context: list[MemoryItem]      # recall output for this turn
    profile: dict                         # cached user_profile_summary.structured
    ignore_defaults: bool                 # per-thread opt-out
```

Compile:

```python
graph = builder.compile(
    checkpointer=RedisSaver(redis_url),
    store=PropQAMemoryStore(pg_pool),
)
# invoke with config={"configurable": {"thread_id": tid, "user_id": uid}}
```

### 7.2 `recall_memory`

```python
async def recall_memory(state, config, *, store):
    uid = config["configurable"]["user_id"]
    settings = await get_settings(uid)
    if not settings.memory_enabled:
        return {"memory_context": []}

    q = state["messages"][-1].content
    clusters = classify_clusters(q)                # reuse intent classifier output → subset of clusters
    if not clusters:
        return {"memory_context": []}              # off-topic → inject nothing

    items = await store.asearch(
        ("users", uid), query=q,
        filter={"status": "active", "cluster": clusters},
        limit=12,
    )
    ranked = sorted(items, key=score, reverse=True)[:6]
    await touch(ranked)                            # last_accessed_at, access_count
    return {"memory_context": ranked}

HALF_LIFE_DAYS = {"profile": 365, "preference": 90, "semantic": 120, "episodic": 30, "goal": 45, "ephemeral": 3}

def score(m):
    days = (now() - m.updated_at).days
    recency = 0.5 ** (days / HALF_LIFE_DAYS[m.type])
    return 0.45 * m.similarity + 0.25 * m.confidence + 0.20 * m.importance + 0.10 * recency
```

### 7.3 `refine_or_new`

Classifies the turn against the current `QueryFrame`:

| Class | Trigger | Action on `QueryFrame` |
|---|---|---|
| `refine` | "cheaper", "with a balcony", "the second one", "sort by yield" | delta on `predicates` / `projection` / `order_by` — e.g. "cheaper" → `price.lte = result_meta.p25_price`; "the second one" → `id in [result_meta.ids[1]]` |
| `pivot` | "what's the yield there?", "how far is that from the metro?" | new `domain`/`intent`; entity predicates (`location_id_v2`, `id`) carried |
| `new` | unrelated request | clear frame (keep `goal` unless the new query contradicts it) |

Implemented as a small structured-output LLM call (Haiku) with the frame and last message as input; deterministic shortcuts for known comparatives ("cheaper", "bigger", "newer").

### 7.4 Injection points (three, with precedence)

1. **Predicate defaults** → merged into `QueryFrame.predicates` before SQL generation at **lowest precedence**: explicit turn filters > working memory > long-term profile defaults. Only memories whose `col` is in the routed domain's whitelisted tables are eligible.
2. **Projection / ordering hints** → `default_projection`, `order_by` (investor persona → yield columns first).
3. **Answer composition** → `<user_memory>` block injected into the **response-writer** prompt only, never the SQL-writer prompt (keeps SQL generation small and deterministic).

```
<user_memory>
- [explicit] Budget ≤ AED 2M (2026-08-14)
- [inferred, 0.6] Prefers proximity to metro
- [goal] Currently searching for an investment property
</user_memory>
```

Disclosure rule: whenever a default is applied, the answer says so once — "Using your usual 2BR / ≤ AED 2M filter — say 'ignore my defaults' to search wide." The phrase sets `ignore_defaults=true` in `wm:{thread_id}` for the rest of the thread.

---

## 8. Extraction worker

### 8.1 Inputs

Per job: `(user message, QueryFrame after refine, result_meta, behavioural events)` where events = listing clicks, saves, filter changes, dwell. **Raw SQL is never an input.** Behavioural events are passed as pseudo-turns and yield `inferred` items only.

### 8.2 Output contract (structured tool call)

```json
{
  "memories": [
    {
      "op": "add | update | delete | noop",
      "type": "preference | profile | semantic | episodic | goal | ephemeral",
      "cluster": "property_prefs",
      "slot": "bedrooms",
      "content": "Prefers 2-bedroom apartments",
      "structured": {"col": "properties.bedrooms", "op": "eq", "val": 2},
      "provenance": "explicit | inferred",
      "confidence": 0.95,
      "importance": 0.7,
      "ttl_days": null,
      "target_memory_id": "<existing id if update/delete>",
      "evidence": "verbatim user text or event summary"
    }
  ]
}
```

### 8.3 Prompt rules

- **Importance:** rate 0–1; drop < 0.3 ("show me this listing" → noop; "I like balconies" → 0.6 preference).
- **Provenance / confidence:** quoted user statement → `explicit`, ≥ 0.85; behavioural inference → `inferred`, ≤ 0.6.
- **TTL:** time-bound statements ("traveling to Dubai this week") → `ephemeral`, `ttl_days=7`. Goals → 45 days, refreshed on each related query.
- **Correction:** "I don't care about Marina anymore" → `op=delete` on `preferred_location`; "actually 3 bedrooms" → `op=update`.
- **Privacy:** never emit clusters outside `allowed_clusters`; never emit nationality, religion, health, exact income, ID/passport numbers, or facts about third parties. `structured.col` must exist in `memory_column_map`.

### 8.4 Validation before insert

- `structured.col` ∈ `memory_column_map`; `val` type matches `value_type`; `id_list` values exist in `locations_v2` (or relevant dimension).
- Redaction pass on `content` and `evidence` (reuse `StreamingRedactor` patterns) for phone/email/ID.
- Reject any `content` containing SQL keywords or table/column names.

### 8.5 Upsert + contradiction

```python
async def apply(uid, ops):
    for op in ops:
        if op.slot:                                      # single-valued fact → deterministic path
            existing = await get_active_slot(uid, op.slot)
            if existing:
                if predicate_equal(existing, op):
                    bump_confidence(existing); continue
                if predicate_overlaps(existing, op):     # e.g. bedrooms eq 2 vs eq 3 → in {2,3}
                    merge_into_semantic(existing, op); continue
                if op.provenance == "explicit" or op.confidence > existing.confidence:
                    supersede(existing, new=op)          # preference evolution / correction
                else:
                    flag_contradiction(existing, op)     # keep old, log event, lower both confidences
                continue
        # unslotted (free-text preference, episodic)
        near = await store.asearch(("users", uid), query=op.content, limit=3)
        if near and near[0].similarity > 0.92:
            bump_confidence(near[0]); continue
        if any(is_negation(n, op) for n in near):        # LLM judge on the pair only
            resolve_or_flag(n, op); continue
        insert(op)
```

Resolution policy: newer **explicit** beats older anything; newer **inferred** never beats older explicit — it is flagged and the bot may ask once in a later turn ("Still avoiding furnished, or has that changed?").

---

## 9. Consolidation job (nightly + every 20th extraction per user)

| Step | Rule |
|---|---|
| Expiry | `UPDATE user_memories SET status='expired' WHERE expires_at < now() AND status='active'` |
| Decay | `inferred` items not accessed: `confidence *= 0.97` per week; < 0.3 → `expired` |
| Inference | ≥3 episodic items sharing a predicate with no explicit slot → create `semantic` inferred item (confidence 0.6) |
| Summarisation | when active items > 60 or every 7 days: LLM over all active items → rewrite `user_profile_summary` (≤150 words + merged `structured`); redundant episodic items → `superseded` |
| Clustering | fixed taxonomy assigned at extraction; optional weekly k-means over embeddings if emergent clusters are ever needed |
| Retention | `user_memory_settings.retention_days` enforced; hard-delete `deleted` rows after 30 days |

---

## 10. Deletion & privacy

- **API:** `DELETE /users/{id}/memory?cluster=property_prefs` or `?memory_id=` → `status='deleted'`, embedding nulled, `memory_events` row, Redis caches invalidated. Hard delete after 30 days.
- **In-chat:** `forget_memory(cluster | memory_id)` agent tool with `interrupt()` confirmation ("Forget all property preferences? yes/no").
- **Kill switch:** `memory_enabled=false` short-circuits `recall_memory` and `enqueue_extraction`.
- **Export:** `GET /users/{id}/memory` returns active items with `content`, `provenance`, `confidence`, `created_at` (no embeddings, no internal ids of dimension tables beyond labels).
- **Never stored:** SQL text, table/column names in `content`, protected attributes, third-party facts.

---

## 11. Database decision

| Option | Verdict | Reason |
|---|---|---|
| **pgvector on RDS** | **Yes — enable** | Memory vectors are hundreds per user, not millions; HNSW on RDS is trivial; one source of truth, transactional upserts, SQL-driven consolidation. Reuse the same extension for the pending RAG/knowledge layer. |
| Qdrant / Pinecone | No (for memory) | Only if a Qdrant cluster already exists for RAG and a single vector service is preferred, or memory rows exceed a few million. |
| Graph DB (Neo4j) | No | user → area → property relationships are already relational. |
| `langmem` | Optional | Can replace the hand-rolled extractor (§8) against a `BaseStore`; less control over confidence/TTL columns. |
| Mem0 / Hindsight / memable | Skip | Bring their own stores; the DB layer is already owned. |

---

## 12. Build order

1. **Foundations:** make Redis mandatory; move checkpointer to `RedisSaver`; add `QueryFrame` + `Goal` to state; persist to `wm:{thread_id}`. → working/task memory done.
2. **Store + recall:** DDL migration (§3); `PropQAMemoryStore(BaseStore)`; `recall_memory` with cluster + whitelist gating; profile defaults merged at lowest precedence; disclosure line in answers.
3. **Refinement:** `refine_or_new` node replacing `merge_with_prior`; `result_meta` capture after SQL execution.
4. **Extraction worker:** Redis stream consumer; explicit-only extraction first; validation + redaction; then behavioural inference.
5. **Evolution:** slot supersession, overlap merge, contradiction flagging; `forget_memory` tool; delete/export API; settings table.
6. **Consolidation:** nightly expiry/decay/inference/summarisation job; `memory_column_map` rename handling.
7. **Evals:** 30 synthetic users with scripted histories; assert recall precision (no budget predicate in `rta_intel` queries), refine correctness ("cheaper" narrows price), correction/forget behaviour, contradiction handling, and p95 added latency of `recall_memory` < 150 ms.

---

## 13. Feature checklist

| Feature | Where implemented |
|---|---|
| Short-term / conversational memory | `RedisSaver` checkpointer + `QueryFrame` |
| Long-term memory | `user_memories` + `PropQAMemoryStore` |
| User preferences | `type='preference'`, slotted predicates |
| User profile / facts | `type='profile'`, `user_profile_summary` |
| Episodic memory | `type='episodic'` query signatures |
| Semantic memory | `type='semantic'`, inferred from ≥3 episodic |
| Working memory | `QueryFrame` in state + `wm:{thread_id}` |
| Task / goal memory | `Goal` in state, 45-day TTL |
| Preference evolution | slot supersession with `supersedes_id` |
| Memory importance / relevance | extractor `importance`, threshold 0.3, retrieval score |
| Memory expiration / TTL | `expires_at`, `ephemeral` type, nightly sweep |
| Memory correction | extractor `op=update/delete`, supersession |
| Memory deletion / forgetting | `forget_memory` tool, DELETE API, `memory_events` |
| Memory confidence | `confidence` column, decay, bump-on-repeat |
| Memory provenance | `provenance` column, `source_*`, `memory_events` |
| Memory retrieval | `recall_memory` (pgvector + filters + scoring) |
| Memory summarization | consolidation job → `user_profile_summary` |
| Memory clustering | fixed `cluster` taxonomy |
| Context-aware personalization | cluster gating + domain whitelist gating |
| Contradiction detection | deterministic slot check + LLM judge on free text |
| Privacy controls | `user_memory_settings`, column allowlist, redaction, never-store list |