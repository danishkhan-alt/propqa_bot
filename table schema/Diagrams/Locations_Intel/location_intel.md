---
title: location_intel
tags:
  - architecture
  - location-intel
---

# Persona: `location_intel`

Spatial / POI / building / catalog-ranking intelligence. There is **no** `table_router` module. Routing is two-stage: **query → domain(s)**, then **domain → table subset**. Runtime hints steer the ReAct agent; they do not shrink `SQLDatabase(include_tables=...)`.

Editorial lifestyle (“what’s Business Bay like”, schools, commute narrative) is **not** this domain — that is [`communities_intel`](../../Content/architecture_propqa/propqa_pipeline_system_intel_personas/Communities_Intel/communities_intel.md). Persona aliases host on CI, not LI.

Canonical inventory: [`../../Content/architecture_propqa/propqa_pipeline_system_intel_personas/Locations_Intel/location_intel_complete.md`](../../Content/architecture_propqa/propqa_pipeline_system_intel_personas/Locations_Intel/location_intel_complete.md)

## Diagrams

| Document | Link |
|---|---|
| Architecture | [location-architecture.mermaid](location-architecture.mermaid) |
| End-to-end flow | [location-end-to-end-flow.mermaid](location-end-to-end-flow.mermaid) |
| Routing decisions | [location-routing-decisions.mermaid](location-routing-decisions.mermaid) |
| Table routing | [location-table-routing.mermaid](location-table-routing.mermaid) |
| Module map | [location-module-map.mermaid](location-module-map.mermaid) |
| Hybrid fan-out | [location-hybrid-fanout.mermaid](location-hybrid-fanout.mermaid) |
| Enrichment dataflow | [location-enrichment-dataflow.mermaid](location-enrichment-dataflow.mermaid) |

Shared four-layer overview: [`../Property_Search/table-routing.mermaid`](../Property_Search/table-routing.mermaid)

## Four layers (no 1:1 table router)

```
Layer 1  Query → domain(s)   think lock + infer_intel_families + planner / Haiku
Layer 2  Hard whitelist      LOCATION_INTEL_TABLES ∩ available → include_tables
Layer 3  Runtime hints       value-index select_tables_for_query, cap 3
Layer 4  SQL execution guard sql_guard + ranking completeness hold
```

Production engine only (`DB_*`). No staging RTA / communities pool for pure `location_intel`.

## Hard whitelist

Factory: [`Backend/domain_agents.py`](../../Backend/domain_agents.py) `_build_single_agent("location_intel")`.

### CORE (`LOCATION_INTEL_CORE` — schema baked into the system prompt)

| Table | Role |
|---|---|
| `locations` | Master area hierarchy; `parent_id` self-join; `aliases_en` jsonb |
| `buildings` | Dedicated building dimension (`morphable_type` / `morphable_id`) |
| `nlp_search_locations` | NLP geocoding index |
| `nlp_search_pois` | POI catalog (schools, malls, hospitals — spatial only) |
| `nlp_search_roads` | Road / highway layer |
| `nearby_locations` | Named anchors (e.g. “Metro Station”) |
| `nearby_location_property` | M2M bridge to listings (listings SQL lives on `property_search`) |
| `pf_locations` | Property Finder spelling / path dimension |
| `places` | Generic place lat/lng records |

### EXTENDED (name-only, still queryable)

`countries`, `spatial_ref_sys`, `geometry_columns`, `geography_columns`, `nlp_search_location_sources`, `bayut_locations`.

**Not on this whitelist:** `chatbot_communities_dubai` / `area_insights_communities` / `ps_*` (`communities_intel`), `properties` (listings), any `dld*` table. Skill forbids `JOIN locations.area_id → real_estate_dld_areas`.

## Cue → table map

[`Backend/catalog/domain_context.py`](../../Backend/catalog/domain_context.py) `select_tables_for_query` — **no regex waterfall**. Tables score by value-index phrase hits, cap `DOMAIN_CONTEXT_MAX_TABLES` (default 3). No hits → largest tables by `approx_rows` from [`Backend/data/table_profiles/location_intel_profiles_v1.json`](../../Backend/data/table_profiles/location_intel_profiles_v1.json). Hints do **not** shrink `include_tables`.

