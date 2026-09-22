# PropQA Query + Domain Router — Contract

Implementation spec for the two routing hops. System-level architecture stays in [`propqa-ai-real-estate-agent.md`](propqa-ai-real-estate-agent.md). Memory, SQL execution, and catalog pack format are out of scope here.

**Status:** draft  
**Last updated:** 2026-09-22  
**Stack:** LangGraph · Anthropic Claude (fast model for routers) · `src/catalog`  
**Related:** `src/catalog/registry.py`, `src/catalog/domains/index.yaml`, memory spec (`QueryFrame` / `refine_or_new`)

---

## 1. What this spec owns

Every user turn must decide two things, in order:

1. **Query router** — can the model answer now, or must we hit the warehouse?
2. **Domain router** — if we need data, which catalog pack(s) to load into the SQL agent?

The routers never write SQL, never see full table schemas, and never invent numbers. They only produce structured decisions that the graph can branch on.

---

## 2. Hard rules

1. **Two hops, not one.** “DB or not” is a different problem from “which tables.” Mixing them makes the model load schema to answer “hi.”
2. **Smallest useful context.** Query router sees domain *names and one-liners*. Domain router sees the compact index (`id`, `name`, `description`, `synonyms`, `table_count`). Only the SQL agent sees domain YAML.
3. **Data over guesswork.** If the answer depends on a stored fact (price, volume, school, metro, inventory, fee), the route is `need_db` even when the user phrased it casually.
4. **The model states the filters.** There is no clarify route. A vague warehouse question is still `need_db`. Purpose, limit, and order come from the query router. Null means the user did not say, and the previous lookup does not carry it. No keyword list fills those in. Empty or invalid SQL is handled downstream, not by guessing a domain.
5. **Follow-ups are deltas.** A refine of the last DB turn must not re-route from scratch as if the conversation were empty.
6. **Catalog is the domain list.** Domain IDs come from `src/catalog/domains/index.yaml`. Do not invent IDs such as `property_search` or `communities_intel`.

---

## 3. Graph placement

```
START
 └─ load_context          last route, last domain_ids, QueryFrame / result summary if present
 └─ query_router          direct_answer | need_db  +  turn_kind + intent
      ├─ direct_answer ──► answer
      └─ need_db           purpose, limit, and order are whatever the query router set
           └─ domain_router     1–N domain ids + optional join domain
           └─ catalog.load      full YAML for selected ids only
           └─ sql_agent         run_sql tool (other spec)
           └─ answer
 └─ catalog.unload        drop packs unless the next turn is a refine of the same domains
END
```

Query router always runs. Domain router runs only on `need_db`. Direct answers never load catalogs.

---

## 4. State contract

Routers read and write these fields. SQL agent and memory layers may add more; they must not overwrite router fields except via their own nodes.

Structured outputs are Pydantic models (`QueryRoute`, `DomainRoute`, `LastNeedDb` in `src/agent/schemas/routes.py`). Graph state stays a `TypedDict` so LangGraph can apply the message reducer.

```python
class QueryRoute(BaseModel):
    route: Route                 # direct_answer | need_db
    turn_kind: TurnKind          # new | refine | pivot
    intent: Intent               # list | lookup | aggregate | trend | compare | rank | assess | other
    confidence: float            # 0..1
    rationale: str               # one sentence, for traces

class DomainRoute(BaseModel):
    domain_ids: list[str]        # primary packs to load in full
    join_ids: list[str]          # usually ["locations"]; load join keys only
    confidence: float
    rationale: str

class ChatState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    user_id: str
    query_route: QueryRoute | None
    domain_route: DomainRoute | None
    loaded_domains: list[str]    # cleared before checkpoint
    catalog_context: str         # full YAML for this turn only; cleared before checkpoint
    last_need_db: LastNeedDb | None
    assumptions: Assumptions | None   # purpose, limit, order from the query router; null when unset
    awaiting_sql: bool
```

