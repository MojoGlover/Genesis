"""
ui — Computer Black shared UI layer.

    from ui.theme  import CB_CSS, cb_theme
    from ui.tokens import BAR_ROW, LABEL, ACCENT   # etc.

Panels use token class names from ui.tokens.
Hosts apply CB_CSS + cb_theme() once at launch.
"""
from .theme  import CB_CSS, cb_theme
from .tokens import *  # noqa: F401,F403 — re-export all token constants

__all__ = ["CB_CSS", "cb_theme"]
