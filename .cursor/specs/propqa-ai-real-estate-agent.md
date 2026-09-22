# Propqa AI Real Estate Agent — Overall Spec

Living architecture document for the Propqa real-estate chatbot. This is the source of truth for product scope, routing, schema context, SQL access, and observability. Implementation details belong in follow-up specs; this file stays at the system level.

**Status:** draft  
**Last updated:** 2026-09-22  
**Related folders:** `src/agent`, `src/catalog`, `src/routes`, `src/evals`

---

## 1. What we are building

A conversational real-estate agent for Propqa (AI real estate). The agent answers questions about the Dubai / UAE property market using data already stored in our database.

Most questions need live data: listings, transactions, RTA records, schools, amenities, and similar datasets. Those go through **text-to-SQL**. Simple questions that do not need a lookup — greetings, product help, definitions, how-to, clarification — are answered **directly by the LLM**.

This is not “always SQL.” The hard rule is: **use the database when the answer depends on stored facts; otherwise answer from the model.**

---

## 2. Problem this architecture solves

The warehouse has **100+ tables**. Dumping every table, column, join, and example into one prompt is too large, too noisy, and too expensive. The model then writes worse SQL.

We solve that with two routers and a catalog:

1. **Query router** — does this turn need the database, or can the model answer now?
2. **Domain / table router** — if we need data, which *group* of tables is relevant?

Only the selected domain catalog is loaded into the SQL agent. Unused schema is not in context. After the turn (or when the user changes topic), that catalog can be unloaded.

---

## 3. Design principles

1. **Data over guesswork.** Market facts, prices, volumes, inventory, school names, RTA fields, and listing attributes come from SQL. The model does not invent them.
2. **Smallest useful context.** Never send all 100+ tables. Load only the domain(s) required for this turn.
3. **SQL is a tool, not the whole agent.** The graph can answer without calling it.
4. **Read-only by default.** The SQL tool only runs `SELECT` (plus `WITH` / `EXPLAIN` if we allow them). No writes, no DDL.
5. **Trace every decision.** Router choice, selected domains, generated SQL, row counts, latency, tokens, and errors go to Langfuse.
6. **Fail honestly.** If SQL is empty, invalid, or the domain is unclear, say so and ask a follow-up. Do not fabricate numbers.

---

## 4. High-level architecture

```
User message
    │
    ▼
┌──────────────────────────┐
│  Query router            │  direct_answer  |  need_db  |  clarify
└────────────┬─────────────┘
             │
     ┌───────┴────────┐
     │                │
     ▼                ▼
 Direct LLM      Domain / table router
 answer          (pick 1–N domains)
                      │
                      ▼
              Load domain catalog
              (tables, columns, joins, examples)
                      │
                      ▼
              Text-to-SQL agent
              (SQL DB as tool)
                      │
                      ▼
              Execute read-only SQL
                      │
                      ▼
              Synthesize grounded answer
                      │
                      ▼
              Unload unused domain context
```

Intended stack (matches the current repo skeleton):

| Layer | Role |
| --- | --- |
| `src/routes` | HTTP / chat API, session, auth |
| `src/agent` | LangGraph (or equivalent): routers, tools, answer node |
| `src/catalog` | Domain registry, table metadata, load / unload |
| `src/evals` | Golden questions, SQL correctness, answer quality |
| Langfuse | Traces, generations, tool spans, later scores / datasets |

HTTP is FastAPI. Shared infrastructure lives in `src/common` (no Django, no email). Cache and rate limits use Redis. Callers are either **registered** or **visitors**. Config already has Anthropic / OpenAI, Langfuse, warehouse (`AUDIT_DB_*`, `DB_SEARCH_PATH`), and `REDIS_URL`.

---

## 5. Query router

First hop on every user turn. Input: current message + short conversation summary (not the full schema).

### 5.1 Routes

| Route | When | Next step |
| --- | --- | --- |
| `direct_answer` | No stored fact is required | LLM answers immediately |
| `need_db` | Answer depends on warehouse data | Domain router → SQL tool |
| `clarify` | Intent is too vague to query safely | Ask one focused question |

### 5.2 Direct-answer examples

- “Hi, what can you help with?”
- “What is RERA?”
- “How do I read a title deed?”
- Follow-ups that only rephrase the last grounded answer, with no new filter.

### 5.3 Need-DB examples

- “Average sale price in Dubai Marina last 12 months”
- “Schools within 2 km of this building”
- “List 2-bed apartments in JVC under 1.2M with a pool”
- “RTA / traffic or parking around Downtown”
- “Compare transaction volume in Business Bay vs Marina”

