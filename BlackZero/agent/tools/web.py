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
    Search the web via DuckDuckGo instant answers API.
    For full web search, use shell: curl + grep or playwright.
    """
    logger.info(f"[web] Searching: {query}")
    encoded = urllib.parse.quote(query)
    url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1&no_html=1"
    try:
        result = fetch(url)
        if result["error"]:
            return {"query": query, "results": [], "error": result["error"]}

        data = json.loads(result["content"])
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

        return {"query": query, "results": results[:num_results], "error": None}
    except Exception as e:
        return {"query": query, "results": [], "error": str(e)}


def api_call(url: str, method: str = "GET", headers: dict | None = None,
             body: dict | str | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Make an HTTP API call. Supports GET and POST."""
    logger.info(f"[web] {method} {url}")
    try:
        data = None
        if body:
            if isinstance(body, dict):
                data = json.dumps(body).encode()
            else:
                data = body.encode()

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
