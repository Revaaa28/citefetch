# Evaluation record — sample batch

Sample batch: `data/inputs/queries.json` (3 questions). Known-correct
values: q1 = "Guido van Rossum", q2 = a 1991 release date for Python,
q3 = "£51.77". Runs executed locally on the development VM
(Python 3.12.3, `requests` 2.31.0) on 2026-11-10. Live results depend on
network conditions — the interesting comparison is *wrong answers*, which
the agent is designed never to produce, vs. *misses* (fail closed), which
are the safe failure mode.

## Baseline (original partial build, before fixes)

Batch run via `python3 run.py data/inputs/queries.json`:

| id | answer | conf | verdict |
|----|--------|------|---------|
| q1 | "General Python" | 0.74 | **WRONG** — reference-section boilerplate ("General Python FAQ") out-scored "Guido van Rossum" (5.86 vs 5.18 aggregated) |
| q2 | "" | 0.0 | MISS — failed closed; diagnosed as intermittent DuckDuckGo HTML-endpoint bot-blocking (0 result URLs on some calls) |
| q3 | "£51.77" | 0.79 | PASS |

CLI re-runs of q2 alternated between "1991" (correct) and "" — confirming
search reliability, not extraction, as the q2 problem.

## Fixes applied (in order)

1. `agent/extract.py` — subject-overlap penalty (−1.6 per token) for name
   candidates containing the question's own keywords; sentence/UI starter
   words added to the name validator's stop-start set; "designer" added to
   the role-context list.
2. `agent/fetch.py` — DuckDuckGo lite endpoint as a top-up fallback when
   the HTML endpoint returns too few results (the endpoints fail on
   different schedules).
3. `agent/pipeline.py` — one retry search round when the first round
   yields no confident candidate.
4. `agent/fetch.py` — one quiet retry (1.5 s pause) for a failed page
   fetch, so losing the most authoritative page to a transient error
   cannot flip an answer to a weaker source.
5. `agent/pipeline.py` — the retry round now pauses 8 s and searches
   wider (top 6), adding only not-yet-gathered pages.

## After fixes

**Live eval** (`python3 tests/eval_samples.py`, exit code 0):

| check | answer | conf | verdict |
|-------|--------|------|---------|
| q1 | "Guido van Rossum" | 0.71 | PASS |
| q2 | "1991" | 0.79 | PASS (evidence: "Van Rossum first released it in 1991 as Python 0.9.0") |
| q3 | "£51.77" | 0.79 | PASS |
| fail-closed probe (author's phone number, not on the page) | "" | 0.0 | PASS — no guess |

**Repeat batch runs** (same command as baseline): three consecutive full
runs after the final fix set — 3/3 correct in each (q1 "Guido van
Rossum", q2 "1991", q3 "£51.77"). Across all post-fix batch runs, the
only imperfect run was one q2 MISS observed after fix set 1–3 during a
search-endpoint blackout window; that observation motivated fixes 4–5.

**Unit tests** (`python3 tests/test_agent_units.py`): 9/9 pass —
classification, keyword extraction, the subject-overlap behaviour on
synthetic text, sentence-starter rejection, phone validation,
cross-page corroboration, confidence bounds, and the LLM hook being
inert when unconfigured.

**Extra spot checks** (CLI, after fixes):

| question | answer | conf |
|----------|--------|------|
| "Who wrote the novel Pride and Prejudice?" | "Jane Austen" | 0.75 |
| "When was the Eiffel Tower completed?" | "March 1889" | 0.72 |

## Known residual risk

Search-mode questions can still fail closed if both DuckDuckGo endpoints
are simultaneously rate-limiting this egress IP (observed in bursts
during heavy repeated testing). The agent treats that as "search
unavailable" and answers empty rather than guessing. Spot checks also
showed that a partially fetched page set can elevate a weaker value
(e.g. "December 1989" — implementation start — when the main Python page
fails to load); fix 4 (fetch retry) targets exactly that case.
