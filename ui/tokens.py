"""
ui/tokens.py
Shared CSS class name contract for all Computer Black panels.

PANELS emit these class names. HOSTS define what they look like.
No panel ever hardcodes a color, font, or size.

Class contract
──────────────
Layout:
    cb-panel          container card / section
    cb-row            horizontal flex row
    cb-col            vertical flex column
    cb-divider        horizontal rule between sections

Text:
    cb-label          field label, secondary text
    cb-value          primary displayed value
    cb-muted          de-emphasized metadata
    cb-accent         highlighted / active value (teal by default)
    cb-danger         error or warning text
    cb-code           monospace text

Interactive:
    cb-btn            base button
    cb-btn-primary    primary action button
    cb-btn-secondary  secondary / ghost button
    cb-btn-icon       icon-only button (▲ ▼ ⏸ ✕)
    cb-btn-active     toggled-on state (e.g. paused)
    cb-input          text input

Status:
    cb-dot            inline status dot (●)
    cb-dot--online    green
    cb-dot--busy      amber
    cb-dot--offline   red
    cb-dot--paused    muted

Progress:
    cb-bar-row        one task row in a queue
    cb-bar-row--done  completed state
    cb-bar-track      full-width background track
    cb-bar-fill       filled portion
    cb-bar-fill--paused
    cb-bar-fill--done
    cb-bar-name       task name overlay
    cb-bar-pct        percentage label
    cb-bar-eta        ETA / time remaining label
    cb-bar-controls   button group on the right

Empty states:
    cb-empty          "nothing here" placeholder text
"""

# These are just the string constants — import and use them in HTML to
# avoid typos and make refactoring trivial.

PANEL         = "cb-panel"
ROW           = "cb-row"
COL           = "cb-col"
DIVIDER       = "cb-divider"

LABEL         = "cb-label"
VALUE         = "cb-value"
MUTED         = "cb-muted"
ACCENT        = "cb-accent"
DANGER        = "cb-danger"
CODE          = "cb-code"

BTN           = "cb-btn"
BTN_PRIMARY   = "cb-btn cb-btn-primary"
BTN_SECONDARY = "cb-btn cb-btn-secondary"
BTN_ICON      = "cb-btn cb-btn-icon"
BTN_ACTIVE    = "cb-btn cb-btn-icon cb-btn-active"
INPUT         = "cb-input"

DOT           = "cb-dot"
DOT_ONLINE    = "cb-dot cb-dot--online"
DOT_BUSY      = "cb-dot cb-dot--busy"
DOT_OFFLINE   = "cb-dot cb-dot--offline"
DOT_PAUSED    = "cb-dot cb-dot--paused"

BAR_ROW       = "cb-bar-row"
BAR_ROW_DONE  = "cb-bar-row cb-bar-row--done"
BAR_TRACK     = "cb-bar-track"
BAR_FILL      = "cb-bar-fill"
BAR_FILL_P    = "cb-bar-fill cb-bar-fill--paused"
BAR_FILL_D    = "cb-bar-fill cb-bar-fill--done"
BAR_NAME      = "cb-bar-name"
BAR_PCT       = "cb-bar-pct"
BAR_ETA       = "cb-bar-eta"
BAR_CONTROLS  = "cb-bar-controls"

EMPTY         = "cb-empty"
