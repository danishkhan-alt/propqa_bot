---
title: communities_intel
tags:
  - architecture
  - communities-intel
---

# Persona: `communities_intel`

Editorial community-page intelligence (lifestyle cards + page KPIs). There is **no** `table_router` module. Routing is two-stage: **query → domain(s)**, then **domain → table subset**. Runtime hints steer the ReAct agent; they do not shrink `SQLDatabase(include_tables=...)`.

Spatial / POI / building catalog rankings are **not** this domain — that is [`location_intel`](../Locations_Intel/location_intel.md). Live mobility is `rta_intel`. Production DLD *transaction* tables are `market_intel`. Active listings are `property_search`. Companions arrive via fan-out only — never cross-JOIN.

Canonical inventory (note: Content persona notes still mention `chatbot_communities_dubai`; **live code** uses staging page tables): [`../../Content/architecture_propqa/propqa_pipeline_system_intel_personas/Communities_Intel/communities_intel_complete.md`](../../Content/architecture_propqa/propqa_pipeline_system_intel_personas/Communities_Intel/communities_intel_complete.md)

## Diagrams

| Document | Link |
|---|---|
| Architecture | [communities-architecture.mermaid](communities-architecture.mermaid) |
| End-to-end flow | [communities-end-to-end-flow.mermaid](communities-end-to-end-flow.mermaid) |
| Routing decisions | [communities-routing-decisions.mermaid](communities-routing-decisions.mermaid) |
| Table routing | [communities-table-routing.mermaid](communities-table-routing.mermaid) |
| Module map | [communities-module-map.mermaid](communities-module-map.mermaid) |
| Hybrid fan-out | [communities-hybrid-fanout.mermaid](communities-hybrid-fanout.mermaid) |
| Enrichment dataflow | [communities-enrichment-dataflow.mermaid](communities-enrichment-dataflow.mermaid) |

Shared four-layer overview: [`../Property_Search/table-routing.mermaid`](../Property_Search/table-routing.mermaid)

## Four layers (no 1:1 table router)

```
Layer 1  Query → domain(s)   think lock + infer_intel_families + planner / Haiku
Layer 2  Hard whitelist      COMMUNITIES_INTEL_TABLES ∩ staging available → include_tables
Layer 3  Runtime hints       value-index select_tables_for_query + skill recipes, cap 3
Layer 4  SQL execution guard sql_guard + adaptive recovery + ranking hold
```

Staging engine only (`AUDIT_DB_*` / `chatbot_ai`). [`build_domain_agents`](../../Backend/agent.py) excludes `communities_intel` from production `DB_*`. Incomplete staging env → agent not registered.

## Hard whitelist

Factory: [`Backend/domain_agents.py`](../../Backend/domain_agents.py) `build_communities_intel_agent` → `_build_single_agent("communities_intel")`.

Default (`COMMUNITIES_AREA_INSIGHTS=1`):

### CORE (`COMMUNITIES_INTEL_CORE` — schema baked into the system prompt)

| Object | Role |
|---|---|
| `area_insights_communities` | Only **reflectable** table. Hub PK `id`, unique `location_id`, display `title_en`. Lifestyle / amenities / family JSONB cards. Never `WHERE display_community = true`. |

### Matviews (FQN in prompt — **not** in `include_tables`)

SQLAlchemy / LangChain cannot reflect Postgres matviews. Schema is injected by [`communities_page_schema.py`](../../Backend/communities_page_schema.py) `communities_matview_schema_block`:

| Object | Role |
|---|---|
| `public.mv_community_landing_metrics` | Active listings + all-time DLD volume + nationalities |
| `public.mv_community_dld_market_metrics` | Trailing-12m page snapshot (yield / growth / medians). Quote only when `*_data_quality = 'ok'` |

Join: `insights.id = landing.area_insights_id` **or** `lower(title_en)=lower(community_name)` (prefer name — FK often null). MV joins on `community_name`.

### Rollback (`COMMUNITIES_AREA_INSIGHTS=0` — emergency only)

CORE: `ps_communities`, `ps_subcommunities`, `ps_schools`, `ps_transport`, `ps_things_to_do`. EXTENDED: `ps_buildings`, `ps_locations_nearby`, `ps_nearby_neighbourhoods`.

**Not on this whitelist:** `chatbot_communities_dubai`, `properties`, raw `real_estate_dld_*`, `locations` / POI catalogs, RTA tables. Skill forbids JOINs outside insights + the two matviews.

## Cue → table map

[`Backend/catalog/domain_context.py`](../../Backend/catalog/domain_context.py) `select_tables_for_query` — **no regex waterfall**. Tables score by value-index phrase hits, cap `DOMAIN_CONTEXT_MAX_TABLES` (default 3). No hits → largest tables by `approx_rows` from [`Backend/data/table_profiles/communities_intel_profiles_v1.json`](../../Backend/data/table_profiles/communities_intel_profiles_v1.json). Hints do **not** shrink `include_tables`.

Skill recipes in [`COMMUNITIES_INTEL_SKILL`](../../Backend/sql_agent_skills.py) tell the model which object / columns to write SQL against:

