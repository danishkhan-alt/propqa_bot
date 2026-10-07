# Intel Routing and Query Flow

End-to-end path from a user chat message to an intel answer.

Related diagrams:

- [diagrams/end-to-end-flow.mermaid](diagrams/end-to-end-flow.mermaid)
- [diagrams/cognitive-pipeline.mermaid](diagrams/cognitive-pipeline.mermaid)
- [diagrams/classification-waterfall.mermaid](diagrams/classification-waterfall.mermaid)
- [diagrams/sql-router-fanout.mermaid](diagrams/sql-router-fanout.mermaid)
- [table-routing.md](table-routing.md) — query → domain → table whitelist / runtime hints
- [diagrams/table-routing.mermaid](diagrams/table-routing.mermaid)
- [Property_Search/property_search.md](Property_Search/property_search.md) — listings dual path + cue → tables

---

## Entry point

| Route | Role |
|---|---|
| `POST /api/chat` | Main SSE chat — cognitive pipeline (if enabled) then SQL router |
| `POST /api/chat/resume` | HITL resume stream |
| `GET /api/admin/agents` | Lists registered domain agents and live status |

Implementation: [`Backend/main.py`](../../Backend/main.py) → `stream_agent_response()` / cognitive graph.

Intel is **not** a separate REST API; routing is internal to the chat pipeline.

---

## High-level turn lifecycle

```
User query
  → cognitive_pipeline (COGNITIVE_PIPELINE=1)
      think (intent: location_intel | market_intel | valuation | …)
      enhance (skip slots for analytical intents)
      route_after_enhance → propqa_core (fast path for intel)
  → agent.py SQL router
      check_mvp_scope
      classify_query
      route_to_agents → Send(domain)
      domain ReAct agent(s) / dld_listings_pipeline
      synthesize_results
  → result_node (envelope + optional investment enrichment)
```

---

## Layer 1 — Cognitive pipeline details

### Think node

**Files:**

- [`Backend/orchestration/nodes/think.py`](../../Backend/orchestration/nodes/think.py)
- [`Backend/intent_classifier_llm.py`](../../Backend/intent_classifier_llm.py)

Haiku classifies intent into labels including:

| Intent | Meaning |
|---|---|
| `location_intel` | Area comparison, neighbourhood recommendation, community ranking |
| `market_intel` | Aggregate stats, trends, inventory counts, DLD volumes |
| `valuation` | Price band / AVM / “what is X worth” / 5-year outlook → market_intel domain |
| `rta_intel` | RTA mobility — stations, routes, ridership, parking, NOL, Salik (gated) |
| `search` / listing intents | Active property search (not intel) |

Disambiguation rules (summarized from the classifier prompt):

- Area **recommendations / rankings** → `location_intel`, not search
- DLD **historical** transaction/rental stats → `market_intel`
- Metro/bus/tram/marine stations, routes, monthly trips, parking, NOL, Salik → `rta_intel` (when `RTA_INTEL_ENABLED=1`)
- Named off-plan project trends from project data → `offplan_projects` (not market_intel)
- Engagement metrics (leads, views) → search, not market_intel

### Enhance node

**File:** [`Backend/orchestration/nodes/enhance.py`](../../Backend/orchestration/nodes/enhance.py)

For `_ANALYTICAL_INTENTS` including `location_intel`, `market_intel`, `valuation`, persona aliases, and `rta_intel`:

- Slot / FilterSpec extraction is **skipped**
- Prevents “best” / “most” being parsed as location names

### Route after enhance

**File:** [`Backend/orchestration/cognitive_pipeline.py`](../../Backend/orchestration/cognitive_pipeline.py) — `route_after_enhance`

- Intents in `{social, off_topic, define, location_intel, market_intel, valuation}` fast-path to `propqa_core`
- Ambiguous / complex queries may go through reason → rebuild → suggest → HITL → QA before core

### PropQA core

Invokes `agent._get_workflow()` with the rebuilt query. Analytical intents keep SQL agents enabled (do not force `skip_sql_agents=True` for location/market intel).

### Research branch (optional)

When `RESEARCH_AGENT_ENABLED=1`, intents `research` / `location_intel` / `market_intel` / `valuation` may enter the research flow via [`flow_router.py`](../../Backend/orchestration/flow_router.py) / research nodes. Default is off (`RESEARCH_AGENT_ENABLED=0`).

---

## Layer 2 — Classifier waterfall

**File:** [`Backend/query_classifier.py`](../../Backend/query_classifier.py)

`classify_query` (via `build_classify_node`) runs this waterfall:

1. **Respect cognitive decision** — if `skip_sql_agents` already set, do not re-classify into SQL domains
2. **`_try_fast_classify`** — **retired**; always returns `None`. Domain routing is LLM-only
3. **Perception / families** — `infer_intel_families` + `perception_prepass`
4. **`_safe_build_plan`** — optional LLM query planner ([`query_planner.py`](../../Backend/orchestration/query_planner.py))
5. **`classify_intent_llm`** — Haiku conversational pre-check
6. **Structured LLM** — `ClassificationResult` with domains + `sub_query` per domain
7. **Post-guards** — strip `rta_intel` / catalog `offplan_projects` on listing inventory; unknown domain coerced to `property_search`

Family cues (not a live regex domain router): listing inventory → `property_search`; listing count + DLD volume → `property_search` + `market_intel`; area ranking stays off the listings hijack.