Compile with thread_id + user_id in `configurable`. Persist `last_need_db` in thread state (and later in `QueryFrame` / Redis working memory). Do not persist full catalogs in the checkpointer.

---

## 5. Query router

First hop on every turn. Cheap, schema-blind, structured output.

### 5.1 Input (prompt context)

| Include | Exclude |
| --- | --- |
| Current user message | Full domain YAML / columns |
| Last 1–2 turns, or a short thread summary | Raw SQL, row grids |
| `last_need_db` compact summary if any | User PII beyond what the message already contains |
| Domain index: `id` + one-line `description` only | Tool schemas, warehouse errors |

The domain one-liners exist so the model can tell “this is a warehouse question” vs “this is a definition.” They are not for picking tables.

### 5.2 Output

JSON matching `QueryRoute`. Reject / retry once if the payload is malformed. Default on second failure: `need_db` with `turn_kind=new` and `confidence=0.3` (safer than a guessed market number).

### 5.3 Routes

| Route | When | Next |
| --- | --- | --- |
| `direct_answer` | No stored fact is required | Answer node, no catalog |
| `need_db` | Answer depends on warehouse data | Apply defaults, then the domain router |

### 5.4 Direct-answer

Use when the turn is language, product, or process:

- An empty or whitespace message (a short greeting, no question)
- Greetings and capability questions (“hi”, “what can you do?”)
- Definitions and how-to (“what is RERA?”, “how do I read a title deed?”)
- Policy / product explanation that is not a row in `chatbot_ai`
- Restating or explaining the last grounded answer with **no new filter, entity, or metric**

Forbidden on this route: prices, averages, inventory counts, school names, metro distances, fees, “is this a good deal” without a referenced property, anything the model would have to invent.

### 5.5 Need-DB

Use when a correct answer needs a lookup. Bias here whenever a number *might* be required.

Examples:

- “Show me properties” — `need_db`, intent `list`. Purpose and limit stay null unless this message or the previous lookup states them.
- “Average sale price in Dubai Marina last 12 months”
- “2-bed apartments in JVC under 1.2M”
- “Schools within 2 km of this building”
- “Metro / parking around Downtown”
- “Compare transaction volume in Business Bay vs Marina”
- “What is Emaar handing over this year?”
- “Service charges in that community”

Follow-ups that **change a filter or ask a new metric** are `need_db`, not `direct_answer`: “cheaper”, “only villas”, “what about the yield”, “and schools near those”.

### 5.6 Purpose, limit, and order

The query router sets these on every `need_db` turn. They are not filled in afterwards by a word list.

| Field | When it is set | When it is null |
| --- | --- | --- |
| `purpose` | The user stated it, or a follow-up keeps the previous one | Neither this message nor `last_need_db` says |
| `limit` | The user asked for a count, or a refine keeps the previous count | No count was given |
| `order` | The user said how to order the rows | They did not say |

The answer uses those values. It does not invent a purpose or a row count, and it does not stop to ask.

### 5.7 `turn_kind`

Classified against `last_need_db` (later: `QueryFrame`).

| Kind | Trigger | Effect |
| --- | --- | --- |
| `new` | Unrelated ask, or no prior DB turn | Fresh domain routing |
| `refine` | Same subject, delta on filters / sort / projection / “the second one” | Domain router **reuses** `last_need_db.domain_ids` |
| `pivot` | Same entities, different subject (“yield there?”, “schools near that building?”) | Domain router **re-runs**, may keep location/entity ids in working memory |

The model classifies the kind. Code does not match the message against a word list. When the model says `refine` and a previous lookup exists, the domain model is skipped and the previous packs are copied.

`turn_kind` is ignored on `direct_answer` except: explaining the previous answer without new filters stays `refine` so we do not unload context prematurely.

### 5.8 Confidence

| Band | Action |
| --- | --- |
| ≥ 0.7 | Take the route |
| < 0.7 | Take the model's route, and log `low_confidence` |

A low score is a trace note. It does not rewrite the route.

---

## 6. Domain router

Second hop, `need_db` only. Picks packs from the live index.