| User cue | Target | How |
|---|---|---|
| What’s X like / overview | insights + LEFT JOIN landing + LEFT JOIN DLD MV | `title_en` exact-first; project tags / family / school+metro counts + KPIs when quality is ok |
| Schools / nurseries / universities | `area_insights_communities` | `jsonb_array_elements(schools)` LIMIT 15 |
| Who lives here / nationalities | `mv_community_landing_metrics` | `nationalities_sorted`; fallback insights.nationalities |
| Catalog metro / drive destinations | insights `metro` / `whats_within_reach` | stop catalog — **not** live RTA |
| Page yield / growth / median | `mv_community_dld_market_metrics` | quality gate `*_data_quality = 'ok'` |
| Best yield / fastest growth ranking | DLD MV | `WHERE quality='ok' ORDER BY … LIMIT 10` |
| Most listings / listings vs all-time sales | landing | `total_listings` ≠ `properties_sold` / `total_transactions_all_time` |
| Subcommunities / building URL / brunch | **Not available** | page model has no hierarchy / event catalog |
| Live metro / Salik | **not this whitelist** | `rta_intel` companion |
| Production DLD transaction yields | **not this whitelist** | `market_intel` companion |

Name match: exact-first on `title_en` / `community_name`. Page aliases: JVC → `Jumeirah Village Circle (JVC)`, JVT → `Jumeirah Village Triangle (JVT)`, JGE → Jumeirah Golf Estates, MBR City / MBRC → Mohammed Bin Rashid City, BB → Business Bay, Creek Harbour → Dubai Creek Harbour. False friends: Business Bay ≠ Marasi Business Bay; Dubai Marina ≠ Dubai Marina Mall.

Never `SELECT *` on `area_insights_communities`. Ignore `description` (always null). Redact `phone` / `telephone_1`.

## Query → domain

Regex `_try_fast_classify` is retired. Live path: Think lock → `infer_intel_families` → planner / Haiku → `route_to_agents`.

Family order: **communities** → market → offplan → location → RTA → listings.

Think lock `_THINK_COMMUNITIES_LOCK_INTENTS = {communities_intel}` keeps `skip_sql_agents=False`. Additional exclusive / salvage entry:

- `_COMMUNITIES_NEIGHBOURHOODS_NEAR_RE` (“which neighbourhoods are near…”) **suppresses** `location_intel`
- `is_community_faq_ask` + narrow `_COMMUNITIES_SALVAGE_RE` (“what’s X like”, living in, family-friendly)
- Kitchen-sink `_COMMUNITIES_INTEL_CUE_RE` is **not** used for exclusive lock (would steal developer / handover onto CI)
- `_COMMUNITIES_FAMILY_CUE_RE` adds CI in `infer_intel_families`
- Salvage refuses inventory (beds + apartment) and off-plan (handover / payment plan / brochure)

Enhance skips FilterSpec for analytical CI.

| Query shape | Domain / path |
|---|---|
| What’s Business Bay like / schools / lifestyle / who lives here | exclusive `communities_intel` |
| Which neighbourhoods are near X | exclusive `communities_intel` (LI suppressed) |
| Show 2-bed in Business Bay | `property_search` |
| Which area has the most villas / POI / lat-lng | `location_intel` |
| Nearest live metro / Salik | `rta_intel` |
| DLD transaction prices / volumes | `market_intel` |
| CI ask + developer / payment-plan / brochure | CI + `offplan_projects` via `infer_communities_companion_domains` |
| CI ask + yield / DLD volume gap | CI + `market_intel` |
| CI ask + POI-rank / lat-lng gap | CI + `location_intel` |
| CI ask + listing filters | CI + `property_search` |

## Intent aliases

Persona aliases **host on** `communities_intel`:

| Intent | Routes to |
|---|---|
| `communities_intel` | `communities_intel` only |
| `buyer_fit` | `communities_intel` + `property_search` |
| `investor_intelligence` | `market_intel` + `communities_intel` |
| `rental_intel` | `communities_intel` + `market_intel` + `property_search` |

See [`Backend/orchestration/persona/intent_domain_map.py`](../../Backend/orchestration/persona/intent_domain_map.py).

## Canonical code

| Concern | Path |
|---|---|
| Domain → table map | [`Backend/domain_agents.py`](../../Backend/domain_agents.py) `COMMUNITIES_INTEL_TABLES` / `COMMUNITIES_INTEL_CORE` / `build_communities_intel_agent` |
| Matview FQN schema | [`Backend/communities_page_schema.py`](../../Backend/communities_page_schema.py) |
| Skill recipes | [`Backend/sql_agent_skills.py`](../../Backend/sql_agent_skills.py) `COMMUNITIES_INTEL_SKILL` |
| Query → domain | [`Backend/query_classifier.py`](../../Backend/query_classifier.py) |
| Value-index hints | [`Backend/catalog/domain_context.py`](../../Backend/catalog/domain_context.py) |
| Fan-out + hint inject | [`Backend/agent.py`](../../Backend/agent.py) `GENERIC_PROFILE_DOMAINS` + staging bake |
| SQL fence | [`Backend/sql_guard.py`](../../Backend/sql_guard.py) |
| Name rewrite | [`Backend/adaptive_sql_recovery.py`](../../Backend/adaptive_sql_recovery.py) |
| Ranking hold | [`Backend/answer_completeness.py`](../../Backend/answer_completeness.py) |
| Soft enrich | [`Backend/services/community_content_resolver.py`](../../Backend/services/community_content_resolver.py), [`community_signals.py`](../../Backend/services/community_signals.py) |
