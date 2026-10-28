# PropQA Bot: Improvement Plan

**Evals, a feedback loop, answer grounding and GEPA self-improvement · October 2026**

# 1. Summary

The bot works well. Routing, name grounding, guarded text-to-SQL and structured replies are all in place. What it lacks is a dependable way to know whether a change makes it better or worse. Today prompt quality depends on someone noticing a bad answer and adding another rule by hand.

This plan makes **four changes**, in this order. Each one depends on the one before it.

| # | Change | Why it matters | Size |
| --- | --- | --- | --- |
| 1 | **One eval system** with a frozen holdout set and a merge gate | Every later change is measured against it. Without it GEPA has nothing to optimise. | ~2 weeks |
| 2 | **Close the feedback loop**: store the thumbs the UI already sends | Real failures become eval cases instead of being lost | ~2 days |
| 3 | **Answer grounding check**: every number in a reply must come from the data | The product promises figures you can trust. This measures and protects that. | ~4 days |
| 4 | **GEPA prompt optimisation** for the query router, then the SQL drafter | Replaces hand-patching prompts with measured, reviewable improvements | ~2 weeks |

**Figure 1.** *Where each change plugs into the current chat pipeline.*

Out of scope on purpose: new data domains, a new UI, a model or framework migration, and any automatic self-modification in production (section 7).

# 2. Where the bot stands today

These findings come from the current code.

| Area | What exists | Gap |
| --- | --- | --- |
| Evals | `sql_golden.yaml` (20 cases, truth written as SQL, scored on the live warehouse), `domain_router_golden.yaml` (39), `router_golden.yaml` (10, mocked tests only) | Small sets, no train/holdout split, no score history, nothing gates a change. Reply quality is not measured. |
| Real queries | `testquries.md`: ~170 real user queries by domain, typos kept | Not yet turned into eval cases |
| Prompts | Hand-written rule lists in `src/agent/prompts/` (router, SQL drafter, structured reply) | 31 of the repo's 78 commits touch the prompts. Rules grow one failure at a time and repeat across prompts. Nothing shows whether a new rule broke an old case. |
| Feedback | Thumbs up/down in `MessageList.tsx`, posted to `/api/feedback/thumbs` | **No backend route exists.** Every vote is dropped. |
| Tracing | Langfuse spans for routing, SQL attempts and replies | No prompt version on traces, so two prompt versions cannot be compared |
| Fallbacks | Router, SQL and reply fallbacks keep a turn alive | Nobody counts how often they fire |
| Reply numbers | `figures` values are copied from rows by code, which is safe | `intro_text` is free model text and can state a price or count that is not in the rows. Nothing checks it. |

The design is sound. The weak point is measurement, so measurement comes first.

# 3. Change 1: One eval system

## 3.1 What we measure

| Score | Question it answers | How it is scored |
| --- | --- | --- |
| Route accuracy | Right route (`need_db`, `direct_answer`, `out_of_scope`) and turn kind? | Exact match against labels |
| Domain accuracy | Right domains, joins and recipe? | Existing `score_route` in `run_domain_eval.py` |
| **Result correctness** | Right listings or the right figure? | Existing scorers in `run_sql_eval.py`: listing ids vs. truth SQL, value within tolerance |
| Answer grounding | Is every number in the reply backed by the data? | Deterministic check (Change 3) |
| Usefulness (judge) | Does it answer what was asked and state relaxed filters? | LLM judge, 3 yes/no questions, calibrated first |

Result correctness matters most. A polite reply that shows listings from the wrong area is a failure. A plain reply with the right figure is a pass. Latency, fallback rate and cost per turn are reported alongside the scores but never block a change on their own.

## 3.2 The dataset

Keep the current convention: **truth is written as SQL and run against the live warehouse at eval time**. The data changes daily, so a stored expected number would go stale. A stored query does not. Grow the sets from real queries, not invented ones:

| Set | Today | Target | Source |
| --- | --- | --- | --- |
| Router cases | 10 | 150 | All ~170 queries in `testquries.md`, one label per line |
| Domain cases | 39 | 100 | The `need_db` subset of those |
| Lookup cases (SQL truth) | 20 | 120 | ~12 per domain: typos, multi-place, OR-amenities, budgets, empty results |
| Multi-turn cases | 1 | 20 | Refine, "cheaper", pronoun follow-ups, focused listings |

**Figure 2.** *How cases are built, split once, scored and used to gate a merge.*

Every case carries tags (domain, kind, hard), so a regression shows where it happened. The split is stored in each case and frozen. **Holdout** cases are never shown to GEPA or used to write a prompt rule, and they are the only set that can block a release. About 15 **must_pass** cases, such as "show me properties in Dubai Marina", "what is RERA" or the out-of-scope code request, block on any failure.

