# base_tool.py
# THE BASE TOOL INTERFACE
#
# Responsibility:
#   Defines the contract that every tool must implement.
#   All tools in this registry must inherit from or conform to this interface.
#
# Expected contents:
#   - BaseTool abstract class or protocol with:
#       name        — unique tool identifier (string)
#       description — what the tool does (used by planner and registry)
#       run(input)  — executes the tool and returns a result
#   - Input/output type definitions
#   - Optional: schema validation for tool inputs
#
# What does NOT belong here:
#   - Specific tool implementations (each gets its own file)
#   - Registry logic (that belongs in tool_registry.py)
