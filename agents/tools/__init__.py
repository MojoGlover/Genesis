"""
Tools Module - Initialization
Auto-imports all tool modules to register them with the registry
"""

from .tool_registry import get_registry, register_tool

# Import all tool modules to trigger registration
from . import file_ops
from . import code_executor
from . import package_manager
from . import workspace
from . import web_tools
from . import location_tools
from . import delivery_tools

# Export commonly used functions
__all__ = [
    'get_registry',
    'register_tool',
    'file_ops',
    'code_executor',
    'package_manager',
    'workspace',
    'web_tools',
    'location_tools',
]


def list_all_tools():
    """Convenience function to list all registered tools"""
    registry = get_registry()
    return registry.list_tools()


def get_tool_summary():
    """Convenience function to get tool summary"""
    registry = get_registry()
    return registry.get_tool_summary()


def list_categories():
    """Convenience function to list tool categories"""
    registry = get_registry()
    return registry.list_categories()
