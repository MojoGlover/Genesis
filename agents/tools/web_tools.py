"""
Web Tools Module
Provides web search and URL fetching capabilities for the autonomous agent
"""

import logging
from typing import Dict, List, Any, Optional
from .tool_registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="web_search",
    description="Search the web using DuckDuckGo. Returns titles, snippets, and URLs.",
    category="web",
    examples=[
        "web_search('python async tutorial')",
        "web_search('latest news on AI', max_results=5)",
    ]
)
def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Search the web using DuckDuckGo

    Args:
        query: Search query string
        max_results: Maximum number of results (default 5)

    Returns:
        dict with 'success', 'results' list, and optional 'error'
    """
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r["title"],
                    "snippet": r["body"],
                    "url": r["href"],
                })

        return {
            "success": True,
            "query": query,
            "count": len(results),
            "results": results,
        }
    except ImportError:
        return {
            "success": False,
            "error": "ddgs not installed. Run: pip install ddgs",
        }
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="web_search_summarize",
    description="Search the web and return a formatted text summary of results.",
    category="web",
    examples=[
        "web_search_summarize('how to parse JSON in Python')",
    ]
)
def web_search_summarize(query: str, max_results: int = 3) -> Dict[str, Any]:
    """
    Search web and return a formatted summary string

    Args:
        query: Search query string
        max_results: Maximum number of results (default 3)

    Returns:
        dict with 'success' and 'output' (formatted text)
    """
    result = web_search(query, max_results)

    if not result.get("success"):
        return result

    results = result["results"]
    if not results:
        return {"success": True, "output": f"No results found for: {query}"}

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        lines.append(f"   {r['snippet']}")
        lines.append(f"   {r['url']}\n")

    return {"success": True, "output": "\n".join(lines)}


@register_tool(
    name="fetch_url",
    description="Fetch the content of a web page by URL. Returns the page text.",
    category="web",
    examples=[
        "fetch_url('https://example.com')",
        "fetch_url('https://api.github.com/repos/user/repo', headers={'Accept': 'application/json'})",
    ]
)
def fetch_url(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 15,
    max_length: int = 50000,
) -> Dict[str, Any]:
    """
    Fetch content from a URL

    Args:
        url: The URL to fetch
        headers: Optional HTTP headers
        timeout: Request timeout in seconds (default 15)
        max_length: Max characters to return (default 50000)

    Returns:
        dict with 'success', 'content', 'status_code', 'url', and optional 'error'
    """
    try:
        import httpx

        default_headers = {
            "User-Agent": "GENESIS-Agent/1.0 (autonomous AI assistant)",
        }
        if headers:
            default_headers.update(headers)

        resp = httpx.get(url, headers=default_headers, timeout=timeout, follow_redirects=True)

        content = resp.text
        truncated = False
        if len(content) > max_length:
            content = content[:max_length]
            truncated = True

        return {
            "success": resp.status_code < 400,
            "status_code": resp.status_code,
            "url": str(resp.url),
            "content_type": resp.headers.get("content-type", ""),
            "content": content,
            "truncated": truncated,
        }
    except ImportError:
        return {"success": False, "error": "httpx not installed. Run: pip install httpx"}
    except httpx.TimeoutException:
        return {"success": False, "error": f"Request timed out after {timeout}s", "url": url}
    except Exception as e:
        logger.error(f"Fetch URL error: {e}")
        return {"success": False, "error": str(e), "url": url}


@register_tool(
    name="fetch_json",
    description="Fetch a JSON API endpoint and return parsed data.",
    category="web",
    examples=[
        "fetch_json('https://api.github.com/repos/python/cpython')",
        "fetch_json('https://jsonplaceholder.typicode.com/posts/1')",
    ]
)
def fetch_json(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 15,
) -> Dict[str, Any]:
    """
    Fetch JSON from a URL and return parsed data

    Args:
        url: The API URL to fetch
        headers: Optional HTTP headers
        timeout: Request timeout in seconds (default 15)

    Returns:
        dict with 'success', 'data' (parsed JSON), 'status_code', and optional 'error'
    """
    try:
        import httpx

        default_headers = {
            "User-Agent": "GENESIS-Agent/1.0",
            "Accept": "application/json",
        }
        if headers:
            default_headers.update(headers)

        resp = httpx.get(url, headers=default_headers, timeout=timeout, follow_redirects=True)

        return {
            "success": resp.status_code < 400,
            "status_code": resp.status_code,
            "url": str(resp.url),
            "data": resp.json(),
        }
    except ImportError:
        return {"success": False, "error": "httpx not installed. Run: pip install httpx"}
    except Exception as e:
        logger.error(f"Fetch JSON error: {e}")
        return {"success": False, "error": str(e), "url": url}