Skill recipes in [`LOCATION_INTEL_SKILL`](../../Backend/sql_agent_skills.py) tell the model which table to write SQL against:

| User cue | Target | How |
|---|---|---|
| Area / alias / hierarchy (JVC) | `locations` | `name_en` ILIKE or `aliases_en::jsonb ?\|` |
| Buildings in an area | `buildings` (or `locations` where `type='building'`) | `morphable_type` / `morphable_id` to parent Location |
| Nearby school / mall / hospital POI (catalog, not lifestyle) | `nlp_search_pois` | `category` / `subcategory` ILIKE; optional area_id |
| Roads / highways | `nlp_search_roads` | `road_type`, `line_geom` |
| Geocoding / NLP area match | `nlp_search_locations` | aliases + geom |
| Named anchor (“Metro Station”) | `nearby_locations` + `nearby_location_property` | M2M; listing join stays on `property_search` |
| PF / Bayut spelling | `pf_locations` / `bayut_locations` | soft `location_id` or title match |
| Generic place lat/lng | `places` | `name_en`, `type` |
| Country | `countries` | rare |
| Explicit SRID / geom meta | PostGIS metadata tables | only if asked |
| Catalog ranking (“most villas”) | aggregate `locations` / `buildings` | never invent from POI lat/lng |
| Lifestyle / schools narrative | **not this whitelist** | `communities_intel` |

Time windows: `created_at` only when the ask is clearly temporal (catalog freshness). Most LI data is static.

## Query → domain

Regex `_try_fast_classify` is retired. Live path: Think lock → `infer_intel_families` (`_LOCATION_INTEL_CUE_RE`) → planner / Haiku → `route_to_agents`.

`_LOCATION_INTEL_CUE_RE`: `location`, `poi`, `building(s)`, `nearby`, `proximity`, `spatial`, `lat/lng/coordinates`.

`_COMMUNITIES_NEIGHBOURHOODS_NEAR_RE` (“which neighbourhoods are near…”) **suppresses** LI — Haiku often mislabels those as location; they stay on `communities_intel`.

Family order: CI → market → offplan → **location** → RTA → listings.

Think lock `_THINK_LOCATION_LOCK_INTENTS = {location_intel}` keeps `skip_sql_agents=False`. Perception `think.intent == location_intel` returns exclusive `("location_intel",)`. Enhance skips FilterSpec for analytical LI.

| Query shape | Domain / path |
|---|---|
| Which area has the most villas / POI / lat-lng / buildings | exclusive `location_intel` |
| What’s Business Bay like / schools / lifestyle | `communities_intel` only |
| Show 2-bed in Business Bay | `property_search` |
| Nearest metro to Marina | `rta_intel` |
| CI ask + POI-rank / lat-lng gap | CI + `location_intel` via `infer_communities_companion_domains` |
| Mobility hybrid + location cue | `rta_intel` + LI companion |

## Intent aliases

Persona aliases **do not** host on `location_intel`:

| Intent | Routes to |
|---|---|
| `location_intel` | `location_intel` only |
| `buyer_fit` | `communities_intel` + `property_search` |
| `investor_intelligence` | `market_intel` + `communities_intel` |
| `rental_intel` | `communities_intel` + `market_intel` + `property_search` |

See [`Backend/orchestration/persona/intent_domain_map.py`](../../Backend/orchestration/persona/intent_domain_map.py).

## Canonical code

| Concern | Path |
|---|---|
| Domain → table map | [`Backend/domain_agents.py`](../../Backend/domain_agents.py) `LOCATION_INTEL_TABLES` / `LOCATION_INTEL_CORE` |
| Skill recipes | [`Backend/sql_agent_skills.py`](../../Backend/sql_agent_skills.py) `LOCATION_INTEL_SKILL` |
| Query → domain | [`Backend/query_classifier.py`](../../Backend/query_classifier.py) |
| Value-index hints | [`Backend/catalog/domain_context.py`](../../Backend/catalog/domain_context.py) |
| Fan-out + hint inject | [`Backend/agent.py`](../../Backend/agent.py) `GENERIC_PROFILE_DOMAINS` |
| SQL fence | [`Backend/sql_guard.py`](../../Backend/sql_guard.py) |
| Ranking hold | [`Backend/answer_completeness.py`](../../Backend/answer_completeness.py) |
