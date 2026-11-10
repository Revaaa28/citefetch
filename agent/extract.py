"""Candidate value extraction from page text, plus ranking/scoring.

Every candidate records where it was found so the caller can cite the exact
source URL and show a short evidence snippet. Scoring is deterministic:
type match + question-keyword proximity + early position + page order +
corroboration (the same value appearing on multiple pages).
"""
import re
from dataclasses import dataclass, field

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)

PATTERNS = {
    "price": [
        (re.compile(r"[$€£¥]\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b"), 0.7),
        (re.compile(r"\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s?(?:USD|EUR|GBP|dollars|euros|pounds)\b"), 0.7),
        (re.compile(r"[$€£¥]\s?\d+(?:\.\d{2})?\b"), 0.4),
    ],
    "date": [
        (re.compile(r"\b(?:" + _MONTHS + r")\s+\d{1,2},\s+\d{4}\b"), 0.9),
        (re.compile(r"\b\d{1,2}\s+(?:" + _MONTHS + r")\s+\d{4}\b"), 0.9),
        (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), 0.7),
        (re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"), 0.6),
        (re.compile(r"\b(?:" + _MONTHS + r")\s+\d{4}\b"), 0.5),
        (re.compile(r"\b(?:1[5-9]|20)\d{2}\b"), 0.2),  # bare year
    ],
    "phone": [
        (re.compile(r"\+\d[\d\s().-]{6,}\d"), 0.6),
        (re.compile(r"\(\d{3}\)\s?\d{3}-\d{4}"), 0.6),
        (re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"), 0.5),
    ],
    "email": [
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), 0.8),
    ],
    "number": [
        (re.compile(r"\b\d+\.\d+\.\d+\b"), 0.6),                      # versions
        (re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"), 0.5),      # 1,234,567
        (re.compile(r"\b\d+\.\d+\b"), 0.4),                           # decimals
        (re.compile(r"\b\d+\b"), 0.15),                               # bare ints
    ],
    "name": [
        # [ \t] rather than \s: a real name does not span the line breaks of
        # extracted text, but navigation menus chain capitalised words that way.
        (re.compile(
            r"\b[A-Z][a-z]+(?:[ \t]+(?:[A-Z][a-z]+|de|van|von|der|den|di|le|"
            r"[A-Z]\.)){1,3}\b"), 0.4),
    ],
}

# Words that make a capitalised phrase a sentence fragment, not a name.
_NAME_STOP_START = {
    "The", "This", "That", "It", "In", "On", "At", "By", "For", "With",
    "From", "After", "Before", "When", "While", "He", "She", "They", "We",
    "However", "Also", "But", "And", "As", "If", "Its", "His", "Her",
    "Why", "How", "What", "When", "Where", "Which", "Who", "Can", "Do",
    "Does", "Is", "Are", "Was", "An", "One", "See", "Main", "Contents",
    "Toggle", "Retrieved", "Archived",
}

# Extra types folded into "other"/"name"/"number" fallback searches.
_FALLBACK = {"other": ["name", "number", "date"], "name": ["name"],
             "number": ["number"]}

WINDOW = 160  # chars either side of a candidate used for keyword proximity


@dataclass
class Candidate:
    value: str
    source_url: str
    evidence: str
    score: float = 0.0
    occurrences: int = 1
    extras: dict = field(default_factory=dict)

    @property
    def confidence(self):
        # Smooth squash of the raw score into (0, 0.97).
        return round(min(0.97, self.score / (self.score + 2.2)), 2)


def _snippet(text, start, end):
    lo = max(0, start - 90)
    hi = min(len(text), end + 90)
    snippet = " ".join(text[lo:hi].split())
    return ("..." if lo > 0 else "") + snippet + ("..." if hi < len(text) else "")


def _valid_phone(value):
    digits = re.sub(r"\D", "", value)
    return 7 <= len(digits) <= 15


def _valid_name(value):
    parts = value.split()
    if parts[0] in _NAME_STOP_START:
        return False
    if any(p.lower() in ("january", "february", "march", "april", "may",
                          "june", "july", "august", "september", "october",
                          "november", "december") for p in parts):
        return False
    return True


_VALIDATORS = {"phone": _valid_phone, "name": _valid_name}


def _keyword_weights(text_lower, keywords):
    """IDF-style weights: a keyword repeated all over the page (usually the
    page's own title words) discriminates poorly, so it counts less than a
    rare keyword such as the question's verb ('invented', 'released')."""
    weights = {}
    for kw in keywords:
        count = text_lower.count(kw)
        weights[kw] = 1.0 if count <= 4 else min(1.0, 12.0 / count)
    return weights


