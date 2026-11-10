#!/usr/bin/env python3
"""Network-free unit tests for the deterministic core of the agent.

Run from the project root:
    python3 -m unittest discover -s tests -v
or directly:
    python3 tests/test_agent_units.py

These tests pin the design principles: typed classification, the
subject-overlap penalty for name candidates, corroboration in ranking,
name validation, fail-closed extraction, and the LLM hook being inert
when unconfigured. The live behaviour (search, fetching) is covered by
tests/eval_samples.py instead, because it depends on the network.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from agent.classify import classify, question_keywords  # noqa: E402
from agent.extract import Candidate, aggregate, extract_candidates  # noqa: E402
from agent import llm  # noqa: E402


class TestClassify(unittest.TestCase):
    def test_types(self):
        self.assertEqual(classify("Who created the Python language?"), "name")
        self.assertEqual(classify("When was Python first released?"), "date")
        self.assertEqual(classify("What is the price of this book?"), "price")
        self.assertEqual(classify("How many employees does Acme have?"), "number")
        self.assertEqual(classify("What is the email address of support?"), "email")
        self.assertEqual(classify("What is their phone number?"), "phone")

    def test_keywords_drop_stopwords(self):
        kws = question_keywords("Who created the Python programming language?")
        self.assertIn("python", kws)
        self.assertIn("created", kws)
        self.assertNotIn("who", kws)
        self.assertNotIn("the", kws)


class TestNameExtraction(unittest.TestCase):
    def test_subject_phrase_does_not_outrank_person(self):
        # "General Python" is subject boilerplate; the person after
        # "created by" must win despite the phrase's keyword density.
        text = (
            "Python was created by Guido van Rossum in the Netherlands. "
            "The General Python FAQ answers questions about Python created "
            "for learners of the Python programming language."
        )
        kws = question_keywords("Who created the Python programming language?")
        ranked = aggregate(extract_candidates(text, "name", kws, "http://x", 0))
        self.assertTrue(ranked)
        self.assertEqual(ranked[0].value, "Guido van Rossum")

    def test_sentence_starters_are_not_names(self):
        text = "Why We Built The Thing is a post. It was written by Jane Doe."
        kws = question_keywords("Who wrote this post?")
        values = [c.value for c in extract_candidates(text, "name", kws,
                                                      "http://x", 0)]
        self.assertIn("Jane Doe", values)
        self.assertNotIn("Why We Built", values)

    def test_no_value_means_no_candidates(self):
        text = "This page talks about many things but states no people."
        kws = question_keywords("Who founded the company?")
        self.assertEqual(extract_candidates(text, "name", kws, "http://x", 0),
                         [])

    def test_phone_candidates_need_plausible_digits(self):
        text = "Call us on +1 (555) 123-4567 or dial 42 for fun."
        kws = question_keywords("What is the phone number?")
        values = [c.value for c in extract_candidates(text, "phone", kws,
                                                      "http://x", 0)]
        self.assertTrue(any("555" in v for v in values))
        self.assertNotIn("42", values)


class TestAggregate(unittest.TestCase):
    def test_corroboration_across_pages_beats_single_page(self):
        one = Candidate("1991", "http://a", "ev", score=4.0)
        two_a = Candidate("2000", "http://a", "ev", score=4.0)
        two_b = Candidate("2000", "http://b", "ev", score=4.0)
        ranked = aggregate([one, two_a, two_b])
        self.assertEqual(ranked[0].value, "2000")

    def test_confidence_squash_bounds(self):
        c = Candidate("x", "http://a", "ev", score=3.4)
        self.assertGreater(c.confidence, 0.0)
        self.assertLessEqual(c.confidence, 0.97)


class TestLlmHookInert(unittest.TestCase):
    def test_unconfigured_rerank_returns_none(self):
        saved = {k: os.environ.pop(k, None)
                 for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY")}
        try:
            cands = [Candidate("a", "http://a", "e", score=5.0),
                     Candidate("b", "http://b", "e", score=4.0)]
            self.assertIsNone(llm.rerank("q?", cands))
        finally:
            for key, val in saved.items():
                if val is not None:
                    os.environ[key] = val


if __name__ == "__main__":
    unittest.main(verbosity=2)
