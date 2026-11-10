"""HTTP fetching, HTML-to-text conversion, and DuckDuckGo search.

Uses `requests` when available and falls back to urllib so the agent runs
anywhere Python 3.12 does (including the slim container image).
"""
import re
import urllib.parse
from html.parser import HTMLParser

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 15
MAX_TEXT_CHARS = 200_000

try:
    import requests

    _SESSION = requests.Session()
    _SESSION.headers.update({"User-Agent": USER_AGENT})
except Exception:  # pragma: no cover - requests is a declared dependency
    requests = None
    _SESSION = None


def _fetch_once(url):
    if _SESSION is not None:
        resp = _SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return None
        return resp.url, resp.text
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.geturl(), resp.read().decode(charset, errors="replace")


def fetch_url(url):
    """Fetch a URL, returning (final_url, html) or None on any failure.

    One quiet retry after a short pause: single-page fetch failures are
    usually transient proxy/network hiccups, and losing the most
    authoritative page can flip an answer to a weaker source.
    """
    import time

    for attempt, delay in enumerate((0, 1.5)):
        if delay:
            time.sleep(delay)
        try:
            result = _fetch_once(url)
        except Exception:
            result = None
        if result:
            return result
    return None


class _PageParser(HTMLParser):
    """Collects visible text chunks and (href, anchor-text) link pairs."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.text_chunks = []
        self.links = []
        self._link_href = None
        self._link_text = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._link_href = href
                self._link_text = []
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "br"):
            self.text_chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "a" and self._link_href is not None:
            anchor = " ".join("".join(self._link_text).split())
            self.links.append((self._link_href, anchor))
            self._link_href = None

    def handle_data(self, data):
        if self._skip_depth:
            return
        self.text_chunks.append(data)
        if self._link_href is not None:
            self._link_text.append(data)


def parse_page(html):
    """Return (text, links) for an HTML document. Text is whitespace-normalised
    per line so character offsets stay meaningful for snippet extraction."""
    parser = _PageParser()
    try:
        parser.feed(html)
    except Exception:
        return "", []
    lines = []
    for line in "".join(parser.text_chunks).split("\n"):
        line = " ".join(line.split())
        if line:
            lines.append(line)
    text = "\n".join(lines)[:MAX_TEXT_CHARS]
    return text, parser.links


def _unwrap_result_href(href):
    """Resolve one search-result href to a real URL, or None.

    Both DDG endpoints wrap targets in an 'uddg' query parameter (the lite
    endpoint uses protocol-relative redirect hrefs); a direct http(s) href
    that is not a duckduckgo.com internal link is already the target.
    """
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        target = qs.get("uddg", [None])[0]
        return target if target and target.startswith("http") else None
    if href.startswith("http") and "duckduckgo.com" not in href:
        return href
    return None


def _endpoint_urls(base, query, limit):
    """Result URLs from one DuckDuckGo endpoint ('' HTML or 'lite/')."""
    url = base + urllib.parse.quote_plus(query)
    fetched = fetch_url(url)
    if not fetched:
        return []
    results = []
    for href, _anchor in parse_page_links_only(fetched[1]):
        target = _unwrap_result_href(href)
        if target and target not in results:
            results.append(target)
        if len(results) >= limit:
            break
    return results


def ddg_search(query, limit=3):
    """Return up to `limit` result URLs for a query, best effort.

    The main HTML endpoint intermittently answers with a bot-check page
    (HTTP 202, no result links) or rate-limits repeat callers, so it is
    retried after a short pause and then topped up from the independent
    lite endpoint, which fails on a different schedule. Either endpoint
    alone returning nothing is common enough that callers should treat an
    empty result as "search unavailable", not "no such pages exist".
    """
    import time

    results = []
    for delay in (0, 2):
        if delay:
            time.sleep(delay)
        results = _endpoint_urls("https://html.duckduckgo.com/html/?q=",
                                 query, limit)
        if results:
            break
    if len(results) < limit:
        for url in _endpoint_urls("https://lite.duckduckgo.com/lite/?q=",
                                  query, limit):
            if url not in results:
                results.append(url)
            if len(results) >= limit:
                break
    return results


def parse_page_links_only(html):
    """Extract only search-result anchors (plus all anchors as fallback).

    The DDG HTML endpoint marks organic results with class 'result__a', the
    lite endpoint with class 'result-link'; both wrap the real URL in the
    'uddg' query parameter.
    """
    links = []
    for match in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>', html, re.IGNORECASE):
        tag = match.group(0)
        if "result__a" in tag or "result-link" in tag:
            links.append((match.group(1), ""))
    if links:
        return links
    parser = _PageParser()
    try:
        parser.feed(html)
    except Exception:
        return []
    return parser.links
