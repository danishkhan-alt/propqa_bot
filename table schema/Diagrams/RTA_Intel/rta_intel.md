---
title: rta_intel
tags:
  - architecture
  - rta-intel
---

# Persona: `rta_intel`

Dubai RTA mobility / amenity intelligence. There is **no** `table_router` module. Routing is two-stage: **query → domain(s)**, then **domain → table subset**. Runtime hints steer the ReAct agent; they do not shrink `SQLDatabase(include_tables=...)`. Five mobility bridges hit **named tables** with deterministic SQL.

Gated by `RTA_INTEL_ENABLED=1` plus valid `AUDIT_DB_*`. Production `build_domain_agents(exclude_domains={"rta_intel"})` so the prod pool never sees RTA GIS tables.

Canonical inventory: [`../../Content/architecture_propqa/propqa_pipeline_system_intel_personas/RTA/rta_intel_complete.md`](../../Content/architecture_propqa/propqa_pipeline_system_intel_personas/RTA/rta_intel_complete.md)

## Diagrams

| Document | Link |
|---|---|
| Architecture | [rta-architecture.mermaid](rta-architecture.mermaid) |
| End-to-end flow | [rta-end-to-end-flow.mermaid](rta-end-to-end-flow.mermaid) |
| Routing decisions | [rta-routing-decisions.mermaid](rta-routing-decisions.mermaid) |
| Table routing | [rta-table-routing.mermaid](rta-table-routing.mermaid) |
| Module map | [rta-module-map.mermaid](rta-module-map.mermaid) |
| Hybrid fan-out | [rta-hybrid-fanout.mermaid](rta-hybrid-fanout.mermaid) |
| Bridge dataflow | [rta-bridge-dataflow.mermaid](rta-bridge-dataflow.mermaid) |

Shared four-layer overview: [`../Property_Search/table-routing.mermaid`](../Property_Search/table-routing.mermaid)

Schema ERDs (data model, not pipeline): [`../../Content/data_dubai_dld/rta_amenity/version3/`](../../Content/data_dubai_dld/rta_amenity/version3/)

## Four layers (no 1:1 table router)

```
Layer 1  Query → domain(s)   think lock + infer_intel_families + mobility LLM
Layer 2  Hard whitelist      RTA_INTEL_TABLES ∩ available on AUDIT_DB → include_tables
Layer 3  Runtime hints       value-index select_tables_for_query, cap 3
Layer 4  Execution           5 bridge tools (fixed SQL) OR ReAct sql_db_query + sql_guard
```

Staging engine (`AUDIT_DB_*` / schema `chatbot_ai`) for ReAct and most bridge GIS. Production `DB_*` only for building coords, off-plan geo rank, and readiness.

## Hard whitelist

Factory: [`Backend/domain_agents.py`](../../Backend/domain_agents.py) `build_rta_intel_agent()` → `_build_single_agent("rta_intel")` on the staging engine.

### CORE (`RTA_INTEL_CORE` — schema baked into the system prompt)

| Table | Role |
|---|---|
| `metro_lines` | Metro line catalogue (`line_name`) |
| `metro_stations` | Station names, zone, lat/lon — preferred proximity source |
| `tram_lines` | Tram line catalogue |
| `tram_stations` | Tram stop names / coords |
| `tram_stations_gis` | Tram GIS companion |
| `bus_stops_gis` | 6-digit `bus_stop_id`, `stops_name_en`, lat/lon, `routes` CSV |
| `bus_routes` | Route metadata (`stop_name` often empty) |
| `public_transportation_routes_stops` | Bus route stop sequence; join on 6-digit `stop_id` |
| `marine_stations` | Marine station catalogue |
| `marine_stations_gis` | Marine GIS; join on `station_id` |
| `marine_lines` | Marine route catalogue |
| `nol_machines` | NOL top-up machines |
| `rta_customer_service_centers` | RTA service centres |
| `taxi_stand_locations` | Taxi stand points |
| `salik_tolling_gates_location` | Salik gate locations |
| `salik_tariff` | Salik tariff bands |
| `rail_parking` | Park-and-ride near rail |
| `metro_passengers_trips_by_station_monthly` | Monthly metro tap rollup |
| `tram_passengers_trips_by_station_monthly` | Monthly tram tap rollup |
| `bus_passengers_trips_by_route_monthly` | Monthly bus tap rollup |
| `marine_passengers_trips_by_station_monthly` | Monthly marine tap rollup |
| `bus_network_coverage` | Community seam (`community_num`) to parking |
| `number_of_parking_spaces_per_zone` | Parking supply by community |
| `parking_rates` | Tariff bands (`zone` = A/B/D — **not** area codes) |