# Words that, right before a capitalised phrase, signal a person in a role
# ("designed by ~", "Original author ~", "founder ~").
_NAME_CONTEXT = ("by ", "author", "creator", "founder", "developer",
                 "inventor", "designed", "designer", "written", "founded",
                 "created", "director", "president", "ceo")

# Particles that legitimately appear inside person names and are never
# question keywords, so they are exempt from the subject-overlap penalty.
_NAME_PARTICLES = {"de", "van", "von", "der", "den", "di", "le", "the"}

# Per-token penalty for a name candidate that literally contains one of the
# question's content keywords. For name-type questions the answer is an
# entity distinct from the subject the question asks about, so a candidate
# built out of the subject's own words ("General Python", "Python Software
# Foundation" for "Who created the Python programming language?") is almost
# always the subject's documentation or boilerplate, not the answer. A
# penalty (not a hard reject) keeps genuinely ambiguous cases fail-soft.
SUBJECT_OVERLAP_PENALTY = 1.6


def extract_candidates(text, vtype, keywords, source_url, page_index):
    """All scored candidate occurrences of the target type on one page."""
    types = [vtype] if vtype in PATTERNS else _FALLBACK.get(vtype, ["name", "number"])
    lowered = text.lower()
    weights = _keyword_weights(lowered, keywords)
    page_bonus = max(0.1, 1.0 - 0.3 * page_index)
    found = []
    for t in types:
        validator = _VALIDATORS.get(t)
        for pattern, pattern_bonus in PATTERNS[t]:
            for match in pattern.finditer(text):
                value = match.group(0).strip()
                if validator and not validator(value):
                    continue
                bonus = pattern_bonus
                if t == "name":
                    before = lowered[max(0, match.start() - 60):match.start()]
                    if any(ctx in before for ctx in _NAME_CONTEXT):
                        bonus += 1.3
                    tokens = [tok.strip("'.-").lower()
                              for tok in value.split()]
                    overlap = sum(1 for tok in tokens
                                  if tok and tok not in _NAME_PARTICLES
                                  and tok in keywords)
                    bonus -= SUBJECT_OVERLAP_PENALTY * overlap
                if t == "number" and match.start() > 0:
                    prev = text[match.start() - 1]
                    if prev in "$€£¥" or prev.isdigit() or prev in ".,":
                        # Part of a price ("£51.77") or the fragment of a
                        # longer number ("77" in "51.77"), not standalone.
                        continue
                window = lowered[max(0, match.start() - WINDOW):
                                  match.end() + WINDOW]
                kw_score = sum(weights[kw] for kw in keywords if kw in window)
                score = 1.0 + bonus + page_bonus
                score += 1.2 * min(kw_score, 3.0)
                # Distance bonus: a value sitting right next to a strong
                # keyword ("released it in 1991") beats one that merely
                # shares a paragraph with it. Capped so it can only break
                # near-ties, never dominate the ranking on its own.
                dist_bonus = 0.0
                for kw in keywords:
                    if weights[kw] < 0.5:
                        continue
                    pos = lowered.find(kw, max(0, match.start() - 100))
                    while pos != -1 and pos < match.end() + 100:
                        dist = max(match.start() - (pos + len(kw)),
                                   pos - match.end(), 0)
                        if dist <= 40:
                            dist_bonus += 0.5
                        elif dist <= 90:
                            dist_bonus += 0.25
                        break
                score += min(dist_bonus, 0.6)
                if match.start() < 0.12 * max(len(text), 1):
                    score += 0.8  # facts usually sit near the top of a page
                found.append(Candidate(
                    value=value,
                    source_url=source_url,
                    evidence=_snippet(text, match.start(), match.end()),
                    score=score,
                ))
    return found


def aggregate(candidates):
    """Merge identical values and rank best-first.

    Corroboration bonus rewards the same value appearing on *different*
    pages; mere repetition on one page counts for much less.
    """
    by_value = {}
    for cand in candidates:
        key = re.sub(r"\s+", " ", cand.value.lower()).strip()
        if key in by_value:
            keeper = by_value[key]
            keeper.occurrences += 1
            keeper.extras.setdefault("sources", {keeper.source_url})
            keeper.extras["sources"].add(cand.source_url)
            if cand.score > keeper.score:
                keeper.score = cand.score
                keeper.evidence = cand.evidence
                keeper.source_url = cand.source_url
        else:
            cand.extras["sources"] = {cand.source_url}
            by_value[key] = cand
    ranked = list(by_value.values())
    for cand in ranked:
        distinct = len(cand.extras.get("sources", {cand.source_url}))
        repeats = cand.occurrences - distinct
        cand.score += 0.5 * min(distinct - 1, 2) + 0.1 * min(repeats, 3)
    ranked.sort(key=lambda c: (-c.score, c.value))
    return ranked