Diagram: [classification-waterfall.mermaid](diagrams/classification-waterfall.mermaid). Listings pack: [[property_search]].

---

## Fan-out and domain execution

**File:** [`Backend/agent.py`](../../Backend/agent.py) — `route_to_agents`, `_make_agent_node`

1. Merge classifications per domain (dedupe)
2. Emit `Send(domain_name, state)` for each selected domain
3. Parallel ReAct agents run with:
   - User message + transcript
   - Session slots / buyer preferences
   - Domain system prompt + skill
   - Guarded `sql_db_query`

Special domain: **`dld_bridge`** → node `dld_listings_pipeline` (not a ReAct agent). See [personas/dld_bridge.md](personas/dld_bridge.md).

How a chosen domain is mapped onto **specific Postgres tables** (startup `include_tables`, regex / value-index hints, SQL guard): [table-routing.md](table-routing.md).

### Streaming holds and completeness

**File:** [`Backend/answer_completeness.py`](../../Backend/answer_completeness.py)

| Helper | Domains |
|---|---|
| `needs_streaming_hold` | `market_intel`, `location_intel`, `offplan_projects` |
| `needs_completeness_check` | `location_intel`, `market_intel` (ranking / breakdown queries) |

Repair runs before tokens are released when hold/completeness triggers fire.

---

## Synthesis

**File:** [`Backend/agent.py`](../../Backend/agent.py) — `synthesize_results`

| Case | Behaviour |
|---|---|
| Single domain | Pass-through answer; scrub schema identifiers |
| Multi domain | LLM merge of per-agent answers into one markdown response |
| Cards | Aggregated from all domain nodes into `final_cards` |

---

## Result envelope and investment enrichment

**File:** [`Backend/orchestration/nodes/result.py`](../../Backend/orchestration/nodes/result.py)

1. Build `ResultEnvelope` (`answer_md`, `cards`, `suggestions`, `citations`, `pipeline_trace`, `metadata`)
2. If think intent ∈ `{market_intel, investment_intel, investment}` and cards exist:
   - Call `services.investment_intel.enrich_cards_with_investment()` when `INVESTMENT_INTEL_ENABLED=1`

See [personas/investment_intel.md](personas/investment_intel.md).

---

## Optional multi-intent path

**Files:**

- [`Backend/orchestration/intent/intent_decomposer.py`](../../Backend/orchestration/intent/intent_decomposer.py)
- [`Backend/orchestration/intent/multi_intent_orchestrator.py`](../../Backend/orchestration/intent/multi_intent_orchestrator.py)

When `INTENT_DECOMPOSITION_ENABLED=1` and `MULTI_INTENT_ENABLED=1`:

```python
_INTENT_TO_DOMAIN = {
    "property_search": "property_search",
    "location_intel": "location_intel",
    "offplan_projects": "offplan_projects",
    "market_intel": "market_intel",
    "investment_intel": "market_intel",  # alias
    "passthrough": "property_search",
}
```

`fan_out()` resolves agents via `AgentRegistry` and runs them in parallel.

---

## Cross-domain handoff rules (classifier / prompts)

These are routing conventions, not shared imports:

| User need | Typical routing |
|---|---|
| Project + units/prices | `property_search` + `offplan_projects` |
| Area narrative + listings | `location_intel` + `property_search` (when area context is explicit) |
| DLD stats + listing cards | `dld_bridge` (not parallel market_intel + property_search) |
| ROI / yield | `market_intel` (+ investment card enrichment) |
| Named off-plan “trends” | `offplan_projects` (from project data), not DLD market_intel |

ReAct agents are **forbidden** from cross-domain DLD ↔ listings JOINs; that path is owned by `dld_bridge`.

---

## Tests covering routing

| Test | Focus |
|---|---|
| `Backend/tests/test_area_ranking_routing.py` | Area ranking → location_intel |
| `Backend/tests/test_offplan_followup_routing.py` | Off-plan follow-up routing |
| `Backend/tests/test_answer_completeness.py` | Ranking repair for LI/MI |
| `Backend/tests/test_cognitive_pipeline.py` | LI/MI must not skip SQL |
| `Backend/tests/test_intent_classifier_prompt_disambiguation.py` | Intel vs search disambiguation |
| `Backend/tests/test_query_planner.py` | Multi-domain intel plans |
| `Backend/tests/test_profile_registry.py` | Legacy intel domains + YAML profiles |

---

## Related docs

- [architecture.md](architecture.md)
- [table-routing.md](table-routing.md)
- [registration-and-config.md](registration-and-config.md)
- [README.md](README.md)

---

## Session persona layer (investor / buyer / renter)

Orthogonal to domain specialists. Alias intents expand to multi-domain host agents; scores run in `result_node`.

| Alias intent | Host domains | Notes |
|---|---|---|
| `investor_intelligence` | market_intel + location_intel | Area opportunity; distinct from card ROI `investment_intel` |
| `buyer_fit` | location_intel + property_search | Requires `PersonaContext`; else stays `location_intel` |
| `rental_intel` | location + market + property_search | New Expat ? `guided_explainer` in metadata |

Flags (default off): `PERSONA_LAYER_ENABLED`, `INVESTOR_SCORE_ENABLED`, `BUYER_FIT_SCORE_ENABLED`, `RENTAL_SUITABILITY_ENABLED`.

`skip_sql_agents` must stay false for these aliases (same contract as location/market intel). Streaming hold / completeness inherit from resolved host domains.

See `Content/persona_intel/persona-layer-architecture.md`.
