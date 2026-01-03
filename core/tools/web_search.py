"""
Web Search Tool
Uses DuckDuckGo for internet searches
"""
from duckduckgo_search import DDGS
from typing import List, Dict, Any


def search_web(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Search the web using DuckDuckGo
    
    Args:
        query: Search query string
        max_results: Maximum number of results to return
        
    Returns:
        List of search results with title, snippet, and URL
    """
    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r["title"],
                    "snippet": r["body"],
                    "url": r["href"]
                })
        return results
    except Exception as e:
        return [{"error": str(e)}]


def search_and_summarize(query: str, max_results: int = 3) -> str:
    """
    Search web and return formatted summary
    """
    results = search_web(query, max_results)
    
    if not results:
        return "No results found."
    
    summary = f"Search results for: {query}\n\n"
    for i, result in enumerate(results, 1):
        if "error" in result:
            return f"Search error: {result['error']}"
        summary += f"{i}. {result['title']}\n"
        summary += f"   {result['snippet']}\n"
        summary += f"   {result['url']}\n\n"
    
    return summary