### 6.1 Input

| Include | Exclude |
| --- | --- |
| Current message | Column lists, few-shot SQL, pitfalls |
| `turn_kind` and `last_need_db` | Full YAML |
| Compact index from `list_domains()`: `id`, `name`, `description`, `synonyms`, `table_count` | Tables omitted from the catalog (courts, visas, flights, chats, ridership) |
| Join hint: `locations` is the usual bridge | Memory embeddings, user profile (until memory spec is wired) |

Build the index prompt from `catalog.list_domains()`. Do not hardcode domain copy in the prompt file; the YAML is the source of truth.

### 6.2 Output

JSON matching `DomainRoute`.

- `domain_ids`: 1–2 primary domains, rarely 3. Order = relevance.
- `join_ids`: domains needed only as join keys. The domain model puts `locations` here when the question needs a place and locations is not the subject. Code does not add that join from a place-name list.
- Every id must exist in the index. Unknown ids → drop and, if none remain, answer that there is no dataset for that.

### 6.3 Caps

| Rule | Value |
| --- | --- |
| Max primary domains | 3 |
| Max total loaded (`domain_ids` + `join_ids`) | 3 |
| Refine reuse | If the model set `turn_kind=refine` and `last_need_db` exists, skip the domain model and copy `domain_ids` / `join_ids` |

If the model returns more than the cap, keep the top entries by its own order and trace the truncation. Do not add a pack it did not name.

### 6.4 Live domain map

From `src/catalog/domains/index.yaml`. Router must follow **description + pitfalls**, not the English word the user used.

| ID | Load when the user wants | Do not use for |
| --- | --- | --- |
| `listings` | What exists: units, plots, buildings, freehold, type/size/status | Asking prices, sold prices, rents (no classified listings in this warehouse) |
| `transactions` | Sold prices, volumes, registered rents (Ejari), valuations, community averages | City-wide indices, “what units exist” |
| `locations` | Community / subcommunity / Makani / “where is” as the question | Silent join-only needs (those go in `join_ids`) |
| `developers` | Who builds what, off-plan, handover, permits, contractors, escrow | Completed-unit inventory (that is `listings`) |
| `schools` | KHDA schools, fees, ratings, nearby schools | Parks, hospitals, “amenities” |
| `rta` | Metro, tram, bus, marine, parking, Salik, roads, commute | Lifestyle POIs |
| `amenities` | Parks, beaches, hospitals/clinics, things-to-do | Schools, metro, building gym/pool attributes |
| `agencies` | Brokers, agencies, valuators, owners associations, RERA license | Listings or deals |
| `regulations` | OA service charges, DLD property-map / site-plan procedures | General “is this legal” advice with no table |
| `market` | DSC price/rent indices, construction-cost series, building-stock aggregates | Deal-level or community average prices (`transactions`) |

### 6.5 Common confusions (must be in the prompt)

| User phrasing | Correct pack |
| --- | --- |
| “listings / apartments for sale in JVC under 1.2M” | `listings` for inventory **if** they want what exists; `transactions` if they want what **sold** or contracted rent. If they want current asking price, we **cannot** answer from this warehouse — domain router still picks `listings` or `transactions` as closest, and the SQL/answer layer must say asking prices are not in the DB. |
| “average price in Marina” | `transactions` (+ `locations` join). Not `market`. |
| “is the market up?” / “price index” | `market` |
| “near good schools” | `schools` (+ listings or locations as primary) |
| “near metro / parking” | `rta` |
| “pool, beach, hospital” | `amenities` (building amenities that live on listing/building tables stay with `listings`) |
| “Emaar handover / off-plan” | `developers` |
| “who is the agent / OA” | `agencies` |
| “service charge” | `regulations` |

### 6.6 Multi-domain examples

