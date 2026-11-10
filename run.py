#!/usr/bin/env python3
"""Batch entrypoint (the container's /app/run.py).

Reads questions from a JSON array or JSONL file:
    [{"id": "q1", "query": "...", "start_url": "https://..."}, ...]
`start_url` is optional. Writes one JSON result per line (JSONL), preserving
input order, each line: {"id", "answer", "source_url", "evidence",
"confidence"}.

Usage: python3 run.py [input_file] [output_file]
Default input:  /app/data/inputs/queries.json (or ./data/inputs/queries.json
next to this script), default output: stdout.
Exit codes: 0 = run completed (individual questions may fail closed with an
empty answer), 2 = input missing/unparseable (hard failure).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import answer_question  # noqa: E402

EMPTY = {"answer": "", "source_url": "", "evidence": "", "confidence": 0.0}


def _default_input():
    candidates = [
        "/app/data/inputs/queries.json",
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "data", "inputs", "queries.json"),
        os.path.join(os.getcwd(), "data", "inputs", "queries.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _load_items(path):
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read().strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        return [data]
    except json.JSONDecodeError:
        items = []
        for line in raw.splitlines():
            line = line.strip()
            if line:
                items.append(json.loads(line))
        return items


def main(argv):
    input_path = argv[1] if len(argv) > 1 else _default_input()
    output_path = argv[2] if len(argv) > 2 else None
    if not input_path or not os.path.isfile(input_path):
        print("error: no input file found", file=sys.stderr)
        return 2
    try:
        items = _load_items(input_path)
    except Exception as exc:
        print(f"error: cannot parse input: {exc}", file=sys.stderr)
        return 2

    lines = []
    for index, item in enumerate(items):
        qid = item.get("id", index)
        query = item.get("query", "")
        try:
            result = answer_question(query, item.get("start_url"))
        except Exception:
            result = dict(EMPTY)  # one bad question must not kill the batch
        lines.append(json.dumps({"id": qid, **result}, ensure_ascii=False))

    payload = "\n".join(lines) + ("\n" if lines else "")
    if output_path:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(payload)
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
