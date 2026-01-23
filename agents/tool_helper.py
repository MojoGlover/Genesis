"""
Tool Helper for EngineerAgent
Provides easy access to tools for the agent to use during execution
"""

import sys
from pathlib import Path

# Add parent directory to path to import tools
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.tools import get_registry, get_tool_summary, list_categories


class ToolHelper:
    """Helper class to make tools easily accessible to the agent"""
    
    def __init__(self):
        self.registry = get_registry()
    
    def discover_tools(self) -> str:
        """Get a summary of all available tools"""
        return get_tool_summary()
    
    def list_categories(self) -> list:
        """List all tool categories"""
        return list_categories()
    
    def list_tools(self, category: str = None) -> list:
        """List tools, optionally filtered by category"""
        return self.registry.list_tools(category=category)
    
    def use_tool(self, tool_name: str, **kwargs):
        """Execute a tool by name with given parameters"""
        return self.registry.execute(tool_name, **kwargs)
    
    # Convenience methods for common operations
    
    def read_file(self, filepath: str):
        """Read a file"""
        return self.use_tool('read_file', filepath=filepath)
    
    def write_file(self, filepath: str, content: str):
        """Write a file"""
        return self.use_tool('write_file', filepath=filepath, content=content)
    
    def execute_code(self, code: str, timeout: int = 30):
        """Execute Python code"""
        return self.use_tool('execute_python', code=code, timeout=timeout)
    
    def execute_file(self, filepath: str, timeout: int = 30):
        """Execute a Python file"""
        return self.use_tool('execute_file', filepath=filepath, timeout=timeout)
    
    def install_package(self, package: str):
        """Install a Python package"""
        return self.use_tool('install_package', package=package)
    
    def check_missing_packages(self, code: str):
        """Check which packages are missing for given code"""
        return self.use_tool('check_missing_packages', code=code)
    
    def auto_install_dependencies(self, code: str):
        """Auto-install missing dependencies"""
        return self.use_tool('auto_install_dependencies', code=code)
    
    def save_to_workspace(self, filename: str, content: str):
        """Save file to workspace"""
        return self.use_tool('save_to_workspace', filename=filename, content=content)
    
    def read_from_workspace(self, filename: str):
        """Read file from workspace"""
        return self.use_tool('read_from_workspace', filename=filename)
    
    def list_workspace(self, pattern: str = "*"):
        """List workspace contents"""
        return self.use_tool('list_workspace', pattern=pattern)
    
    def init_workspace(self, clean: bool = False):
        """Initialize workspace"""
        return self.use_tool('init_workspace', clean=clean)
    
    def parse_error(self, error_text: str):
        """Parse error message"""
        return self.use_tool('parse_error', error_text=error_text)
    
    def validate_syntax(self, code: str):
        """Validate Python syntax"""
        return self.use_tool('validate_syntax', code=code)
    
    def run_shell_command(self, command: str, timeout: int = 30):
        """Run shell command"""
        return self.use_tool('run_shell_command', command=command, timeout=timeout)


# Global helper instance
_helper = None


def get_tool_helper() -> ToolHelper:
    """Get the global tool helper instance"""
    global _helper
    if _helper is None:
        _helper = ToolHelper()
    return _helper


# Quick access functions
def discover_tools() -> str:
    """Quick access to tool discovery"""
    return get_tool_helper().discover_tools()


def use_tool(tool_name: str, **kwargs):
    """Quick access to tool execution"""
    return get_tool_helper().use_tool(tool_name, **kwargs)


if __name__ == '__main__':
    # Test the helper
    helper = get_tool_helper()
    
    print("=== Tool Discovery ===")
    print(helper.discover_tools())
    
    print("\n=== Test File Operations ===")
    result = helper.write_file('/tmp/test_helper.py', 'print("Hello from ToolHelper!")')
    print(f"Write: {result}")
    
    result = helper.execute_file('/tmp/test_helper.py')
    print(f"Execute: {result}")