| Question | `domain_ids` | `join_ids` |
| --- | --- | --- |
| Average sale price in Dubai Marina last 12 months | `transactions` | `locations` |
| 2-bed freehold units in JVC | `listings` | `locations` |
| 2-beds in JVC near good schools | `listings`, `schools` | `locations` |
| Parking and metro around Downtown | `rta` | `locations` |
| Emaar handovers this year in Dubai Hills | `developers` | `locations` |
| Service charges vs recent sales in that community | `regulations`, `transactions` | `locations` |
| Price index vs last year’s transaction volume | `market`, `transactions` | `[]` |
| What community is this building in? | `locations` | `[]` |
| Brokers licensed for this building | `agencies` | `locations` |

### 6.7 Refine / pivot behaviour

- **`refine`:** skip domain LLM; keep packs; SQL agent applies the delta. If the refine introduces a new subject (“also schools”), treat as `pivot`.
- **`pivot`:** re-run domain LLM with prior `domain_ids` shown as hints; entity predicates (area, building) carry via working memory, not via re-extracting from chat.
- **`new`:** unload previous packs; route from scratch.

---

## 7. Implementation

### 7.1 Default: structured-output LLM

Overall spec default. One fast Claude call per hop (`ROUTER_MODEL`, default `claude-haiku-4-5`) with `with_structured_output(..., method="json_schema")`. The schema is the Pydantic model.

- Query router: no tools.
- Domain router: no tools; index inlined from `list_domains()`.

Optional later: embedding / synonym hit as a **pre-filter** that restricts candidate domain ids before the LLM. Never replace the LLM with embeddings-only for `direct_answer` vs `need_db`.

### 7.2 What code may change after the model

The query router always runs. Nothing is classified from a keyword list before that call.

After the model returns:

1. `turn_kind=refine` with no `last_need_db` becomes `new`.
2. `turn_kind=refine` with a previous lookup reuses those domain ids and skips the domain model.
3. Unknown domain ids are dropped. More than 3 packs are truncated. No join is added that the model did not name.

### 7.3 Catalog API the routers use

```python
from catalog import list_domains, load_domains, load_prompt

index = list_domains()                 # query + domain routers
packs = load_domains(domain_ids)       # SQL agent only
fragment = load_prompt(domain_ids)     # YAML dumped into SQL-agent context
```

`join_ids` are loaded as **join snippets**, not full packs, once catalog YAML supports a join-only view. Until then, loading `locations` in full is allowed but must be traced as `join`. Unload with the rest of the working set.

### 7.4 Ownership

| Package | Owns |
| --- | --- |
| `src/agent` (to be added) | `query_router` node, `domain_router` node, state, prompts |
| `src/catalog` | Index, packs, `list_domains` / `load_*` |
| `src/evals` | Golden route + domain labels |
| Langfuse | `router.query`, `router.domain` generations |

---

## 8. Prompt sketches

Keep prompts in code or Langfuse, versioned. Below is the contract, not the final copy.

### 8.1 Query router

System: You route a Dubai real-estate chatbot turn. You do not answer the user. You do not write SQL.

- `direct_answer` only when no warehouse fact is needed.
- `need_db` when prices, inventory, schools, transport, developers, fees, or any stored attribute are required. Prefer `need_db` over guessing. Missing filters use defaults; do not ask instead of routing.
- Classify `turn_kind` against the prior DB summary.
- Return JSON only.

User payload: `{message, history_summary, last_need_db, domain_blurbs}`.

### 8.2 Domain router

System: You pick catalog domains for a text-to-SQL agent.

- Choose from the provided index only.
- Prefer the domain whose description matches the *metric*, not the surface noun (“average price” → `transactions`, not `listings` or `market`).
- Cap 2 primary domains. Put geo hierarchy in `join_ids` unless the question is about locations themselves.
- If the warehouse cannot answer (e.g. classified asking prices), still pick the closest domain; do not invent a new id.

User payload: `{message, turn_kind, last_need_db, index}`.

---

## 9. Observability

One Langfuse trace per user turn. Router hops are child generations.