### 5.4 Clarify examples

- “Show me properties” (no location, type, or budget)
- “Is this a good deal?” with no property referenced

### 5.5 Bias

When a question *might* need numbers, prefer `need_db` over guessing. Direct answers are for language, process, and definitions — not market facts.

The query router should **not** receive full table schemas. It only needs a short list of domain names and one-line descriptions so it can decide “DB or not.” Fine-grained table choice is the next hop.

---

## 6. Domain / table router

Second hop, only on `need_db`. Tables are grouped into **domains**. The router sees a compact catalog of domains, not every column.

### 6.1 Why domains

- 100+ tables will not fit usefully in one prompt.
- Real-estate questions usually hit one or two subjects, not the whole warehouse.
- Schema, join keys, and few-shot SQL can live next to the domain that needs them.

### 6.2 Initial domain map

These groups are the starting catalog. Names and table lists will be refined once we inventory the live schema.

| Domain ID | What it covers | Typical questions |
| --- | --- | --- |
| `listings` | Active / historical property listings, asking prices, beds, baths, size, status | “Show 2-beds in JVC under 1.2M” |
| `transactions` | Sales and rental transactions, prices, dates, buyers/sellers if present | “Average sale price in Marina last year” |
| `rta` | Dubai RTA: traffic, parking, transport, related location data | “Parking / metro near Downtown” |
| `schools` | School locations, ratings, curricula, catchments | “Best schools near Arabian Ranches” |
| `amenities` | Pools, gyms, parks, malls, community facilities | “Buildings with a pool and gym in JLT” |
| `locations` | Areas, communities, buildings, geo hierarchy, coordinates | “What community is this building in?” |
| `developers` | Developers, projects, handover, off-plan metadata | “What is Emaar handing over this year?” |
| `regulations` | RERA / DLD / permit / fee style reference tables if stored | “What is the DLD fee on this sale?” |

A question may select **more than one** domain. Example: “2-bed listings in JVC near good schools” → `listings` + `schools` (+ `locations` if needed for joins).

Cap selected domains (suggested: **max 2**, rarely 3). If more look necessary, prefer `clarify` or a two-step tool plan rather than loading half the warehouse.

### 6.3 Domain catalog record

Each domain in `src/catalog` should eventually hold:

- `id`, display name, one-line description, synonyms / trigger phrases
- table names in that domain
- column glossary (only useful columns, with types and meaning)
- join keys to other domains (especially `locations`)
- grain (row = listing, transaction, school, building, …)
- date / geo / currency conventions
- 2–5 few-shot NL → SQL examples
- common pitfalls (e.g. sale vs rent, asking vs transacted price)
- allowed vs forbidden tables inside the domain

The **router view** of a domain is only `id + description + synonyms`. The **SQL-agent view** is the full record above, loaded after routing.

### 6.4 Cross-domain joins

`locations` is the usual bridge (community, building, coordinates). When two domains are selected, also load the documented join keys between them — not every table in `locations`.

---

## 7. Dynamic context load and unload

Context is a working set, not a permanent dump.

### 7.1 Always-on (tiny)

- Agent role and product rules
- Query-router instructions
- Domain index: id + one-line description only
- Current user message and a short memory summary

### 7.2 Loaded on demand

- Full catalog for selected domain(s)
- Join snippets for those domains
- SQL tool description and result-size limits

### 7.3 Unload rules

- After the turn completes, drop domain catalogs from the working prompt / state unless the next user message is clearly the same domain.
- If the user switches topic (“now schools near that building”), unload the previous domain and load the new one.
- Keep a compact **result summary** in conversation memory (what was asked, filters, key numbers), not raw result sets or full schema.
- Never accumulate catalogs across a long chat.

### 7.4 Implementation sketch

Catalog modules are data, not prompt text baked into one mega-system-prompt.

```
src/catalog/
  registry.py          # domain index for the query + domain routers
  domains/
    listings.py
    transactions.py
    rta.py
    schools.py
    amenities.py
    ...
  loader.py            # load(ids) / unload(ids) → prompt fragments + state
```

`loader.load(["listings", "schools"])` returns the SQL-agent system fragment. `loader.unload(...)` removes it from graph state.

---

## 8. SQL as a tool

The database is exposed as a **tool**, not as hidden retrieval.

### 8.1 Tool contract (draft)

**Name:** `run_sql` (name can change)

**Input:**

- `sql`: read-only query
- `domain_ids`: domains this query is allowed to touch
- `purpose`: one-line why this query exists (helps traces and retries)

