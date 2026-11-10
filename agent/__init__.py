"""ExactFind — a web information retrieval agent.

Given a natural-language question (and optionally a start URL), it navigates
the web, extracts one exact value of the type the question asks for, and
returns it with its source URL and evidence — or an empty answer when it
cannot verify anything (fail closed, never guess).
"""
from .pipeline import answer_question

__all__ = ["answer_question"]
__version__ = "1.0.0"
