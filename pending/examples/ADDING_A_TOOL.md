# Adding a Custom Tool to GENESIS

This guide shows you how to extend GENESIS with new capabilities by adding a custom tool.

## Overview

In this example, we'll add a **Web Search Tool** that can search the internet and return results. The same pattern works for any tool you want to add.

## Step 1: Create Your Tool File

Create a new file in `tools/custom_search.py`:

**Key components:**
- `__init__`: Configure the tool with API keys, settings
- `search()`: Main functionality 
- `get_tool_definition()`: LangChain/LLM integration format

## Step 2: Register the Tool

Add your tool to `core/tools.py` (create if it doesn't exist).

Create a ToolRegistry class that:
- Loads mission config
- Registers tools based on config
- Provides access to tools

## Step 3: Update Your Mission Config

Add tool configuration to `MISSION.md`:

**Tools Configuration**

Web Search:
- Enabled: Yes
- API Key: your_search_api_key_here
- Max Results: 5
- Purpose: Retrieve current information from the web

## Step 4: Use the Tool in Your Agent

Import ToolRegistry, get your tool, and use it in your agent logic.

## Step 5: Test Your Tool

Create tests to verify:
- Tool initialization
- Search functionality  
- Tool definition format

Run: `pytest tests/test_custom_search.py -v`

## File Structure After Adding Tool

GENESIS/
├── tools/custom_search.py (your new tool)
├── core/tools.py (tool registry)
├── tests/test_custom_search.py (tool tests)
├── MISSION.md (updated with tool config)
└── main.py (uses the tool)

## Integration with LangChain/LangGraph

Convert your tool to LangChain StructuredTool format and add to your agent.

## Best Practices

1. Keep tools focused - one tool, one job
2. Handle errors gracefully
3. Document parameters clearly
4. Make it configurable via MISSION.md
5. Write tests
6. Add logging

## Next Steps

You can add any tool following this pattern:
- Weather API
- Database queries
- File operations
- Custom APIs
- Data processing

**Key pattern:** Tool file → Registry → Mission config → Use in agent

Happy building! 🚀
