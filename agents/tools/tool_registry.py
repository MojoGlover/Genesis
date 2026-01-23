"""
Tool Registry - Central registry for all available tools
Allows AI to discover and understand its capabilities dynamically
"""

from typing import Dict, List, Any, Callable
import inspect


class Tool:
    """Represents a single tool with metadata"""
    
    def __init__(
        self,
        name: str,
        description: str,
        function: Callable,
        category: str = "general",
        examples: List[str] = None
    ):
        self.name = name
        self.description = description
        self.function = function
        self.category = category
        self.examples = examples or []
        
        # Auto-extract parameters from function signature
        self.parameters = self._extract_parameters()
    
    def _extract_parameters(self) -> Dict[str, Any]:
        """Extract parameter info from function signature"""
        sig = inspect.signature(self.function)
        params = {}
        
        for param_name, param in sig.parameters.items():
            params[param_name] = {
                'name': param_name,
                'type': param.annotation if param.annotation != inspect.Parameter.empty else 'Any',
                'default': param.default if param.default != inspect.Parameter.empty else None,
                'required': param.default == inspect.Parameter.empty
            }
        
        return params
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert tool to dictionary for easy display"""
        return {
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'parameters': self.parameters,
            'examples': self.examples
        }
    
    def __call__(self, *args, **kwargs):
        """Allow tool to be called directly"""
        return self.function(*args, **kwargs)


class ToolRegistry:
    """Central registry for all available tools"""
    
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self.categories: Dict[str, List[str]] = {}
    
    def register(
        self,
        name: str,
        description: str,
        function: Callable,
        category: str = "general",
        examples: List[str] = None
    ) -> Tool:
        """Register a new tool"""
        tool = Tool(name, description, function, category, examples)
        self.tools[name] = tool
        
        # Add to category index
        if category not in self.categories:
            self.categories[category] = []
        self.categories[category].append(name)
        
        return tool
    
    def get(self, name: str) -> Tool:
        """Get a tool by name"""
        return self.tools.get(name)
    
    def list_tools(self, category: str = None) -> List[Dict[str, Any]]:
        """List all available tools, optionally filtered by category"""
        if category:
            tool_names = self.categories.get(category, [])
            return [self.tools[name].to_dict() for name in tool_names]
        
        return [tool.to_dict() for tool in self.tools.values()]
    
    def list_categories(self) -> List[str]:
        """List all available categories"""
        return list(self.categories.keys())
    
    def get_tool_summary(self) -> str:
        """Get a human-readable summary of all tools"""
        lines = ["=== Available Tools ===\n"]
        
        for category in sorted(self.categories.keys()):
            lines.append(f"\n## {category.upper()}")
            for tool_name in self.categories[category]:
                tool = self.tools[tool_name]
                lines.append(f"  • {tool.name}: {tool.description}")
        
        lines.append(f"\n\nTotal: {len(self.tools)} tools across {len(self.categories)} categories")
        return "\n".join(lines)
    
    def execute(self, tool_name: str, *args, **kwargs) -> Any:
        """Execute a tool by name"""
        tool = self.get(tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found in registry")
        
        return tool(*args, **kwargs)


# Global registry instance
_registry = ToolRegistry()


def register_tool(
    name: str = None,
    description: str = None,
    category: str = "general",
    examples: List[str] = None
):
    """Decorator to register a function as a tool"""
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        tool_desc = description or func.__doc__ or "No description provided"
        
        _registry.register(
            name=tool_name,
            description=tool_desc,
            function=func,
            category=category,
            examples=examples
        )
        
        return func
    
    return decorator


def get_registry() -> ToolRegistry:
    """Get the global tool registry"""
    return _registry
