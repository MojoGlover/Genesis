"""
GENESIS Builder — The Agent Factory Core.

Pipeline: propose → forge → test → export (PlugOps) or realize (self-sufficient) → export (Botico)
"""

from .builder import Builder, BuildError
from .realizer import Realizer, RealizationError

__all__ = ["Builder", "BuildError", "Realizer", "RealizationError"]