| Observation | Capture |
| --- | --- |
| `router.query` | `route`, `turn_kind`, `intent`, `confidence`, `rationale`, assumptions; model, tokens, latency |
| `router.domain` | `domain_ids`, `join_ids`, `confidence`, `rationale`; whether reuse skipped the LLM |
| `catalog.load` / `catalog.unload` | ids, table_count sum |

Tags: `route:{...}`, `domains:{id,...}`, `turn_kind:{...}`.  
Local logs: same fields via `get_logger("agent.router")`. No SQL, no row samples, no secrets.

---

## 10. Failure modes

| Failure | Behaviour |
| --- | --- |
| Malformed router JSON | One retry with “return valid JSON”; then conservative default (§5.2 / drop unknown domains) |
| Domain id not in index | Drop it; if empty → user-facing “no dataset for that yet” |
| Query router says `direct_answer` on a market question | Take that route. Fix it in the prompt and the golden set, not with a keyword override |
| Domain router wants 5 packs | Truncate to 3. Do not add a join the model did not name |
| Refine with missing `last_need_db` | Treat as `new` |
| User asks for asking prices / Bayut-style listings | Route to `listings` or `transactions`; SQL/answer spec must disclose the gap — **not** a `direct_answer` hallucination |

---

## 11. Evals

Golden set in `src/evals` (add as we implement). Each case: user message (+ optional history) → expected `route` → expected `domain_ids` (order-insensitive) → optional `join_ids`.

Minimum slices:

1. Greetings / definitions → `direct_answer`, no domains.
2. Community average price → `need_db`, `transactions` + locations join.
3. Inventory search → `need_db`, `listings`.
4. “Is the market up?” → `need_db`, `market`.
5. Schools near an area → `schools` (+ listings or locations).
6. Metro / parking → `rta`.
7. A list with no count and no previous lookup → `need_db`, with `purpose` and `limit` null.
8. Follow-up “cheaper” after a transactions turn → `need_db` + `refine`, same domains, no new pack.
9. Pivot “schools near those” → `pivot`, `schools` added, locations join kept.
10. Asking-price wording → not `direct_answer`; closest domain + later disclosure.

Pass bar for the router (separate from SQL correctness): **≥ 90%** route accuracy, **≥ 85%** primary-domain exact-set match on the golden set. Log disagreements in Langfuse.

---

## 12. Build slices

1. `QueryRoute` schema + query-router node + direct answers. No SQL. Langfuse `router.query`.
2. Golden evals for §11 cases 1, 2, 7 (can mock domain router).
3. `DomainRoute` + `list_domains()` prompt + Langfuse `router.domain`. Still no SQL.
4. Deterministic refine bypass + `last_need_db` in state.
5. Wire `catalog.load` / unload into the SQL agent (SQL spec). Heuristic override for false `direct_answer`.
6. Expand evals; prompt-tune confusions in §6.5.

---

## 13. Out of scope

- SQL generation, `run_sql` guards, row caps — overall spec §8 / SQL spec.
- Catalog YAML shape and table assignment — already in `src/catalog/domains/*.yaml`.
- Long-term memory extraction — memory architecture spec. When that lands, `recall_memory` runs **before** query router; routers still do not receive full memory items, only a short profile blurb.
- Per-domain ReAct fan-out (`property_search`, …). This spec uses **one SQL agent** and **catalog packs**. Memory-spec agent names are not domain ids.

---

## 14. Open decisions

These do not block the contract above. Resolve before production tuning.

1. **Asking-price gap:** user-facing copy when they want classified listings we do not store — router vs answer node. Default: router picks closest domain; answer node discloses.
2. **Join-only load:** add a `load_joins(domain_id, keys)` helper vs loading full `locations` YAML.
3. **Split `refine_or_new`:** keep `turn_kind` on the query router (this spec) vs a dedicated node as in the memory spec. Default: keep on query router until latency or quality says otherwise.
4. **Fast model choice:** Haiku vs equivalent OpenAI mini for both hops; measure p95 and eval scores before locking.
5. **False `direct_answer`:** do not override the model with a gazetteer or keyword list. Correct it in the prompt and the golden set.
