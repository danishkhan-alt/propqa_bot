---
title: market_intel
tags:
  - architecture
  - market-intel
---

# Persona: `market_intel`

DLD transaction / rental market intelligence. There is **no** `table_router` module. Routing is two-stage: **query → domain(s)**, then **domain → table subset**. Runtime hints steer the ReAct agent; they do not shrink `SQLDatabase(include_tables=...)`.

Canonical inventory: [`../../Content/architecture_propqa/propqa_pipeline_system_intel_personas/Market_Intel/market_intel_complete.md`](../../Content/architecture_propqa/propqa_pipeline_system_intel_personas/Market_Intel/market_intel_complete.md)

## Diagrams

| Document | Link |
|---|---|
| Architecture | [market-architecture.mermaid](market-architecture.mermaid) |
| End-to-end flow | [market-end-to-end-flow.mermaid](market-end-to-end-flow.mermaid) |
| Routing decisions | [market-routing-decisions.mermaid](market-routing-decisions.mermaid) |
| Table routing | [market-table-routing.mermaid](market-table-routing.mermaid) |
| Module map | [market-module-map.mermaid](market-module-map.mermaid) |
| Hybrid fan-out | [market-hybrid-fanout.mermaid](market-hybrid-fanout.mermaid) |
| Bridge dataflow | [market-bridge-dataflow.mermaid](market-bridge-dataflow.mermaid) |

## Intent aliases

| Intent | Routes to |
|---|---|
| `market_intel` | `market_intel` only |
| `valuation` | `market_intel` only |
| `investment_intel` | `market_intel` only |
| `investor_intelligence` | `market_intel` + `location_intel` |
| `rental_intel` | `location_intel` + `market_intel` + `property_search` |

Think locks `market_intel` / `valuation` so `skip_sql_agents` stays false (`_THINK_MARKET_LOCK_INTENTS`). Family cues use `_MARKET_INTEL_CUE_RE` (market / DLD / yield / trend vocabulary — **not** bare AED amounts).

## Four layers (no 1:1 table router)

```
Layer 1  Query → domain(s)   think lock + infer_intel_families + planner / Haiku
Layer 2  Hard whitelist      MARKET_INTEL_TABLES ∩ available → include_tables
Layer 3  Runtime hints       select_tables_for_query regex waterfall, cap 3
Layer 4  SQL execution guard sql_guard + area rewrite + adaptive recovery
```

Production engine only (`DB_*`). No staging RTA pool for pure market_intel.

## Hard whitelist

### CORE (`MARKET_INTEL_CORE` — schema baked into the system prompt)

| Table | Role |
|---|---|
| `real_estate_dld_transactions` | Sale and transfer records (`instance_date`, `actual_worth`) |
| `real_estate_dld_rent_contracts` | Ejari rentals (`contract_start_date`, `annual_amount`) |
| `dld_community_avg_sale_price` | Pre-aggregated community averages |
| `real_estate_dld_areas` | DLD area dimension |
| `real_estate_dld_projects` | Project registry |
| `real_estate_dld_buildings` | Building registry |
| `real_estate_dld_developers` | Developer registry |
| `price_trend_buy_fact` | Precomputed buy trends |
| `price_trend_rent_fact` | Precomputed rent trends |
| `rental_contract_summary` | Rental aggregates |
| `locations` | PropQA alias index |

### EXTENDED (name-only, still queryable)

`real_estate_dld_units`, `real_estate_dld_land_registry`.

Any identifier containing `dld` is blocked unless it is in `MARKET_INTEL_DLD_ALLOWED` (the 9 DLD registry / transaction tables). Trend facts and `locations` pass because they have no `dld` substring.

## Cue → table map

[`Backend/market_intel/dld_table_profiles.py`](../../Backend/market_intel/dld_table_profiles.py) `select_tables_for_query` is a **priority waterfall**, cap `DLD_CONTEXT_MAX_TABLES` (default 3). First match wins. Hints do **not** shrink `include_tables`.

| User cue | Selected tables |
|---|---|
| yield / ROI / gross yield | `real_estate_dld_rent_contracts` + `real_estate_dld_transactions` + `real_estate_dld_areas` |
| rent / Ejari / lease | rent_contracts + areas (+ transactions if a sale cue is also present) |
| average / community avg price (no sale cue) | `dld_community_avg_sale_price` + areas |
| developer / project registry / percent completed | projects + developers + areas |
| rent trend / rent AED | `price_trend_rent_fact` + areas |
| buy trend / AED per sqft / price trend | `price_trend_buy_fact` + areas |
| sale / sold / transaction / `intent=valuation` | transactions + areas |
| else (default bundle) | transactions + rent_contracts + areas |
| DLD stats **plus** listing cards | **not ReAct** — `dld_listings_pipeline` |
| Sold-most off-plan volume | **not ReAct** — `offplan_market_pipeline` |

Hints inject as `dld_table_context` markdown (sample columns, forbidden sale→rent columns, join edges, DLD sector aliases) via Think (`think.dld_tables`), Enhance (skip FilterSpec; blend `market_topic` + `dld_area_phrase`), classifier `_attach_dld_table_context`, and the agent user message.

Time windows: `instance_date` on sales vs `contract_start_date` when the selector picked rent_contracts only.

## Query → domain

Regex `_try_fast_classify` is retired. Live path: Think lock → `infer_intel_families` (`_MARKET_INTEL_CUE_RE` or `_DLD_AGGREGATE_RE`) → planner / Haiku → `route_to_agents`.

| Query shape | Domain / path |
|---|---|
| How many sales / avg price / YoY / yield | exclusive `market_intel` (no listing cards) |
| Worth / price band / 5-year outlook | `valuation` → `market_intel` |
| ROI / best return as investment alias | `investment_intel` → `market_intel` |
| Investor persona + area narrative | `investor_intelligence` → MI + `location_intel` |
| Rental persona | LI + MI + `property_search` |
| Named off-plan project trends / brochure | `offplan_projects` (not market_intel) |
| Sold-most off-plan | `offplan_market_bridge` |
| DLD stats plus listing cards | `dld_bridge` |
| Listing count + market volume | `property_search` + `market_intel` |
| Bare AED / beds inventory | `property_search` (not market_intel) |
