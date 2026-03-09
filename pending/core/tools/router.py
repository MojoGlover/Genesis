"""
Tool Router
Decides which tools to use based on the request
"""
from typing import Dict, Any, Optional
from .web_search import search_and_summarize
from .file_ops import read_file, write_file, list_files


def detect_and_route(prompt: str, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Detect if tools are needed and route accordingly
    
    Returns:
        Tool result if tool was used, None otherwise
    """
    prompt_lower = prompt.lower()
    
    # Web search detection
    if any(keyword in prompt_lower for keyword in ["search for", "look up", "find information about", "what is happening", "latest"]):
        # Extract search query
        query = prompt.replace("search for", "").replace("look up", "").replace("find information about", "").strip()
        results = search_and_summarize(query, max_results=3)
        return {
            "tool": "web_search",
            "query": query,
            "results": results
        }
    
    # File operations detection
    if "read file" in prompt_lower or "open file" in prompt_lower:
        words = prompt.split()
        if len(words) > 2:
            filepath = words[-1]
            content = read_file(filepath)
            return {
                "tool": "file_read",
                "filepath": filepath,
                "content": content
            }
    
    # No tool needed
    return None
