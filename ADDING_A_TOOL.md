# Adding a Custom Tool to GENESIS

This guide shows you how to extend GENESIS with new capabilities by adding a custom tool.

## Overview

In this example, we'll add a **Web Search Tool** that can search the internet and return results. The same pattern works for any tool you want to add.

## Step 1: Create Your Tool File

Create a new file in `tools/custom_search.py`:

```python
from typing import Dict, Any
import requests

class WebSearchTool:
    """Example custom tool for web searching"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.name = "web_search"
        self.description = "Search the web for current information"
    
    def search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        Search the web for information
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            
        Returns:
            Dict with search results
        """
        # Your implementation here
        # This is a placeholder - use your preferred search API
        return {
            "query": query,
            "results": [
                {"title": "Example Result", "url": "https://example.com", "snippet": "..."}
            ],
            "status": "success"
        }
    
    def get_tool_definition(self) -> Dict[str, Any]:
        """Return tool definition for LangChain/LangGraph integration"""
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
                        "description": "Maximum number of results (default: 5)"
                    }
                },
                "required": ["query"]
            }
        }
```

## Step 2: Register the Tool

Add your tool to `core/tools.py` (create if it doesn't exist):

```python
from tools.custom_search import WebSearchTool
from core.mission import load_mission

class ToolRegistry:
    """Central registry for all available tools"""
    
    def __init__(self):
        self.mission = load_mission()
        self.tools = {}
        self._register_default_tools()
        self._register_custom_tools()
    
    def _register_default_tools(self):
        """Register built-in tools"""
        # Built-in tools go here
        pass
    
    def _register_custom_tools(self):
        """Register custom tools based on mission config"""
        if self.mission.get("tools", {}).get("web_search", {}).get("enabled"):
            api_key = self.mission["tools"]["web_search"].get("api_key")
            self.tools["web_search"] = WebSearchTool(api_key=api_key)
    
    def get_tool(self, name: str):
        """Get a tool by name"""
        return self.tools.get(name)
    
    def get_all_tools(self):
        """Get all registered tools"""
        return self.tools
```

## Step 3: Update Your Mission Config

Add tool configuration to `MISSION.md`:

```markdown
## Tools Configuration

### Web Search
- **Enabled**: Yes
- **API Key**: your_search_api_key_here
- **Max Results**: 5
- **Purpose**: Retrieve current information from the web for research tasks
```

Or in mission.py, parse it as:

```python
"tools": {
    "web_search": {
        "enabled": True,
        "api_key": "your_api_key",
        "max_results": 5
    }
}
```

## Step 4: Use the Tool in Your Agent

In `main.py` or wherever your agent logic lives:

```python
from core.tools import ToolRegistry

# Initialize tools
registry = ToolRegistry()
web_search = registry.get_tool("web_search")

# Use in your agent
if web_search:
    results = web_search.search("latest AI developments")
    print(results)
```

## Step 5: Test Your Tool

Create `tests/test_custom_search.py`:

```python
import pytest
from tools.custom_search import WebSearchTool

def test_web_search_initialization():
    tool = WebSearchTool(api_key="test_key")
    assert tool.name == "web_search"
    assert tool.api_key == "test_key"

def test_web_search_query():
    tool = WebSearchTool()
    results = tool.search("test query")
    assert results["status"] == "success"
    assert "results" in results

def test_tool_definition():
    tool = WebSearchTool()
    definition = tool.get_tool_definition()
    assert definition["name"] == "web_search"
    assert "parameters" in definition
```

Run tests:
```bash
pytest tests/test_custom_search.py -v
```

## File Structure After Adding Tool

```
GENESIS/
├── tools/
│   └── custom_search.py          # Your new tool
├── core/
│   ├── mission.py                 # Reads mission config
│   └── tools.py                   # Tool registry
├── tests/
│   └── test_custom_search.py      # Tool tests
├── MISSION.md                     # Updated with tool config
└── main.py                        # Uses the tool
```

## Integration with LangChain/LangGraph

If you're using LangChain:

```python
from langchain.tools import StructuredTool

# Convert your tool to LangChain format
langchain_tool = StructuredTool.from_function(
    func=web_search.search,
    name=web_search.name,
    description=web_search.description,
    args_schema=web_search.get_tool_definition()
)

# Add to your agent
from langgraph.prebuilt import create_react_agent

agent = create_react_agent(
    model=llm,
    tools=[langchain_tool]
)
```

## Best Practices

1. **Keep tools focused** - One tool does one thing well
2. **Handle errors gracefully** - Return structured error responses
3. **Document parameters** - Clear descriptions for the LLM
4. **Make it configurable** - Use MISSION.md for settings
5. **Write tests** - Ensure reliability
6. **Add logging** - Track usage and debug issues

## Next Steps

You can now add any tool following this pattern:
- Weather API
- Database queries
- File operations
- Custom APIs
- Data processing

The key is: **Tool file → Registry → Mission config → Use in agent**

Happy building! 🚀
