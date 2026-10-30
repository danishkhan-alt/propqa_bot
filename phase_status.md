# PropQA improvement phases

Status against [.cursor/plans/start_propqa_improvements_06fb878a.plan.md](.cursor/plans/start_propqa_improvements_06fb878a.plan.md). The diagram of the same system is [architecture.mmd](architecture.mmd).

Phase 4 is open. The 30 Oct 2026 retest holdout exited 0. This file does not start a GEPA run.

Latest holdout: `logs/eval_20261030_131445.json`. `src/evals/baseline.json` is still the week-2 measurement (result correctness 77.78) and was not overwritten. Its SHA-256 is still `CED1BC8FACDDBF6CCCA35532AB1E030BCB150B6E4DCBCF058E9B764F0DF63F68`.

| Phase | Built | Exit check |
| --- | --- | --- |
| 1. Eval command and holdout | Yes | Met. Holdout exited 0. `must_pass` failures none. |
| 2. Thumbs stored | Yes | Met. Live thumbs check passed earlier. Offline tests passed again on 30 Oct 2026. |
| 3. Number check | Yes | Met. Offline tests passed, and the 30 Oct 2026 retest printed the ungrounded share. |
| 4. GEPA | Not started | Open. The three exit checks are met. No GEPA run has been opened. |

## Phase 1 — eval command and holdout

### Done

- Frozen `split`, `tags`, and `must_pass` on the existing golden files: `src/evals/sql_golden.yaml`, `src/evals/domain_router_golden.yaml`, `src/evals/router_golden.yaml`. Holdout ids are not exported for a later GEPA train or val set.
- One command: `python -m evals.run_all --split holdout`. It runs the router, domain, and lookup suites, writes one JSON report under `logs/`, and records a Langfuse dataset run when keys are set.
- Every miss is one sentence. Router, domain, value, and listing scorers all return that sentence.
- The process exits 1 when any `must_pass` case fails, or when holdout result correctness drops more than 2 points below `src/evals/baseline.json`. Latency, fallback rate, cost, and the ungrounded-number share are printed and do not change the exit code.
- Baseline saved from a real holdout (`logs/eval_20261029_161714.json`): route accuracy 100, domain accuracy 100, result correctness 77.78, `must_pass` failures none. That file is the week-2 measurement. Later runs did not rewrite it.
- Lookup behavior that the holdout exposed was fixed in general rules, not by editing the golden answers: named-place lists use listing search, bare arithmetic with no property subject is out of scope, a compare of two places keeps the locations join, `HAVING COUNT(*)` is kept, one average for a place is one row, and a place filter moves onto the column that stores the name. Listing replies can cite inventory total, completion, furnished, rounded rent, a building name, and the same rent in another period when the fact sheet supports them.
- A unitless number equal to `inventory_total` is supported in any word order, including “the number of properties is 176”. “There are 10 properties” still fails when the total is 176. “10 of the 176” is allowed. A price such as “AED 176” or “176 sq ft” is not treated as the count. `python -m evals.run_all` accepts a repeatable `--case`.

### Exit check

Met again by `logs/eval_20261030_131445.json`, after the bedroom-shorthand and million-range checker change:

- Route accuracy 100.0 (5/5)
- Domain accuracy 100.0 (10/10)
- Result correctness 100.0 (9/9), above the saved 77.78
- Ungrounded numbers 33.3% (3 of 9 data-backed replies). Printed only. It did not change the exit code.
- `must_pass` failures: none
- Exit code 0
- Baseline file unchanged

The earlier full holdout `logs/eval_20261030_110842.json` had also exited 0, with an ungrounded share of 66.7% (6 of 9). `marina_listings_typo` was run on its own three times before that holdout. Two exited 0 (`logs/eval_20261030_110005.json`, `logs/eval_20261030_110216.json`). The third exited 1 (`logs/eval_20261030_110443.json`) on `Aeternitas Tower 2 B/R for Sale priced around AED 4.24 to 4.25 million`, with the search itself correct. The checker now accepts that sentence, and the 13:14 holdout includes the same case and passed.

### Not part of this exit

Labeling toward the larger set in `testquries.md` (router 150, domain 100, lookup 120, multi-turn 20) is ongoing. The plan says that growth is not a blocker for the command. A nightly GitHub workflow was left for later. There is still no `.github` workflow.

