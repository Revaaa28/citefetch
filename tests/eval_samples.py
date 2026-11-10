#!/usr/bin/env python3
"""Live evaluation of the sample batch (requires network access).

Runs the three sample queries from data/inputs/queries.json through the
full pipeline and compares each answer with the known-correct value, plus
one fail-closed probe (a question whose answer does not exist on the
given page must return an empty answer, not a guess).

    python3 tests/eval_samples.py

Status per query: PASS (correct cited answer), MISS (failed closed —
safe but unanswered; can happen when the search endpoints are being
rate-limited), WRONG (a non-empty answer that is not the expected value —
the failure mode this agent is designed never to produce).
Exit codes: 0 = all PASS, 1 = any WRONG, 2 = any MISS and no WRONG.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from agent import answer_question  # noqa: E402

EXPECTED = {
    "q1": lambda a: a == "Guido van Rossum",
    "q2": lambda a: "1991" in a,
    "q3": lambda a: a == "£51.77",
}

FAIL_CLOSED_PROBE = {
    "id": "probe-fail-closed",
    "query": "What is the phone number of the author of A Light in the Attic?",
    "start_url": "http://books.toscrape.com/catalogue/a-light-in-the-"
                 "attic_1000/index.html",
    "check": lambda a: a == "",
}


def _load_samples():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        "data", "inputs", "queries.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    worst = 0
    for item in _load_samples():
        result = answer_question(item["query"], item.get("start_url"))
        answer = result["answer"]
        check = EXPECTED[item["id"]]
        if not answer:
            status, code = "MISS (failed closed)", 2
        elif check(answer):
            status, code = "PASS", 0
        else:
            status, code = "WRONG", 1
        worst = max(worst, code) if code == 1 else (worst or code)
        print(f"{item['id']}: {status}  answer={answer!r} "
              f"confidence={result['confidence']} source={result['source_url']}")
    probe = FAIL_CLOSED_PROBE
    result = answer_question(probe["query"], probe["start_url"])
    ok = probe["check"](result["answer"])
    print(f"{probe['id']}: {'PASS' if ok else 'WRONG'}  "
          f"answer={result['answer']!r} (expected empty)")
    if not ok:
        worst = 1
    print("overall:", {0: "PASS", 1: "WRONG ANSWERS PRESENT",
                       2: "no wrong answers, some misses"}[worst])
    return worst


if __name__ == "__main__":
    sys.exit(main())