**Output:**

- `columns`, `rows` (capped), `row_count`, `truncated`
- `error` if rejected or failed
- never the raw DB exception string to the user; that stays in traces

### 8.2 Guardrails

- Allow only `SELECT` / `WITH` (optional `EXPLAIN` in staging)
- Reject multiple statements
- Enforce a timeout and a max row cap (e.g. 100 rows to the model; more only via aggregation)
- Restrict tables to the loaded domains (plus documented join tables)
- Prefer parameterized identifiers from the catalog; do not let the model invent table names
- Log the exact SQL in Langfuse; do not print secrets or connection strings

### 8.3 Agent loop

Typical `need_db` turn:

1. Domain router selects domains and loads catalog.
2. SQL agent drafts a query from that catalog.
3. Tool executes or rejects.
4. On error or empty result: one retry with the error + catalog, then stop.
5. Answer node writes a user-facing response grounded in the rows.

The model may call the tool more than once in one turn (e.g. resolve a community id, then aggregate transactions). Keep a small hop limit.

---

## 9. Answering

- **Direct route:** short, helpful, no fake market stats.
- **DB route:** lead with the answer, then the key numbers, then caveats (date range, sale vs rent, sample size). Cite filters the SQL actually used.
- **Empty result:** say nothing matched; suggest a looser filter. Do not invent listings.
- **Partial / truncated:** say the result is a sample or an aggregate, not the full table.

Conversation memory stores intent, selected domains, and a short numeric summary — not the full SQL result grid.

---

## 10. Observability: Langfuse + logging

Tracing is part of the product, not an add-on. Every user turn is one Langfuse **trace**. Router hops, LLM calls, and SQL execution are child **observations**.

### 10.1 Why Langfuse

- Inspect *why* a turn went `direct_answer` vs `need_db`
- See which domains were loaded and which SQL ran
- Track latency, tokens, and cost per hop
- Later: scores, datasets, and prompt versions for evals

Use **Langfuse Python SDK v4** (OpenTelemetry-based) plus the LangChain `CallbackHandler` if the graph is LangGraph / LangChain. Create a handler per invocation. Wrap the HTTP/chat handler in `start_as_current_observation` so API + graph share one trace.

Config already reserved:

