# tool_registry.py
# THE TOOL REGISTRY
#
# Responsibility:
#   Maintains the list of all tools available to this agent and provides
#   a lookup interface for executor.py to find and call tools by name.
#
# Expected contents:
#   - register(tool) — add a tool to the registry
#   - get(name) — retrieve a tool by name
#   - list_tools() — return all registered tools and their descriptions
#   - Auto-discovery of tools in this directory (optional)
#
# What does NOT belong here:
#   - Individual tool implementations (each tool gets its own file)
#   - Execution orchestration (that belongs in executor.py)
#   - One-off scripts or experiments (those go to pending/)
