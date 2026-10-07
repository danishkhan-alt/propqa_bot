---
title: offplan_projects
tags:
  - architecture
  - offplan-projects
---

# Persona: `offplan_projects`

Off-plan catalog intelligence. There is **no** `off-plan_intel` module and **no** `table_router`. Routing is two-stage: **query → domain(s)**, then **domain → table subset**. Runtime hints steer the ReAct agent; they do not shrink `SQLDatabase(include_tables=...)`.

Canonical inventory: [`../../Content/architecture_propqa/propqa_pipeline_system_intel_personas/OffPlan_Intel/offplan_projects_complete.md`](../../Content/architecture_propqa/propqa_pipeline_system_intel_personas/OffPlan_Intel/offplan_projects_complete.md)

## Diagrams

| Document | Link |
|---|---|
| Architecture | [offplan-architecture.mermaid](offplan-architecture.mermaid) |
| End-to-end flow | [offplan-end-to-end-flow.mermaid](offplan-end-to-end-flow.mermaid) |
| Routing decisions | [offplan-routing-decisions.mermaid](offplan-routing-decisions.mermaid) |
| Table routing | [offplan-table-routing.mermaid](offplan-table-routing.mermaid) |
| Module map | [offplan-module-map.mermaid](offplan-module-map.mermaid) |
| Hybrid fan-out | [offplan-hybrid-fanout.mermaid](offplan-hybrid-fanout.mermaid) |
| Bridge dataflow | [offplan-bridge-dataflow.mermaid](offplan-bridge-dataflow.mermaid) |

## Three worlds (no LLM cross-JOIN)

| World | Label | Engine | Tables |
|---|---|---|---|
| Catalog | `offplan_projects` ReAct | Prod `DB_*` | `offplan_projects`, `offplan_files`, `locations` |
| DLD sales | `offplan_market_bridge` | Prod `DB_*` | `real_estate_dld_transactions` + DLD project/developer dims, then fuzzy `offplan_projects` |
| Listings | `property_search` | Prod `DB_*` | `properties` where `completion_status='off_plan'` |

Geo station lookup is the only AUDIT use: `offplan_geo_bridge` resolves metro/bus on `AUDIT_DB_*`, then ranks prod `offplan_projects` by haversine.

## Cue → table map

| User cue | Target | How |
|---|---|---|
| Project / developer / price / payment / handover | `offplan_projects` | denormalised columns; ILIKE on `location` / `developer_name_en` / `project_name_en` |
| Brochure / PDF / floor plan / media | `offplan_files` JOIN `offplan_projects` | `fileable_type='OffplanProject'` AND `fileable_id = offplan_projects.id` |
| Community-level area follow-up | `locations` alias `lo` | `name_en` + `aliases_en::jsonb`; default is still ILIKE on `offplan_projects.location` |
| Sold most / sales volume | **not ReAct** | `offplan_market_pipeline` → DLD then fuzzy catalog |
| Near named metro/bus | **not ReAct** | AUDIT station + prod `offplan_projects` haversine |
| Unit beds / listing price | **not this whitelist** | `property_search` / `properties` |

## Query → domain

Regex `_try_fast_classify` is retired. Live path: Think lock → `infer_intel_families` (`_OFFPLAN_INTEL_CUE_RE`) → planner / Haiku → last-line `strip_offplan_catalog_on_listing_inventory` unless `_OFFPLAN_CATALOG_CUE_RE`.

| Query shape | Domain / path |
|---|---|
| Brochure / payment / handover / named project | exclusive `offplan_projects` |
| Sold most / sales volume off-plan | `offplan_market_bridge` then optional catalog `depends_on` |
| Near named metro/bus | `rta_intel` tool `offplan_geo` + often `multi_intel_hybrid` |
| Is X ready / why off-plan | `readiness` via `rta_intel` |
| Beds / AED / units + project | `offplan_projects` + `property_search` |
| Recommend after prior station | `recommend_hybrid` |
