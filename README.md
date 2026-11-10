# ExactFind — Intelligent Web Information Retrieval Agent

Built for the **AMD AI League (lablab) Match 4: "Intelligent Web Information
Retrieval"** (1,800 pts). Given a natural-language question — and optionally a
start URL — the agent navigates the web, extracts **one exact value** of the
type the question asks for (a name, date, price, number, phone, or email), and
returns it with the **source URL and an evidence snippet**. When it cannot
verify a value above its confidence threshold it returns an **empty answer
rather than guessing** ("fail closed").

The agent is a deterministic Python pipeline — typed extraction + transparent
scoring — with an optional LLM verification hook. It runs on CPU with no GPU
requirement; see "Compute" below for exactly what that means.

## How it works

```
question ──► classify ──► gather pages ──► extract typed candidates
                │              │                      │
                │              │                      ▼
                │              │              score + aggregate
                │              │              (corroboration across pages)
                │              ▼                      │
                │     start URL: that page first;   ▼
                │     up to 2 relevant out-links    optional LLM re-rank
                │     followed ONLY if the start    (top candidates only)
                │     page alone is not confident   │
                │     no start URL: top-3 search    ▼
                │     results + one wider retry     answer only if the best
                │     round after a pause           candidate clears the
                └───── target type + keywords       threshold, else EMPTY
```

1. **Classify** (`agent/classify.py`) — the question's trigger words decide
   the target value type and the content keywords used for scoring.
2. **Gather** (`agent/fetch.py`, `agent/pipeline.py`) — with a start URL,
   that page is searched first; relevant out-links (same host preferred,
   login/chrome links blocked) are followed **only as a fallback** when the
   start page alone yields no confident candidate. Without a start URL, the
   top DuckDuckGo results are searched; if that produces nothing confident,
   one wider retry search runs after a short pause (the search endpoints
   rate-limit in bursts). Search tries the DDG HTML endpoint first and tops
   up from the DDG lite endpoint, which fails on a different schedule.
3. **Extract** (`agent/extract.py`) — per-type regex patterns produce
   candidates, each carrying its source URL and an evidence snippet. Scoring
   is deterministic: pattern strength + keyword proximity (IDF-weighted) +
   distance bonus + early-position and page-order bonuses + a role-context
   bonus for names ("designed by ~"). Name candidates that literally contain
   the question's subject keywords are penalised — they are almost always
   the subject's own documentation, not the answer. Identical values are
   aggregated, with a corroboration bonus for appearing on *different* pages.
4. **Verify (optional)** (`agent/llm.py`) — if `LLM_BASE_URL` and `LLM_MODEL`
   are set, the top candidates are sent to any OpenAI-compatible chat
   endpoint to pick the best one. Every failure returns "no pick" and the
   heuristic ranking stands; the agent is fully functional without an LLM.
5. **Answer or fail closed** — the best candidate must clear a raw-score
   threshold (3.4); otherwise the result is an empty answer with
   confidence 0.0.

## Run it

Requires Python 3.12+. Only third-party dependency: `requests` (the HTTP
layer falls back to stdlib `urllib` if it is unavailable).

```bash
pip install -r requirements.txt

# Single question (optional start URL)
python3 cli.py "Who created the Python programming language?" \
    --url https://en.wikipedia.org/wiki/Python_(programming_language)
python3 cli.py "When was Python first released?"

# Batch: JSON/JSONL in, JSONL out
python3 run.py data/inputs/queries.json            # results to stdout
python3 run.py data/inputs/queries.json out.jsonl  # results to a file
```

Docker (same batch contract; the image was not build-tested on the
development VM, which has no Docker — the Dockerfile is a standard
`python:3.12-slim` build):

```bash
docker build -t exactfind .
docker run --rm exactfind            # reads /app/data/inputs/queries.json
```

Optional LLM verification:

```bash
export LLM_BASE_URL=https://your-endpoint/v1
export LLM_MODEL=your-model
export LLM_API_KEY=...               # optional
```

## Input / output format

Input (JSON array or JSONL), `start_url` optional:

```json
[{"id": "q1", "query": "Who created the Python programming language?",
  "start_url": "https://en.wikipedia.org/wiki/Python_(programming_language)"}]
```

Output, one JSON object per line, input order preserved:

```json
{"id": "q1", "answer": "Guido van Rossum",
 "source_url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
 "evidence": "...The designer of Python, Guido van Rossum, at PyCon US 2024...",
 "confidence": 0.71}
```

`confidence` is the raw candidate score squashed into (0, 0.97). An empty
`answer` with `confidence: 0.0` means **fail closed** — no value could be
verified. Batch exit codes: 0 = run completed (individual questions may fail
closed), 2 = input missing/unparseable.

## Tests & evaluation

```bash
python3 tests/test_agent_units.py   # 9 network-free unit tests
python3 tests/eval_samples.py       # live eval of the sample batch + a
                                    # fail-closed probe (needs network)
```

Recorded baseline vs. final results: see **EVAL.md**.

## Compute — stated honestly

This agent is **CPU-only Python** (stdlib + `requests`). It does **not** use
an AMD GPU, ROCm, or any GPU inference, and it does not need the AMD
Developer Cloud credits: web retrieval and deterministic extraction are not
GPU workloads. The only model involved is the *optional* LLM re-ranker,
which calls an external OpenAI-compatible API **if the operator configures
one**; with no LLM configured, ranking is purely heuristic and no model —
local or remote — is run. Nothing in this README should be read as claiming
AMD hardware acceleration.

## Limitations

- **Search dependency.** Without a start URL the agent relies on
  DuckDuckGo's public HTML/lite endpoints, which intermittently bot-check
  or rate-limit (in bursts, per egress IP). The pipeline retries with a
  wider, paused second round, but during a hard blackout a question can
  still fail closed. Fail-closed is the designed behaviour in that case.
- **Exact values only.** It answers factoid questions whose answer is a
  single typed value (name/date/price/number/phone/email). It does not
  summarise, compare, or reason over multiple facts.
- **Heuristic ranking.** Scoring is transparent but hand-tuned; unusual
  page layouts (heavy JavaScript apps, login-walled or PDF sources) can
  defeat extraction. Pages are read as static HTML; no browser rendering.
- **Granularity.** A date question may be answered at year granularity
  ("1991") when that is the most corroborated value on the sources.
- **English-centric.** Classification triggers, name patterns, and month
  names are English.
