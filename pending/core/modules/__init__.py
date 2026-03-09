"""
GENESIS Module System — drop-in capability registration.

Usage:
    from core.modules import ModuleBase, get_module_registry
"""

from .base import ModuleBase
from .registry import ModuleRegistry, get_module_registry

__all__ = [
    "ModuleBase",
    "ModuleRegistry",
    "get_module_registry",
]
