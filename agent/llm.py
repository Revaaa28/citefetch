"""Optional LLM verification hook.

If (and only if) LLM_BASE_URL and LLM_MODEL are set in the environment, the
top heuristic candidates are sent to any OpenAI-compatible chat endpoint to
pick the one that best answers the question. Every failure path returns None
and the deterministic heuristic ranking is used instead — the agent works
fully without an LLM.
"""
import json
import os
import urllib.request


def llm_configured():
    return bool(os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_MODEL"))


def rerank(query, candidates, top_n=5):
    """Return the index of the best candidate, or None to keep heuristics."""
    if not llm_configured() or len(candidates) < 2:
        return None
    base = os.environ["LLM_BASE_URL"].rstrip("/")
    model = os.environ["LLM_MODEL"]
    api_key = os.environ.get("LLM_API_KEY", "")
    lines = []
    for i, cand in enumerate(candidates[:top_n]):
        lines.append(f"{i}. value={cand.value!r} source={cand.source_url} "
                     f"evidence={cand.evidence!r}")
    prompt = (
        "Question: " + query + "\n\nCandidate answers extracted from web "
        "pages:\n" + "\n".join(lines) + "\n\nReply with ONLY the number of "
        "the candidate that best and most directly answers the question. "
        "If none answers it, reply -1."
    )
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You verify extracted answers."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        base + "/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        text = data["choices"][0]["message"]["content"].strip()
        idx = int("".join(ch for ch in text if ch.isdigit() or ch == "-"))
        if 0 <= idx < min(top_n, len(candidates)):
            return idx
    except Exception:
        return None
    return None
