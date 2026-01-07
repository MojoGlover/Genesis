"""
Workspace Tool - LangChain integration for AI workspace access
"""

from typing import Dict, Any, Optional
from core.workspace import workspace
import logging

logger = logging.getLogger(__name__)


class WorkspaceTool:
    """Tool for AI to interact with workspace"""
    
    def __init__(self):
        self.name = "workspace"
        self.description = """Use this tool to execute code, manage files, and build projects in a safe workspace environment.
        
Available actions:
- execute: Run shell commands
- write_file: Create/update files
- read_file: Read file contents
- list: List directory contents
- install: Install packages
- git_clone: Clone repositories

The workspace persists between sessions."""
    
    def execute_command(self, command: str, workdir: str = "/workspace") -> str:
        """Execute command in workspace"""
        result = workspace.execute(command, workdir)
        
        if result["success"]:
            return f"Command executed successfully:\n{result['stdout']}"
        else:
            return f"Command failed (exit code {result['exit_code']}):\n{result['stderr']}"
    
    def write_file(self, path: str, content: str) -> str:
        """Write file to workspace"""
        result = workspace.write_file(path, content)
        
        if result["success"]:
            return f"File written successfully: {path}"
        else:
            return f"Failed to write file: {result['error']}"
    
    def read_file(self, path: str) -> str:
        """Read file from workspace"""
        result = workspace.read_file(path)
        
        if result["success"]:
            return result["content"]
        else:
            return f"Failed to read file: {result['error']}"
    
    def list_directory(self, path: str = "/workspace") -> str:
        """List directory contents"""
        result = workspace.list_directory(path)
        
        if result["success"]:
            return result["listing"]
        else:
            return f"Failed to list directory: {result['error']}"
    
    def install_package(self, package: str, language: str = "python") -> str:
        """Install package"""
        result = workspace.install_package(package, language)
        
        if result["success"]:
            return f"Package '{package}' installed successfully"
        else:
            return f"Failed to install package: {result['error']}"
    
    def get_tool_definition(self) -> Dict[str, Any]:
        """Return tool definition for LangChain"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["execute", "write_file", "read_file", "list", "install", "git_clone"],
                        "description": "Action to perform"
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to execute (for 'execute' action)"
                    },
                    "path": {
                        "type": "string",
                        "description": "File/directory path"
                    },
                    "content": {
                        "type": "string",
                        "description": "File content (for 'write_file')"
                    },
                    "package": {
                        "type": "string",
                        "description": "Package name (for 'install')"
                    }
                },
                "required": ["action"]
            }
        }