## 3.3 A reason for every failure

Every scorer returns a score **and a sentence explaining it**. The existing detail strings are a start. They should be specific enough for a person, or GEPA, to act on:

> *FAIL marina_two_bed: 3 of 10 listings are outside Dubai Marina. The SQL filtered `address_en ILIKE '%marina%'` instead of the stored value `Dubai Marina`. The 2-bedroom filter is missing.*

This one decision is what makes Change 4 work. GEPA learns from this text, not only from the score.

## 3.4 A narrow LLM judge

Use a judge only where code cannot score. Ask it three yes/no questions instead of a 1 to 10 rating:

- Does the reply answer the question the user asked?
- When a filter was relaxed or `search_notes` exist, does the reply say so?
- Does it claim anything about a listing, area or developer that the rows do not support?

Two people label 50 replies first. Trust the judge only if it agrees with them on at least 85% of answers for each question.

## 3.5 How it runs

- **One entry point**: `python -m evals.run_all [--split holdout]` wraps the existing runners, writes a JSON report and records a Langfuse dataset run, so runs can be compared over time.
- **Every PR**: the existing mocked tests plus the grounding checker unit tests (no network).
- **PRs touching prompts, catalog, SQL or grounding**: a full eval run. The PR is blocked on any must_pass failure or if holdout result correctness drops by more than 2 points.
- **Nightly** on main, so warehouse data changes and model drift show up within a day.

## 3.6 Weekly triage

Each week, take 30 to 50 production traces: thumbs-down first, then turns where a fallback fired or the lookup came back empty. Each real failure becomes one case with SQL truth in train or val. This keeps the eval set close to what users actually ask.

# 4. Change 2: Close the feedback loop

The UI already collects the signal. The backend drops it.

- Add `POST /api/feedback/thumbs` (`src/routes/feedback.py`) for the body `analyticsApi.submitFeedback` already sends. Use the same auth and rate limits as chat.
- Store the vote on the turn record `useChat.ts` reads back (`thumbs_up` / `thumbs_down`), so it survives a reload.
- Send it to Langfuse as a `user_feedback` score on that turn's trace. Store the trace id with the turn if it is not stored already.
- Tag every trace with `prompt_version` (a short hash of each prompt), `route`, `domain_ids` and `fallback_fired`. Thumbs-up rate can then be split by prompt version, which GEPA rollout needs.

# 5. Change 3: Answer grounding check

For a property buyer, one wrong price or count does more damage than anything else. Figures are already safe because code copies them from rows. The free text in `intro_text` and cards is not checked. The check (`src/agent/reply/grounding_check.py`) is plain Python with no LLM:

- Extract every number from the reply: prices (AED 1.2M), counts, sizes, percentages, years.
- Normalise it the way `reply/figures.py` formats values, so AED 1.2M matches 1,195,000 within display rounding.
- Accept it if it matches rows, listings, `listing_count`, the user's own filters, coverage dates or the Golden Visa facts, or a simple derived value (a column's min, max or the row count). Flag anything left over.

**Figure 3.** *The check matches each number in the reply to the data. Here "228" has no source, so it is flagged.*

**In evals** it is the answer grounding score. **In production**, phase 1, it runs after the reply and records a Langfuse score without changing the reply, because `intro_text` streams to the user as it is written. Only if the flagged rate is above about 2% of data-backed turns do we add phase 2: a UI event that replaces a flagged reply.

# 6. Change 4: GEPA for self-improvement

## 6.1 What GEPA is and why it fits

GEPA (Genetic-Pareto reflective prompt evolution; Agrawal et al., 2025) improves prompts using the system's own failures. Each round it runs the current prompt on a small batch, reads the scores **and the written failure reasons**, and asks a strong reflection model to rewrite the prompt. A rewrite is kept only if it does better. It keeps a **Pareto front**: every prompt that is best on at least one validation case survives, so later rounds can combine fixes instead of collapsing onto one average prompt.

**Figure 4.** *One GEPA round, and the Pareto front it keeps on the validation set.*

It needs hundreds of evaluations, not the thousands RL-style tuning needs, and its output is plain prompt text a person can review. That fits this repo: the prompts are plain strings, the eval failures are written in words (3.3), and the current process, reading a failure and adding a rule, is exactly what GEPA automates, across the whole training set instead of one bug at a time.

## 6.2 What we optimise, in order

