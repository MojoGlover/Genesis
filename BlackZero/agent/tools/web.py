"""
web.py — Web fetch and search tools for BlackZero agents.

Fetch URLs, search the web, scrape pages.
Used for research, API calls, documentation lookup.
"""
from __future__ import annotations

import logging
import urllib.request
import urllib.parse
import json
import re
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15
MAX_CONTENT_BYTES = 50_000


def fetch(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Fetch a URL and return its content."""
    logger.info(f"[web] Fetching {url}")
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ComputerBlack-Agent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_CONTENT_BYTES)
            content_type = resp.headers.get("content-type", "")

            if "json" in content_type:
                try:
                    text = json.dumps(json.loads(raw), indent=2)
                except Exception:
                    text = raw.decode("utf-8", errors="replace")
            else:
                text = raw.decode("utf-8", errors="replace")
                # Strip HTML tags for readability
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()

        return {"url": url, "content": text[:MAX_CONTENT_BYTES], "error": None}
    except Exception as e:
        logger.error(f"[web] Fetch failed: {e}")
        return {"url": url, "content": "", "error": str(e)}


def search(query: str, num_results: int = 5) -> dict:
    """
    Search the web, trying three no-key sources in order and returning
    whichever finds results first:

      1. DuckDuckGo HTML results — real organic results, but DDG puts a
         CAPTCHA ("anomaly") wall in front of automated/datacenter IPs, so
         this frequently comes back empty from a server. Not an error when
         that happens — just falls through to the next source.
      2. DuckDuckGo Instant Answer API — reliable but narrow: only fires for
         direct factual queries (definitions, conversions, infobox facts).
      3. Wikipedia search — reliable, no key, no bot-gating. Good for
         encyclopedic/topic queries, useless for anything time-sensitive.

    All three empty is a real "nothing found," not a tool failure — the
    caller should say so rather than invent an answer. There is no general,
    reliable, keyless web search API; a paid one (Brave/SerpAPI/Google) would
    close this gap for good but needs Darnie's go-ahead per the cloud API
    policy — this function does not add one on its own.
    """
    logger.info(f"[web] Searching: {query}")

    results = _ddg_html_search(query, num_results)
    if results:
        return {"query": query, "results": results, "error": None}

    results = _ddg_instant_answer(query, num_results)
    if results:
        return {"query": query, "results": results, "error": None}

    results = _wikipedia_search(query, num_results)
    if results:
        return {"query": query, "results": results, "error": None}

    return {"query": query, "results": [], "error": None}


def _strip_html_fragment(fragment: str) -> str:
    import html as _html
    return _html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _unwrap_ddg_redirect(href: str) -> str:
    """DDG HTML results link through /l/?uddg=<real-url>&... — unwrap it."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path == "/l/":
        real = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        if real:
            return urllib.parse.unquote(real)
    return href


def _ddg_html_search(query: str, num_results: int) -> list[dict]:
    """Scrape DuckDuckGo's HTML results page. Returns [] on any failure,
    including the CAPTCHA/anomaly challenge page — never raises."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; ComputerBlack-Agent/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            raw = resp.read(MAX_CONTENT_BYTES).decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"[web] DDG HTML search failed: {e}")
        return []

    if "anomaly-modal" in raw or "id=\"challenge-form\"" in raw:
        logger.info("[web] DDG HTML search hit the bot-check wall — falling through")
        return []

    link_re    = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_re = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
    links      = link_re.findall(raw)
    snippets   = snippet_re.findall(raw)

    results = []
    for i, (href, title_html) in enumerate(links):
        real_url = _unwrap_ddg_redirect(href)
        # Skip sponsored/ad results (duckduckgo.com/y.js) — not organic hits.
        if "duckduckgo.com/y.js" in real_url:
            continue
        title = _strip_html_fragment(title_html)
        snippet = _strip_html_fragment(snippets[i]) if i < len(snippets) else ""
        if title and real_url:
            results.append({"title": title, "url": real_url, "snippet": snippet})
        if len(results) >= num_results:
            break
    return results


def _ddg_instant_answer(query: str, num_results: int) -> list[dict]:
    """DuckDuckGo's instant-answer API — definitions/conversions/infoboxes only."""
    encoded = urllib.parse.quote(query)
    url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1&no_html=1"
    try:
        result = fetch(url)
        if result["error"]:
            return []
        data = json.loads(result["content"])
    except Exception as e:
        logger.warning(f"[web] DDG instant-answer search failed: {e}")
        return []

    results = []
    if data.get("AbstractText"):
        results.append({
            "title": data.get("Heading", ""),
            "url": data.get("AbstractURL", ""),
            "snippet": data["AbstractText"],
        })
    for r in data.get("RelatedTopics", [])[:num_results]:
        if "Text" in r:
            results.append({
                "title": r.get("Text", "")[:100],
                "url": r.get("FirstURL", ""),
                "snippet": r.get("Text", ""),
            })
    return results[:num_results]


def _wikipedia_search(query: str, num_results: int) -> list[dict]:
    """Wikipedia's public search API — reliable, no key, no bot-gating."""
    encoded = urllib.parse.quote(query)
    url = (f"https://en.wikipedia.org/w/api.php?action=query&list=search"
           f"&srsearch={encoded}&format=json&srlimit={num_results}")
    try:
        result = fetch(url)
        if result["error"]:
            return []
        data = json.loads(result["content"])
    except Exception as e:
        logger.warning(f"[web] Wikipedia search failed: {e}")
        return []

    results = []
    for r in data.get("query", {}).get("search", []):
        title = r.get("title", "")
        results.append({
            "title": title,
            "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
            "snippet": _strip_html_fragment(r.get("snippet", "")),
        })
    return results


def api_call(url: str, method: str = "GET", headers: dict | None = None,
             payload: dict | str | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Make an HTTP API call. Supports GET and POST.

    The request-body param is named `payload` to match the tool schema and
    TOOL_DOCS (registry.py). A previous mismatch (`body` here vs `payload` in
    the schema) made every POST/PUT with a body raise TypeError before sending.
    """
    logger.info(f"[web] {method} {url}")
    try:
        data = None
        if payload:
            if isinstance(payload, dict):
                data = json.dumps(payload).encode()
            else:
                data = payload.encode()

        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", "ComputerBlack-Agent/1.0")
        req.add_header("Content-Type", "application/json")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_CONTENT_BYTES)
            content = raw.decode("utf-8", errors="replace")
            try:
                content = json.dumps(json.loads(content), indent=2)
            except Exception:
                pass
            return {"url": url, "status": resp.status, "content": content, "error": None}
    except Exception as e:
        return {"url": url, "status": 0, "content": "", "error": str(e)}