## Phase 2 — thumbs stored

### Done

- A reply keeps a stable `turn_id`. A reload reads that id instead of minting a new one. Older checkpoints fall back to the session id plus the user and assistant text.
- `chat_feedback` on the chat database stores one vote per turn. A second vote updates the same row. The vote is not written into the LangGraph checkpoint.
- `POST /api/feedback/thumbs` is mounted under `/api`, uses the generic API rate limit, and does not consume the chat bucket.
- `GET /sessions/{session_id}/turns` adds `thumbs_up` and `thumbs_down`.
- Each turn’s Langfuse span carries `prompt_version`, `route`, `domain_ids`, and `fallback_fired`. A thumbs vote writes a `user_feedback` score (`1.0` or `0.0`). Missing Langfuse keys stay a no-op.
- `POST /api/feedback/correction` and the admin stats routes were left alone.
- Offline tests cover the store, the route, reload, and the score writer: `src/common/tests/test_feedback_store.py`, `src/routes/tests/test_feedback.py`, `src/agent/tests/test_trace_tags.py`. On 30 Oct 2026 those passed again with the listing-score, eval-gate, and grounding-check tests: 56 passed.

### Exit check

Met earlier with a live click: the thumbs request returned 200, a reload showed the same thumb, and the trace had the four tags plus `user_feedback`.

### Blockage

None. The 30 Oct 2026 retest holdout exited 0, including `marina_listings_typo`. Phase 2 does not block Phase 4.

## Phase 3 — number check

### Done

- `src/agent/reply/grounding_check.py` is plain Python. It is not under `src/agent/grounding/`, which resolves names.
- The check reads prices, counts, sizes, percentages, and years and uses the same display rounding as `format_figure`, so `AED 1.2M` matches `1195000`. A number is allowed when it matches a row, a column min, max, or count, a listing fact, `listing_count`, a filter, a coverage date, or the Golden Visa minimum. Anything else is one sentence.
- Offline tests in `src/agent/tests/test_grounding_check.py` cover the rounded price, a count copied from `listing_count`, an unsourced number, and the Golden Visa minimum. They passed with no network.
- After a lookup reply has already streamed, production writes a Langfuse score named `answer_grounding`: `1.0` when nothing is flagged, `0.0` when something is, with the sentences as the comment. Greetings and out-of-scope replies are not scored. The message stored for the user is the text already streamed.
- `run_all` records the share of data-backed replies that contain an ungrounded number and prints it. Listing pass/fail stays the listing justification. The share does not change the `must_pass` exit code.

### Exit check

Met. Offline tests passed on 30 Oct 2026, and `logs/eval_20261030_131445.json` printed the share: **33.3% (3 of 9 data-backed replies)**. Earlier the same day a holdout printed 66.7% (6 of 9). On 29 Oct the share was 22.2% (2 of 9) and 33.3% (3 of 9). No replacement UI was added. The plan keeps that UI until a later pass. The week-6 target of under 1% belongs to Phase 4, not to this exit.

### Blockage

None inside Phase 3. The ungrounded share is printed and does not fail the run. The week-6 target of under 1% is still ahead.

## Phase 4 — GEPA

### Done

Nothing. `src/evals/gepa/` does not exist. The router prompt and the SQL draft prompt have not been split into a fixed prefix, an optimisable middle, and a fixed suffix. `LangChainAgentModels` has no prompts override. The `gepa` package is not pinned.

### Blockage

None on the exit checks. The 30 Oct 2026 retest left no must_pass failure and no correctness drop, so Phase 4 can start with the query router, then the SQL drafter. Train and val only. A candidate is written under `src/evals/gepa/runs/<date>/` and reaches production only through a reviewed PR after a person runs holdout: every `must_pass` case passes, the candidate beats the current prompt on its own metric, and no other score drops by more than 1 point. Leave the Jev domain router and `STRUCTURED_REPLY_SYSTEM` alone. No GEPA run has been opened yet.

Week-6 targets, judged against the Phase 1 baseline of 77.78 result correctness, stay ahead of this work: lookup correctness +10 points, route accuracy at least 95%, ungrounded numbers under 1% of data-backed turns, thumbs-down 25% lower than the first two weeks of votes, and zero nightly `must_pass` failures.