| Stage | Prompt | Metric | Why this order |
| --- | --- | --- | --- |
| A | `QUERY_ROUTER_SYSTEM` | Route + turn-kind accuracy; names, limits and filters match labels | Cheap (one fast-model call, no warehouse), 150 labels, errors here spread to every later step |
| B | `SQL_DRAFT_SYSTEM` | Result correctness; guard rejections and retry reasons as feedback | Most wrong answers start here. The metric already exists and runs the SQL. |
| C (later) | `STRUCTURED_REPLY_SYSTEM` | Answer grounding + judge | Only after A and B ship and the judge is calibrated |

The domain router is left out. It has its own eval and can run on Jev, where we do not own the prompt.

## 6.3 Implementation

- Use the standalone `gepa` package with a custom adapter. **No DSPy rewrite**: the adapter calls the same `LangChainAgentModels` methods production uses.
- `LangChainAgentModels.__init__` gains an optional `prompts` override. Production passes nothing, so behaviour does not change.
- Fixed blocks (`IN_SCOPE_SUBJECTS`, `GOLDEN_VISA_FACTS`, `NO_INFERENCE_FROM_NAMES`) stay outside the optimisable text, so GEPA cannot edit away a compliance rule.

```python
# src/evals/gepa/optimize_router.py  (sketch: pin gepa and check its adapter API first)

class RouterAdapter:

    def evaluate(self, batch, candidate, capture_traces=False):
        models = LangChainAgentModels(prompts={"query_router": candidate["query_router"]})
        results = [score_route_case(c, models.route_query(**c.inputs)) for c in batch]
        return EvaluationBatch(outputs=[r.route for r in results],
                               scores=[r.score for r in results],
                               trajectories=[r.trace for r in results] if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        return {"query_router": [{"Inputs": t["message"], "Generated Outputs": t["output"],
                                  "Feedback": t["feedback"]} for t in eval_batch.trajectories]}

result = gepa.optimize(seed_candidate={"query_router": OPTIMISABLE_ROUTER_TEXT},
                       trainset=train, valset=val, adapter=RouterAdapter(),
                       reflection_lm=GEPA_REFLECTION_MODEL, max_metric_calls=1500)
```

- **Task model**: exactly the production model for that step. **Reflection model**: the strongest available, set by `GEPA_REFLECTION_MODEL`.
- **Budget**: about 10 passes over train+val. Estimate cost first (cases × passes × tokens). Stage B runs SQL, so keep `SQL_TIMEOUT_MS` and `SQL_ROW_CAP`.
- **Length limit**: reject any candidate more than 30% longer than the seed. Endless prompt growth is the problem we are solving.

## 6.4 How a GEPA prompt reaches production

GEPA proposes. People decide. Nothing changes in production automatically.

- GEPA writes its best candidate, score history and a diff to `src/evals/gepa/runs/<date>/`.
- The candidate runs on **holdout**. It must pass every must_pass case, beat the current prompt on its own metric, and lower no other score by more than 1 point.
- A person reads the diff and opens a normal PR. Reject wording that fits the data too closely, such as a rule naming one test building.
- Deploy behind its `prompt_version` tag and compare thumbs-up, fallback, empty-result and grounding rates for a week. Roll back by reverting the PR.

## 6.5 The self-improvement loop

**Figure 5.** *The monthly loop. Each cycle makes the eval set closer to real traffic.*

Production failures feed the eval set every week. GEPA tunes against it every month. Every change passes the holdout gate and a human review. Refresh the holdout set once a quarter from new production cases so it stays representative.

# 7. What we are deliberately not doing

- **No automatic prompt changes online.** A buyer may act on a figure. Every change passes a gate and a review.
- **No DSPy or framework migration.** GEPA works through an adapter around the current LangGraph code.
- **No GEPA on the reply prompt yet.** It needs a calibrated judge, and most wrong answers start in routing and SQL, which have exact metrics.
- **No new clarify route.** `QueryRoute` deliberately has none. Add one only if evals show ambiguity ("Downtown" meaning Downtown Dubai or Downtown Jebel Ali) is a top failure.
- **No model swap** in this plan. A different model can be compared later on the same eval.
- **No prompt rule without an eval case.** Bugs still get fixed, but each fix also adds a case.

# 8. Timeline and targets

**Figure 6.** *Six-week plan. Baselines are measured at the end of week 2.*

Targets are relative to the week-2 baseline, so we do not guess numbers before measuring them:

| Measure | Target by end of week 6 |
| --- | --- |
| Holdout result correctness (lookups) | +10 points over baseline |
| Holdout route accuracy | ≥ 95% |
| Data-backed replies with an ungrounded number | < 1% of turns |
| Production thumbs-down rate | 25% lower than the first two weeks of collected votes |
| must_pass failures on main | 0, every night |
| Prompt rules added without an eval case | 0 |

When these hold, the team can answer "is the bot better than last month?" with a number. The prompts then improve from real failures in a measured way, instead of gaining another rule after each complaint.
