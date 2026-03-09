"""
ui/theme.py
The Computer Black Gradio theme — defines all cb-* token classes.

Usage in any Gradio app:
    from ui.theme import CB_CSS, cb_theme

    with gr.Blocks() as demo:
        ...

    demo.launch(css=CB_CSS, theme=cb_theme())

Panels import nothing from here. They only use class names from ui/tokens.py.
The host applies CB_CSS once and every panel inherits it automatically.
"""
import gradio as gr


# ── Raw CSS variables ─────────────────────────────────────────────────────────
# Changing a value here changes it everywhere across all panels.
_VARS = """
:root {
    --cb-void:       #050e14;
    --cb-panel:      #0f172a;
    --cb-raised:     #1e293b;
    --cb-border:     #1a3a4a;
    --cb-teal:       #00d4a0;
    --cb-indigo:     #6366f1;
    --cb-amber:      #f59e0b;
    --cb-red:        #ff4444;
    --cb-text-hi:    #f1f5f9;
    --cb-text-lo:    #94a3b8;
    --cb-muted:      #4a6a7a;
    --cb-font-mono:  'SF Mono', 'Fira Code', 'Consolas', monospace;
    --cb-font-ui:    'Inter', 'SF Pro Text', system-ui, sans-serif;
    --cb-radius:     6px;
    --cb-radius-lg:  10px;
}
"""

# ── Token class definitions ───────────────────────────────────────────────────
_TOKENS = """
/* ── Layout ── */
.cb-panel {
    background: var(--cb-panel);
    border: 1px solid var(--cb-border);
    border-radius: var(--cb-radius-lg);
    padding: 14px 16px;
}
.cb-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 10px;
}
.cb-col {
    display: flex;
    flex-direction: column;
    gap: 6px;
}
.cb-divider {
    border: none;
    border-top: 1px solid var(--cb-border);
    margin: 10px 0;
}

/* ── Text ── */
.cb-label  { color: var(--cb-text-lo);  font-size: 11px; font-weight: 600; letter-spacing: 0.6px; text-transform: uppercase; font-family: var(--cb-font-mono); }
.cb-value  { color: var(--cb-text-hi);  font-size: 13px; font-weight: 600; font-family: var(--cb-font-ui); }
.cb-muted  { color: var(--cb-muted);    font-size: 11px; font-family: var(--cb-font-mono); }
.cb-accent { color: var(--cb-teal);     font-size: 13px; font-weight: 700; font-family: var(--cb-font-mono); }
.cb-danger { color: var(--cb-red);      font-size: 12px; font-family: var(--cb-font-mono); }
.cb-code   { color: var(--cb-text-hi);  font-family: var(--cb-font-mono); font-size: 12px; }

/* ── Buttons ── */
.cb-btn {
    background: var(--cb-raised);
    border: 1px solid var(--cb-border);
    color: var(--cb-text-lo);
    border-radius: var(--cb-radius);
    padding: 4px 10px;
    cursor: pointer;
    font-size: 12px;
    font-family: var(--cb-font-ui);
    line-height: 20px;
    transition: background 0.15s, color 0.15s;
    user-select: none;
    white-space: nowrap;
}
.cb-btn:hover            { background: #2a4a5a; color: var(--cb-text-hi); }
.cb-btn-primary          { background: var(--cb-indigo); color: #fff; border-color: var(--cb-indigo); font-weight: 600; }
.cb-btn-primary:hover    { background: #4f52d4; }
.cb-btn-secondary        { background: transparent; }
.cb-btn-icon             { padding: 2px 7px; font-size: 11px; line-height: 18px; }
.cb-btn-active           { color: var(--cb-teal) !important; border-color: var(--cb-teal) !important; }

/* ── Status dots ── */
.cb-dot            { display: inline-block; width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.cb-dot--online    { background: var(--cb-teal);   box-shadow: 0 0 5px var(--cb-teal); }
.cb-dot--busy      { background: var(--cb-amber);  box-shadow: 0 0 5px var(--cb-amber); animation: cb-pulse 1s infinite; }
.cb-dot--offline   { background: var(--cb-red);    box-shadow: 0 0 4px var(--cb-red); }
.cb-dot--paused    { background: var(--cb-muted); }
@keyframes cb-pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }

/* ── Progress bar rows ── */
.cb-bar-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 12px;
    background: var(--cb-raised);
    border: 1px solid var(--cb-border);
    border-radius: var(--cb-radius);
    position: relative;
    overflow: hidden;
    min-height: 34px;
    font-family: var(--cb-font-mono);
    font-size: 12px;
}
.cb-bar-row--done { opacity: 0.45; }

.cb-bar-track {
    position: absolute;
    inset: 0;
    background: transparent;
    z-index: 0;
}
.cb-bar-fill {
    position: absolute;
    top: 0; left: 0; bottom: 0;
    background: var(--cb-teal);
    opacity: 0.15;
    z-index: 1;
    transition: width 0.7s ease;
}
.cb-bar-fill--paused { background: var(--cb-muted);  opacity: 0.10; }
.cb-bar-fill--done   { background: var(--cb-indigo); opacity: 0.18; }

.cb-bar-name     { position: relative; z-index: 2; color: var(--cb-text-hi); font-weight: 600; min-width: 150px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; letter-spacing: 0.2px; }
.cb-bar-name.cb-bar-name--paused { color: var(--cb-text-lo); }
.cb-bar-pct      { position: relative; z-index: 2; color: var(--cb-teal);    font-weight: 700; width: 40px; text-align: right; flex-shrink: 0; }
.cb-bar-pct.cb-bar-pct--paused { color: var(--cb-muted); }
.cb-bar-pct.cb-bar-pct--done   { color: var(--cb-indigo); }
.cb-bar-eta      { position: relative; z-index: 2; color: var(--cb-muted);   min-width: 72px; flex-shrink: 0; }
.cb-bar-controls { position: relative; z-index: 2; display: flex; gap: 4px; margin-left: auto; flex-shrink: 0; }

/* ── Empty state ── */
.cb-empty {
    color: var(--cb-muted);
    font-family: var(--cb-font-mono);
    font-size: 12px;
    text-align: center;
    padding: 16px;
    letter-spacing: 0.4px;
}

/* ── Queue container ── */
.cb-task-queue { display: flex; flex-direction: column; gap: 5px; }
"""

# ── Host-level overrides (page chrome, Gradio reset) ─────────────────────────
_HOST = """
footer { display: none !important; }
body, .gradio-container { background: var(--cb-void) !important; font-family: var(--cb-font-ui); }
.prose h1, .prose h2, .prose h3 { color: var(--cb-text-hi) !important; }
"""

CB_CSS: str = _VARS + _TOKENS + _HOST


def cb_theme() -> gr.themes.Base:
    """Gradio theme object — controls widget defaults to match CB palette."""
    return gr.themes.Base(
        primary_hue=gr.themes.colors.indigo,
        neutral_hue=gr.themes.colors.slate,
        font=gr.themes.GoogleFont("Inter"),
    ).set(
        body_background_fill      = "#050e14",
        body_background_fill_dark = "#050e14",
        block_background_fill     = "#0f172a",
        block_border_color        = "#1a3a4a",
        input_background_fill     = "#1e293b",
        input_border_color        = "#1a3a4a",
        button_primary_background_fill        = "#6366f1",
        button_primary_background_fill_hover  = "#4f52d4",
        button_secondary_background_fill      = "#1e293b",
        button_secondary_background_fill_hover= "#2a4a5a",
        button_secondary_border_color         = "#1a3a4a",
    )
