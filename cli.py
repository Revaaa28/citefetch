#!/usr/bin/env python3
"""Single-question CLI.

    python3 cli.py "What is the price of A Light in the Attic?" \
        --url http://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html

Prints one JSON object: {"answer", "source_url", "evidence", "confidence"}.
An empty "answer" means the agent could not verify a value (fail closed).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import answer_question  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Ask the web one question.")
    parser.add_argument("query", help="natural-language question")
    parser.add_argument("--url", default=None,
                        help="optional start URL to navigate from")
    args = parser.parse_args()
    result = answer_question(args.query, args.url)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