### EXTENDED (name-only, still queryable)

`metro_ridership`, `tram_ridership`, `bus_ridership`, `marine_ridership`, `average_bus_speed_per_line`, `bus_stop_details`, `taxi_dubai_fleet`, `franchise_taxi_fleet`, `taxis_and_number_of_trips_by_carrier_company_month`, `major_roads`, `bicycle_tracks`, `total_road_length_by_functional_classification_km`, `marine_fleet_by_all_types_monthly`, `dubai_metro_and_tram_capacity`, `school_buses`.

### Explicitly excluded

- `public_transportation_stations` (empty hub)
- `public_transport_trips_by_type_of_transport_month` (corrupt `transport_type`)
- KML / GTFS blobs (`rta_gtfs`, `metro_stations_gis`, `kml_content`, `file_data`)

**Not on this whitelist:** `properties` (listings), any `dld*` table, `chatbot_communities_dubai`, `offplan_projects` (those are companion / bridge-prod tables, not ReAct `include_tables`).

## Cue → table map

Two mechanisms. Bridges **do** target named tables. Generic ReAct hints **do not** shrink `include_tables`.

### A. Mobility bridges (deterministic SQL)

[`Backend/rta_bridge_tools.py`](../../Backend/rta_bridge_tools.py) `dispatch_mobility_bridge` injects ground truth + `required_tool_hint` before ReAct. All routes map to domain `rta_intel` via `route_rta_intel_domain()`.

| User cue | Route / tool | Tables / DB |
|---|---|---|
| Nearest metro to Dubai Marina / JLT / Marina Mall | `marina_metro_corridor` / `marina_metro_corridor_bridge` | AUDIT `metro_stations`, `tram_stations`, `metro_passengers_trips_by_station_monthly` |
| Nearest metro to a named tower | `building_metro_proximity` / `building_metro_proximity_bridge` | PROD `locations` coords + AUDIT `metro_stations` haversine |
| Bus from A to B | `bus_corridor` / `bus_corridor_bridge` | AUDIT `bus_stops_gis` + `public_transportation_routes_stops` |
| Off-plan near a named station | `offplan_geo` / `offplan_geo_bridge` | AUDIT station anchor + PROD `offplan_projects` |
| Is project X ready? | `readiness` / `readiness_bridge` | PROD `offplan_projects` + `properties.completion_status` |

Legacy `*_pipeline` graph nodes exist in [`Backend/agent.py`](../../Backend/agent.py) but production `route_to_agents` never Sends them.

### B. Generic ReAct (`rta_intel_generic`)

[`Backend/catalog/domain_context.py`](../../Backend/catalog/domain_context.py) `select_tables_for_query` — **no regex waterfall**. Tables score by value-index phrase hits, cap `DOMAIN_CONTEXT_MAX_TABLES` (default 3). No hits → largest tables by `approx_rows` from [`Backend/data/table_profiles/rta_intel_profiles_v1.json`](../../Backend/data/table_profiles/rta_intel_profiles_v1.json). Example: “Red Line” picks metro tables because that value lives there.

Skill recipes in [`RTA_INTEL_SKILL`](../../Backend/sql_agent_skills.py) (§4–§6) tell the model which table to write SQL against:

| User cue | Target | How |
|---|---|---|
| Red Line / station list | `metro_stations` | `location_name_english` or `line_name` ILIKE — no line-OR on proximity |
| Nearest metro to Marina / JLT | `metro_stations` §6b | Corridor recipe; Sobha Realty (DB DAMAC) + DMCC co-primary |
| Tram stops / tram trips | `tram_stations` / `tram_stations_gis` / monthly tram | GIS join when coords needed |
| Bus routes at a named stop | `bus_stops_gis` JOIN `public_transportation_routes_stops` | 6-digit `stop_id`; never `bus_stop_details` (4-digit) |
| Monthly ridership | `*_passengers_trips_*_monthly` | UNION per mode; never narrate raw `*_ridership` as OD |
| Parking spaces in a community | `bus_network_coverage` JOIN `number_of_parking_spaces_per_zone` | `community_num` |
| Parking tariff bands | `parking_rates` | Do **not** join `zone` to area codes |
| NOL / Salik / taxi | `nol_machines` / `salik_tolling_gates_location` + `salik_tariff` / `taxi_stand_locations` | ILIKE or SQL-anchored proximity |
| Marine | `marine_stations` JOIN `marine_stations_gis` | `station_id` |
| Lifestyle / schools | **not this whitelist** | `communities_intel` / `location_intel` |
| 2-bed rent near metro | **not this whitelist** | `property_search` only — strip RTA |

