"""
Tool Executor - Executes actions using available tools
Registers 5 Docker workspace tools + 27 local tools from agents/tools registry
"""

import logging
from typing import Dict, Any, List, Optional

from tools.workspace_tool import WorkspaceTool

logger = logging.getLogger(__name__)

# Workspace tool descriptions (not in the registry)
WORKSPACE_TOOL_DESCRIPTIONS = {
    "workspace_execute": "Run shell commands in Docker sandbox",
    "workspace_write": "Write files inside Docker workspace",
    "workspace_read": "Read files from Docker workspace",
    "workspace_list": "List directory contents in Docker workspace",
    "workspace_install": "Install packages inside Docker workspace",
}


class ToolExecutor:
    """Executes actions using registered tools"""

    def __init__(self):
        self.tools = {}
        self._descriptions = {}
        self._register_tools()
        logger.info(f"ToolExecutor initialized with {len(self.tools)} tools")

    def _register_tools(self):
        """Register all available tools"""
        # 1. Register Docker workspace tools (sandboxed execution)
        workspace_tool = WorkspaceTool()
        self.tools["workspace_execute"] = workspace_tool.execute_command
        self.tools["workspace_write"] = workspace_tool.write_file
        self.tools["workspace_read"] = workspace_tool.read_file
        self.tools["workspace_list"] = workspace_tool.list_directory
        self.tools["workspace_install"] = workspace_tool.install_package
        self._descriptions.update(WORKSPACE_TOOL_DESCRIPTIONS)

        workspace_count = len(self.tools)

        # 2. Register all tools from agents/tools registry (local execution)
        registry_count = 0
        try:
            from agents.tools import get_registry
            registry = get_registry()
            for tool in registry.tools.values():
                if tool.name not in self.tools:
                    self.tools[tool.name] = tool.function
                    self._descriptions[tool.name] = tool.description
                    registry_count += 1
                else:
                    logger.debug(f"Skipping registry tool '{tool.name}' - workspace tool takes priority")
        except Exception as e:
            logger.warning(f"Could not load tool registry: {e}")

        logger.info(
            f"Registered {len(self.tools)} tools "
            f"({workspace_count} workspace + {registry_count} registry)"
        )

    def get_available_tools(self) -> List[str]:
        """Get list of available tool names"""
        return list(self.tools.keys())

    def get_tool_descriptions(self) -> Dict[str, str]:
        """Get {name: description} for all registered tools"""
        return dict(self._descriptions)
    
    def execute(
        self,
        action: str,
        parameters: Dict[str, Any],
        context: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute an action using appropriate tool
        
        Args:
            action: Action/tool name to execute
            parameters: Parameters for the action
            context: Previous execution history for context
            
        Returns:
            Dict with success status and results
        """
        logger.info(f"Executing action: {action}")
        
        if action not in self.tools:
            error_msg = f"Unknown action: {action}. Available: {list(self.tools.keys())}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "output": None
            }
        
        try:
            # Get the tool function
            tool_func = self.tools[action]
            
            # Handle parameter name variations (LLMs might use different names)
            # GPT-4 sometimes uses 'code' instead of 'command'
            if action == "workspace_execute":
                if "code" in parameters and "command" not in parameters:
                    parameters["command"] = parameters.pop("code")
                elif "script" in parameters and "command" not in parameters:
                    parameters["command"] = parameters.pop("script")
            
            # Handle 'content' vs 'text' for file writing
            if action == "workspace_write":
                if "text" in parameters and "content" not in parameters:
                    parameters["content"] = parameters.pop("text")
            
            # Handle 'packages' vs 'package' for installation
            if action == "workspace_install":
                if "packages" in parameters and "package" not in parameters:
                    # If multiple packages, install first one
                    packages = parameters.pop("packages")
                    if isinstance(packages, list):
                        parameters["package"] = packages[0]
                    else:
                        parameters["package"] = packages
            
            # Execute with parameters
            result = tool_func(**parameters)
            
            # Format result
            if isinstance(result, str):
                # String result from tool
                return {
                    "success": True,
                    "output": result,
                    "error": None
                }
            elif isinstance(result, dict):
                # Dict result - check if it has success flag
                return {
                    "success": result.get("success", True),
                    "output": result.get("output", result),
                    "error": result.get("error")
                }
            else:
                # Other result type
                return {
                    "success": True,
                    "output": str(result),
                    "error": None
                }
                
        except Exception as e:
            error_msg = f"Execution failed: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "output": None
            }
