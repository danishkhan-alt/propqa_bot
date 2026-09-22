# PropQA Query + Domain Router — Contract

Implementation spec for the two routing hops. System-level architecture stays in [`propqa-ai-real-estate-agent.md`](propqa-ai-real-estate-agent.md). Memory, SQL execution, and catalog pack format are out of scope here.

**Status:** draft  
**Last updated:** 2026-09-22  
**Stack:** LangGraph · Anthropic Claude (fast model for routers) · `src/catalog`  
**Related:** `src/catalog/registry.py`, `src/catalog/domains/index.yaml`, memory spec (`QueryFrame` / `refine_or_new`)

---

## 1. What this spec owns

Every user turn must decide two things, in order:

1. **Query router** — can the model answer now, must we hit the warehouse, or do we need one clarifying question?
2. **Domain router** — if we need data, which catalog pack(s) to load into the SQL agent?

The routers never write SQL, never see full table schemas, and never invent numbers. They only produce structured decisions that the graph can branch on.

---

## 2. Hard rules

1. **Two hops, not one.** “DB or not” is a different problem from “which tables.” Mixing them makes the model load schema to answer “hi.”
2. **Smallest useful context.** Query router sees domain *names and one-liners*. Domain router sees the compact index (`id`, `name`, `description`, `synonyms`, `table_count`). Only the SQL agent sees domain YAML.
3. **Data over guesswork.** If the answer depends on a stored fact (price, volume, school, metro, inventory, fee), the route is `need_db` even when the user phrased it casually.
4. **Fail honest.** Vague asks go to `clarify`, not a 40-table query. Empty or invalid SQL is handled downstream, not by guessing a domain.
5. **Follow-ups are deltas.** A refine of the last DB turn must not re-route from scratch as if the conversation were empty.
6. **Catalog is the domain list.** Domain IDs come from `src/catalog/domains/index.yaml`. Do not invent IDs such as `property_search` or `communities_intel`.

---

## 3. Graph placement

```
START
 └─ load_context          last route, last domain_ids, QueryFrame / result summary if present
 └─ query_router          direct_answer | need_db | clarify  +  turn_kind
      ├─ direct_answer ──► answer
      ├─ clarify ────────► answer (one question, no SQL)
      └─ need_db
           └─ domain_router     1–N domain ids + optional join domain
           └─ catalog.load      full YAML for selected ids only
           └─ sql_agent         run_sql tool (other spec)
           └─ answer
 └─ catalog.unload        drop packs unless the next turn is a refine of the same domains
END
```

Query router always runs. Domain router runs only on `need_db`. Direct and clarify never load catalogs.

---

## 4. State contract

Routers read and write these fields. SQL agent and memory layers may add more; they must not overwrite router fields except via their own nodes.

