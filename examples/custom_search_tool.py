"""
Example Custom Tool: Web Search

This is a working example showing how to create a custom tool for GENESIS.
You can use this as a template for adding your own tools.
"""

from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class WebSearchTool:
    """Example custom tool for web searching."""
    
    def __init__(self, api_key: Optional[str] = None, max_results: int = 5):
        self.api_key = api_key
        self.max_results = max_results
        self.name = "web_search"
        self.description = "Search the web for current information on any topic"
        logger.info(f"WebSearchTool initialized (max_results={max_results})")
    
    def search(self, query: str, max_results: Optional[int] = None) -> Dict[str, Any]:
        """Search the web for information."""
        try:
            num_results = max_results or self.max_results
            logger.info(f"Searching for: '{query}' (max: {num_results})")
            
            # PLACEHOLDER: Replace with actual search API
            results = self._mock_search(query, num_results)
            
            return {
                "query": query,
                "results": results,
                "count": len(results),
                "status": "success"
            }
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {
                "query": query,
                "results": [],
                "count": 0,
                "status": "error",
                "message": str(e)
            }
    
    def _mock_search(self, query: str, max_results: int) -> List[Dict[str, str]]:
        """Mock search results - replace with real API."""
        return [
            {
                "title": f"Result {i+1} for '{query}'",
                "url": f"https://example.com/result-{i+1}",
                "snippet": f"Mock result about {query}. Replace with real API."
            }
            for i in range(min(max_results, 3))
        ]
    
    def get_tool_definition(self) -> Dict[str, Any]:
        """Return tool definition for LangChain/LLM integration."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"Max results (default: {self.max_results})",
                        "minimum": 1,
                        "maximum": 20
                    }
                },
                "required": ["query"]
            }
        }
    
    def format_results_for_llm(self, results: Dict[str, Any]) -> str:
        """Format search results for LLM consumption."""
        if results["status"] == "error":
            return f"Search failed: {results.get('message', 'Unknown error')}"
        
        if results["count"] == 0:
            return f"No results found for: {results['query']}"
        
        formatted = [f"Search results for '{results['query']}' ({results['count']} found):\n"]
        
        for i, result in enumerate(results["results"], 1):
            formatted.append(f"{i}. {result['title']}")
            formatted.append(f"   URL: {result['url']}")
            formatted.append(f"   {result['snippet']}\n")
        
        return "\n".join(formatted)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    search_tool = WebSearchTool(max_results=5)
    results = search_tool.search("latest AI developments")
    print(search_tool.format_results_for_llm(results))
    print("\nTool Definition:")
    print(search_tool.get_tool_definition())