- `LANGFUSE_HOST` (prefer `LANGFUSE_BASE_URL` when we wire the official SDK)
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`

These are not yet set in `.env`. Add them when we instrument; do not commit secrets.

### 10.2 Trace shape (one user turn)

| Observation | Type | Capture |
| --- | --- | --- |
| `chat.turn` | span / root | user message, final answer, session id, user id |
| `router.query` | generation | route, confidence, rationale |
| `router.domain` | generation | `domain_ids`, confidence |
| `catalog.load` | span | which catalogs loaded / unloaded |
| `sql.generate` | generation | prompt catalog ids, draft SQL |
| `sql.execute` | tool / span | SQL, duration, row_count, truncated, error class |
| `answer.synthesize` | generation | grounded answer |

Attach on every trace:

- `session_id`, `user_id` (when we have auth)
- tags: `route:{direct_answer|need_db|clarify}`, `domains:{id,...}`, env
- metadata: model name, catalog version, row cap, timeout
- version: git sha or catalog version so we can compare releases

### 10.3 What we log locally vs Langfuse

| Concern | Local app logs | Langfuse |
| --- | --- | --- |
| Request id, HTTP status | yes | as metadata |
| Router decision | info log | generation + metadata |
| SQL text | debug / structured log | tool span input |
| Row samples | no (or hashed / capped) | truncated preview only |
| Connection secrets | never | never |
| Tokens / cost | optional | generations |
| User PII | redact | redact / mask |

Reuse `src/common/logger` (redaction is already there). Langfuse is the AI trace; local logs stay operational.

### 10.4 Later Langfuse use (not day one)

- Prompt management for router and SQL-agent prompts
- Datasets of golden NL → SQL → expected rows
- Scores: SQL validity, domain accuracy, groundedness
- User feedback (thumbs) attached to the turn’s `trace_id`

---

## 11. Safety and product constraints

- Read-only SQL; warehouse credentials used by the agent must not allow writes.
- Do not expose raw schema dumps, connection details, or other users’ data.
- Respect tenant / search-path settings (`DB_SEARCH_PATH`, `AUDIT_DB_SCHEMA`) so the agent only sees intended schemas.
- Numbers in answers must come from the current tool result or a clearly marked general explanation.
- Rate-limit chat and SQL separately so a looping agent cannot hammer the DB.
- Visitors and registered users never share cache keys or rate-limit buckets.
- No transactional email. Auth recovery, if added later, is not mail-based in this service.

---

## 12. How this maps onto the repo today

`src/common` and `src/config` are Propqa-owned. Marketplace / Django leftovers (email, tenants, eBay intents) are gone.

```
src/common/    identity, Redis cache, rate limits, logging, FastAPI HTTP helpers
src/config/    env / ActiveConfig (warehouse DB, Redis, LLM, Langfuse)
src/agent/     graphs, states, schemas, services, enums
src/catalog/   (empty) domain registry and loaders
src/routes/    enums, repository, schemas, services, views
src/evals/     (empty)
```

Callers:

| Kind | Identity | How it arrives |
| --- | --- | --- |
| `visitor` | durable `visitor_id` | `X-Visitor-ID` header or `propqa_visitor_id` cookie; minted if missing |
| `registered` | `user_id` | set on `request.state.user_id` by auth (not built yet) |

`UserCache` and API rate limits are keyed by `kind + subject_id`, so the two populations cannot collide.

Intended ownership:

| Package | Owns |
| --- | --- |
| `src/catalog` | Domain index, per-domain schema packs, load / unload |
| `src/agent` | Query router, domain router, SQL tool, answer node, graph state |
| `src/routes` | Chat endpoint, session, request/response |
| `src/evals` | Offline evals against Langfuse datasets / golden SQL |
| `src/common` | Caller identity, Redis cache, rate limits, logging, errors, HTTP |
| `src/config` | Env, warehouse DB, Redis, LLM, Langfuse |

---

## 13. Build order

Do this in order so we do not prompt-stuff the whole warehouse on day one.

### Phase 0 — Foundation

- [done] Strip Django / email / marketplace leftovers from `src/common`
- [done] Registered vs visitor identity, Redis cache, rate limits
- Confirm live schema: schemas, table list, grain, join keys
- Finalize domain IDs and assign every table to exactly one primary domain (tables may be *referenced* from another domain as joins)
- Wire Langfuse credentials and a hello-trace from a dummy chat turn
- Confirm read-only DB role for the agent
- Auth for registered users (how they sign in — no email from this service)

### Phase 1 — Query router + direct answers

- Implement query router (`direct_answer` / `need_db` / `clarify`)
- Direct-answer node with a small system prompt
- Trace router decisions in Langfuse
- No SQL yet

### Phase 2 — One domain end-to-end

- Pick the highest-value domain first (likely `transactions` or `listings`)
- Catalog pack + `run_sql` tool + answer synthesis
- Golden questions for that domain
- Prove load / unload for a single domain

### Phase 3 — Domain router + more packs

- Domain router over the index
- Add `schools`, `amenities`, `rta`, `locations`, then the rest
- Multi-domain turns with join-key snippets
- Unload on topic change

### Phase 4 — Hardening

- Evals in `src/evals`, Langfuse datasets and scores
- Prompt versions in Langfuse
- Tighter SQL guards, caching of repeated aggregates
- Conversation memory summaries

---

## 14. Open decisions

Resolve these in follow-up specs before they block implementation.

1. **Exact table → domain assignment** after a real schema inventory.
2. **Router implementation:** small structured-output LLM vs embeddings / rules hybrid. Default: structured LLM with a tiny domain index.
3. **Graph framework:** LangGraph (likely, given LangChain in the venv) vs a thinner custom loop.
4. **Chat API shape:** sync vs streaming; session store.
5. **Which schema(s)** the agent may query (`public`, `ai_chatbot`, `chatbot_ai`).
6. **Langfuse Cloud vs self-hosted**, and the final base URL env name.
7. **Multi-domain cap** and whether a planner node may run two SQL hops instead of one wide join.
8. **How much conversation history** the SQL agent sees (summary vs last N turns).

---

## 15. Success criteria

The design is working when:

- Simple questions never hit the database.
- Market questions never invent numbers.
- A typical SQL turn loads a handful of tables, not 100+.
- Langfuse shows, for any bad answer: route, domains, SQL, rows, and the final text.
- Adding a new subject is “new domain pack + registry entry,” not a rewrite of the system prompt.

---

## 16. Follow-up documents

Create these next, still under `.cursor/specs/`:

1. Schema inventory and domain assignment
2. Query + domain router contract (inputs, outputs, prompts)
3. Catalog pack format and load / unload API
4. SQL tool + execution guards
5. Langfuse instrumentation plan (trace names, attributes, redaction)
