"""Deterministic recurring work.

Code does the doing; the model only judges results it was handed, and is never
asked whether to look. See docs/DUTIES.md.
"""
from .runner import Duty, load_duties, overdue, run_duty  # noqa: F401