```python
from typing import Annotated, Literal, TypedDict
from langgraph.graph.message import add_messages

Route = Literal["direct_answer", "need_db", "clarify"]
TurnKind = Literal["new", "refine", "pivot"]

class QueryRoute(TypedDict):
    route: Route
    turn_kind: TurnKind
    confidence: float          # 0..1
    rationale: str             # one sentence, for traces
    clarify_question: str | None

class DomainRoute(TypedDict):
    domain_ids: list[str]      # primary packs to load in full
    join_ids: list[str]        # usually ["locations"]; load join keys only
    confidence: float
    rationale: str

class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
    query_route: QueryRoute | None
    domain_route: DomainRoute | None
    loaded_domains: list[str]  # currently in SQL-agent context
    last_need_db: dict | None  # {domain_ids, intent_summary, result_meta} for follow-ups
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

`clarify_question` is required when `route=clarify`, null otherwise.

### 5.3 Routes

| Route | When | Next |
| --- | --- | --- |
| `direct_answer` | No stored fact is required | Answer node, no catalog |
| `need_db` | Answer depends on warehouse data | Domain router |
| `clarify` | Not enough constraint to query *or* answer honestly | Answer node asks **one** focused question |

### 5.4 Direct-answer

Use when the turn is language, product, or process:

- Greetings and capability questions (“hi”, “what can you do?”)
- Definitions and how-to (“what is RERA?”, “how do I read a title deed?”)
- Policy / product explanation that is not a row in `chatbot_ai`
- Restating or explaining the last grounded answer with **no new filter, entity, or metric**

Forbidden on this route: prices, averages, inventory counts, school names, metro distances, fees, “is this a good deal” without a referenced property, anything the model would have to invent.

### 5.5 Need-DB

Use when a correct answer needs a lookup. Bias here whenever a number *might* be required.

Examples:

- “Average sale price in Dubai Marina last 12 months”
- “2-bed apartments in JVC under 1.2M”
- “Schools within 2 km of this building”
- “Metro / parking around Downtown”
- “Compare transaction volume in Business Bay vs Marina”
- “What is Emaar handing over this year?”
- “Service charges in that community”

Follow-ups that **change a filter or ask a new metric** are `need_db`, not `direct_answer`: “cheaper”, “only villas”, “what about the yield”, “and schools near those”.

### 5.6 Clarify

Use when running SQL would be a lottery:

- “Show me properties” with no location, type, purpose, or budget
- “Is this a good deal?” with no property or area in the thread
- “Best area to invest” with no budget, horizon, or persona
- Ambiguous entity that would hit many rows (“Marina” when the thread has never disambiguated, and the ask is otherwise unconstrained)

Ask **one** question. Prefer the missing constraint that unblocks a query (location, purpose sale/rent, budget, which building). Do not interview.

If history already supplies the missing slot, this is `need_db` + `refine`, not `clarify`.

### 5.7 `turn_kind`

Classified against `last_need_db` (later: `QueryFrame`).

| Kind | Trigger | Effect |
| --- | --- | --- |
| `new` | Unrelated ask, or no prior DB turn | Fresh domain routing |
| `refine` | Same subject, delta on filters / sort / projection / “the second one” | Domain router **reuses** `last_need_db.domain_ids` unless a new subject appears |
| `pivot` | Same entities, different subject (“yield there?”, “schools near that building?”) | Domain router **re-runs**, may keep location/entity ids in working memory |

Deterministic shortcuts (no LLM) when the message matches a small comparative lexicon and `last_need_db` exists: cheaper, bigger, nearer, newer, the second one, sort by X, only / without X. Those are `need_db` + `refine` at confidence 1.0.

`turn_kind` is ignored on `direct_answer` except: explaining the previous answer without new filters stays `refine` so we do not unload context prematurely.

### 5.8 Confidence

| Band | Action |
| --- | --- |
| ≥ 0.7 | Take the route |
| 0.4–0.7 | Take it, but log `low_confidence`; if the tie is `direct_answer` vs `need_db`, prefer `need_db` |
| < 0.4 | If the question *could* need data → `need_db`; if it is empty/gibberish → `clarify` |

Never use low confidence as a reason to `direct_answer` a market question.

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
- `join_ids`: domains needed only as join keys. Default `["locations"]` when any primary domain declares a locations join **and** the question is geo-scoped. Do not put `locations` in `domain_ids` unless the user asked about communities / hierarchy / “where is” as the *subject*.
- Every id must exist in the index. Unknown ids → drop and, if none remain, `clarify` via the answer node (“I don’t have a dataset for that yet”).

### 6.3 Caps

| Rule | Value |
| --- | --- |
| Max primary domains | 2 (3 only if the ask is explicitly comparative across three subjects) |
| Max total loaded (`domain_ids` + `join_ids`) | 3 |
| Refine reuse | If `turn_kind=refine` and no new subject, skip the LLM and copy `last_need_db.domain_ids` / `join_ids` |

If the model returns more than the cap, keep the top 2 by its own order and trace the truncation.

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

Overall spec default. One fast Claude call per hop. JSON schema = the TypedDicts above.

- Query router: no tools.
- Domain router: no tools; index inlined from `list_domains()`.

Optional later: embedding / synonym hit as a **pre-filter** that restricts candidate domain ids before the LLM. Never replace the LLM with embeddings-only for `direct_answer` vs `need_db`.

### 7.2 Deterministic bypasses

Run **before** the query-router LLM:

1. Empty / whitespace message → `clarify`.
2. Comparative lexicon + existing `last_need_db` → `need_db` + `refine`.
3. Explicit “ignore my defaults” / “search wide” → still `need_db` if the ask is a lookup; memory layer handles the flag.

Run **before** the domain-router LLM:

1. `turn_kind=refine` and no new subject keywords → reuse last domains.
2. If the query-router rationale already named valid domain ids, treat them as a prior; the domain router may confirm or replace.

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
- `need_db` when prices, inventory, schools, transport, developers, fees, or any stored attribute are required. Prefer `need_db` over guessing.
- `clarify` when a query would be unconstrained. One question.
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
| `router.query` | `route`, `turn_kind`, `confidence`, `rationale`, `clarify_question`; model, tokens, latency |
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
| Query router says `direct_answer` but message has a number/area/school/metro | Downstream guard: if a cheap regex/gazetteer hits, override to `need_db` and trace `override=heuristic` |
| Domain router wants 5 packs | Truncate to 2 + `locations` join |
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
7. “Show me properties” → `clarify`.
8. Follow-up “cheaper” after a transactions turn → `need_db` + `refine`, same domains, no new pack.
9. Pivot “schools near those” → `pivot`, `schools` added, locations join kept.
10. Asking-price wording → not `direct_answer`; closest domain + later disclosure.

Pass bar for the router (separate from SQL correctness): **≥ 90%** route accuracy, **≥ 85%** primary-domain exact-set match on the golden set. Log disagreements in Langfuse.

---

## 12. Build slices

1. `QueryRoute` schema + query-router node + direct/clarify answers. No SQL. Langfuse `router.query`.
2. Golden evals for §11 cases 1, 2, 7 (can mock domain router).
3. `DomainRoute` + `list_domains()` prompt + Langfuse `router.domain`. Still no SQL.
4. Deterministic refine bypass + `last_need_db` in state.
5. Wire `catalog.load` / unload into the SQL agent (SQL spec). Heuristic override for false `direct_answer`.
6. Expand evals; prompt-tune confusions in §6.5.

---

## 13. Out of scope

- SQL generation, `run_sql` guards, row caps — overall spec §8 / SQL spec.
- Catalog YAML shape and table assignment — already in `src/catalog/domains/*.yaml`.
- Long-term memory extraction — memory architecture spec. When that lands, `recall_memory` runs **before** query router; routers still do not receive full memory items, only a short profile blurb if needed for clarify.
- Per-domain ReAct fan-out (`property_search`, …). This spec uses **one SQL agent** and **catalog packs**. Memory-spec agent names are not domain ids.

---

## 14. Open decisions

These do not block the contract above. Resolve before production tuning.

1. **Asking-price gap:** user-facing copy when they want classified listings we do not store — router vs answer node. Default: router picks closest domain; answer node discloses.
2. **Join-only load:** add a `load_joins(domain_id, keys)` helper vs loading full `locations` YAML.
3. **Split `refine_or_new`:** keep `turn_kind` on the query router (this spec) vs a dedicated node as in the memory spec. Default: keep on query router until latency or quality says otherwise.
4. **Fast model choice:** Haiku vs equivalent OpenAI mini for both hops; measure p95 and eval scores before locking.
5. **Gazetteer override** for false `direct_answer` (§10): reuse streaming QU gazetteer when it exists; until then, a small area/school/RTA keyword list.