Time windows: monthly tables filter `(year, month-name)` pairs via [`Backend/time_windows/recipes.py`](../../Backend/time_windows/recipes.py) — not a single date column.

Rename aliases in user-facing answers: DAMAC Properties → **Sobha Realty**; Nakheel → **Al Fardan Exchange**.

## Query → domain

Regex `_try_fast_classify` is retired. Live path: Think lock → `infer_intel_families` (`_COMMUNITIES_GAP_RTA_RE`) → `mobility_intent_llm` → planner / Haiku → `route_to_agents`.

`_COMMUNITIES_GAP_RTA_RE`: `metro`, `tram`, `bus(es)`, `salik`, `nol`, `rta`, `public transport`, `station near`.

Think lock `_THINK_RTA_LOCK_INTENTS = {rta_intel}` keeps `skip_sql_agents=False` when the flag is on. Listing inventory (`query_has_listing_signal_regex`) **strips** `rta_intel`. Family order: CI → market → offplan → location → **RTA** → listings.

Enhance: `route_after_enhance` RTA / mobility fast-path → `propqa_core`; FilterSpec suppress for `rta_intel` (readiness must not inject `completion_status`).

| Query shape | Domain / path |
|---|---|
| Nearest metro to Dubai Marina / JLT | exclusive `rta_intel` → `marina_metro_corridor` |
| Metro closer to Continental Tower | exclusive `rta_intel` → `building_metro_proximity` |
| Which bus from Silicon Oasis to Marina | exclusive `rta_intel` → `bus_corridor` |
| Off-plan closer to Business Bay metro | `multi_intel_hybrid` — `rta_intel` (`offplan_geo`) + companions |
| Is Peninsula Two ready? | exclusive `rta_intel` → `readiness` |
| Monthly trips / Salik / NOL / Red Line catalogue | exclusive `rta_intel` → `rta_intel_generic` |
| Recommend 2BHK after station context | `recommend_hybrid` — offplan + rta + `property_search` |
| 2-bed rent near metro in JLT under 100k | `property_search` only — **strip** `rta_intel` |
| What’s Marina like / schools / lifestyle | `communities_intel` / `location_intel` (route `none`) |
| Avg sale price Business Bay | `market_intel` |

## Intent aliases

`rta_intel` is a first-class domain + intent. No persona alias hosts on it.

| Intent | Routes to |
|---|---|
| `rta_intel` | `rta_intel` only (unless hybrid companions fire) |

See [`Backend/orchestration/persona/intent_domain_map.py`](../../Backend/orchestration/persona/intent_domain_map.py) and [`Backend/mobility_intent_llm.py`](../../Backend/mobility_intent_llm.py) `route_rta_intel_domain()`.

## Canonical code

| Concern | Path |
|---|---|
| Domain → table map | [`Backend/domain_agents.py`](../../Backend/domain_agents.py) `RTA_INTEL_TABLES` / `RTA_INTEL_CORE` / `build_rta_intel_agent` |
| Skill recipes | [`Backend/sql_agent_skills.py`](../../Backend/sql_agent_skills.py) `RTA_INTEL_SKILL` |
| Query → domain | [`Backend/query_classifier.py`](../../Backend/query_classifier.py) |
| Mobility routes + slots | [`Backend/mobility_intent_llm.py`](../../Backend/mobility_intent_llm.py) |
| Bridge tools + preflight | [`Backend/rta_bridge_tools.py`](../../Backend/rta_bridge_tools.py) |
| Value-index hints | [`Backend/catalog/domain_context.py`](../../Backend/catalog/domain_context.py) |
| Fan-out + hint inject | [`Backend/agent.py`](../../Backend/agent.py) `GENERIC_PROFILE_DOMAINS`, `_rta_mobility_send` |
| Feature flag | [`Backend/ops/feature_flags.py`](../../Backend/ops/feature_flags.py) `rta_intel_enabled` |
| SQL fence | [`Backend/sql_guard.py`](../../Backend/sql_guard.py) |
| Routing contracts | [`Backend/tests/test_rta_intel_routing.py`](../../Backend/tests/test_rta_intel_routing.py) |
