"""End-to-end pipeline: question (+ optional start URL) -> cited answer.

1. Classify the target value type and pull content keywords.
2. Gather pages. With a start URL, that page is searched first; up to 2
   relevant out-links are followed ONLY if the start page alone yields no
   confident candidate (link-following is a fallback, not a default — it
   keeps site chrome and mirror pages from outvoting the source the user
   actually pointed at). Without a start URL, the top 3 DuckDuckGo results
   are searched; if that yields no confident candidate, one wider retry
   search runs after a short pause (search endpoints rate-limit in bursts).
3. Extract and score typed candidates on every gathered page.
4. Optionally let a configured LLM pick among the top candidates.
5. Answer only if the best candidate clears the confidence threshold —
   otherwise fail closed with an empty answer rather than guessing.
"""
import urllib.parse

from .classify import classify, question_keywords
from .extract import aggregate, extract_candidates
from .fetch import ddg_search, fetch_url, parse_page
from . import llm

EMPTY_RESULT = {"answer": "", "source_url": "", "evidence": "", "confidence": 0.0}
ANSWER_THRESHOLD = 3.4  # raw candidate score needed before we dare answer
MAX_FOLLOW_LINKS = 2
SEARCH_RESULTS = 3

_LINK_BLOCKLIST = ("login", "signin", "sign-in", "register", "/auth",
                   "createaccount", "userlogin",
                   # non-article namespaces (MediaWiki etc.) are noise
                   "talk:", "special:", "user:", "file:", "category:",
                   "template:", "help:", "draft:",
                   # site chrome: edit/history/info views of the same page
                   "action=edit", "action=history", "action=info",
                   "oldid=", "printable=")


def _relevant_links(links, keywords, base_url, visited, limit=MAX_FOLLOW_LINKS):
    """Up to `limit` out-links whose anchor/href mention a question keyword."""
    scored = []
    for href, anchor in links:
        absolute = urllib.parse.urljoin(base_url, href)
        if not absolute.startswith("http") or absolute in visited:
            continue
        if absolute.split("#")[0] in visited:
            continue
        if any(bad in absolute.lower() for bad in _LINK_BLOCKLIST):
            continue  # login walls and site chrome never hold the answer
        haystack = (anchor + " " + href).lower()
        hits = sum(1 for kw in keywords if kw in haystack)
        if hits:
            scored.append((hits, absolute))
    # Prefer links that stay on the same host (avoids language-variant and
    # mirror pages whose text the scorer cannot judge as reliably).
    base_host = urllib.parse.urlparse(base_url).netloc
    scored.sort(key=lambda item: (
        urllib.parse.urlparse(item[1]).netloc != base_host, -item[0]))
    chosen, seen = [], set()
    for _hits, url in scored:
        clean = url.split("#")[0]
        if clean not in seen:
            seen.add(clean)
            chosen.append(url)
        if len(chosen) >= limit:
            break
    return chosen


def _fetch_page(url):
    fetched = fetch_url(url)
    if not fetched:
        return None
    final_url, html = fetched
    text, links = parse_page(html)
    return final_url, text, links


def answer_question(query, start_url=None):
    """Answer one natural-language question with a cited exact value."""
    vtype = classify(query)
    keywords = question_keywords(query)
    candidates = []

    def add_page(index, url, text):
        candidates.extend(extract_candidates(text, vtype, keywords, url, index))

    if start_url:
        first = _fetch_page(start_url)
        if first:
            final_url, text, links = first
            add_page(0, final_url, text)
            ranked = aggregate(candidates)
            if not ranked or ranked[0].score < ANSWER_THRESHOLD:
                # Fallback only: follow up to MAX_FOLLOW_LINKS relevant links.
                visited = {final_url, start_url}
                for i, link in enumerate(
                        _relevant_links(links, keywords, final_url, visited),
                        start=1):
                    page = _fetch_page(link)
                    if page:
                        add_page(i, page[0], page[1])
    else:
        urls = ddg_search(query, limit=SEARCH_RESULTS)
        for i, url in enumerate(urls):
            page = _fetch_page(url)
            if page:
                add_page(i, page[0], page[1])
        ranked = aggregate(candidates)
        if not ranked or ranked[0].score < ANSWER_THRESHOLD:
            # One retry round with a fresh, wider search after a pause:
            # the search endpoints are intermittently bot-checked or
            # rate-limited in bursts, and a first round that gathered too
            # little is worth one more attempt before failing closed.
            # Only pages not already gathered are added.
            import time

            time.sleep(8)
            wider = ddg_search(query, limit=SEARCH_RESULTS + 3)
            for j, url in enumerate(wider):
                if url in urls:
                    continue
                page = _fetch_page(url)
                if page:
                    add_page(len(urls) + j, page[0], page[1])

    ranked = aggregate(candidates)
    if not ranked:
        return dict(EMPTY_RESULT)

    best = ranked[0]
    pick = llm.rerank(query, ranked)
    if pick is not None:
        best = ranked[pick]

    if best.score < ANSWER_THRESHOLD:
        return dict(EMPTY_RESULT)
    return {
        "answer": best.value,
        "source_url": best.source_url,
        "evidence": best.evidence,
        "confidence": best.confidence,
    }
