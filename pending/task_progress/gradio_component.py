"""
task_progress/gradio_component.py
Renders TaskQueue as HTML using only cb-* token classes.
No colors, fonts, or sizes live here — those belong to the host via ui/theme.py.
"""
from __future__ import annotations

import math
import sys
import os
from typing import Optional

# Allow import from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ui import tokens as t
from .bar import ProgressSnapshot
from .queue import TaskQueue


# ── JS bridge (host-agnostic — targets #cb-cmd-input by elem_id) ─────────────
_JS = """
<script>
(function() {
    if (window._cbWired) return;
    window._cbWired = true;
    function _cbPost(action, index, dir) {
        const box = document.getElementById('cb-cmd-input');
        if (!box) return;
        const nativeSet = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value');
        nativeSet.set.call(box, JSON.stringify({action, index, dir}));
        box.dispatchEvent(new Event('input', {bubbles: true}));
    }
    window.cbPause  = function(i)   { _cbPost('pause',  i, 0); };
    window.cbMove   = function(i,d) { _cbPost('move',   i, d); };
    window.cbRemove = function(i)   { _cbPost('remove', i, 0); };
})();
</script>
"""


def _fmt_eta(eta: Optional[float], done: bool, paused: bool) -> str:
    if done:   return "done"
    if paused: return "paused"
    if eta is None: return "…"
    if eta < 60:    return f"~{math.ceil(eta)}s"
    return f"~{math.ceil(eta/60)}m"


def _task_row(index: int, name: str, snap: ProgressSnapshot) -> str:
    pct_int = min(int(snap.pct * 100), 100)

    # Row class
    row_cls  = t.BAR_ROW_DONE if snap.done else t.BAR_ROW

    # Fill class
    if snap.done:    fill_cls = t.BAR_FILL_D
    elif snap.paused: fill_cls = t.BAR_FILL_P
    else:            fill_cls = t.BAR_FILL

    # Name class
    name_cls = f"{t.BAR_NAME} cb-bar-name--paused" if (snap.paused and not snap.done) else t.BAR_NAME

    # Pct class
    if snap.done:     pct_cls = f"{t.BAR_PCT} cb-bar-pct--done"
    elif snap.paused: pct_cls = f"{t.BAR_PCT} cb-bar-pct--paused"
    else:             pct_cls = t.BAR_PCT

    # Pause button
    pause_label = "▶" if snap.paused else "⏸"
    pause_cls   = t.BTN_ACTIVE if snap.paused else t.BTN_ICON

    eta_str = _fmt_eta(snap.eta_seconds, snap.done, snap.paused)

    return f"""
<div class="{row_cls}" data-index="{index}">
  <div class="{t.BAR_TRACK}"></div>
  <div class="{fill_cls}" style="width:{pct_int}%"></div>
  <span class="{name_cls}">{name}</span>
  <span class="{pct_cls}">{pct_int}%</span>
  <span class="{t.BAR_ETA}">{eta_str}</span>
  <div class="{t.BAR_CONTROLS}">
    <button class="{t.BTN_ICON}" onclick="cbMove({index},-1)" title="Move up">▲</button>
    <button class="{t.BTN_ICON}" onclick="cbMove({index}, 1)" title="Move down">▼</button>
    <button class="{pause_cls}" onclick="cbPause({index})"   title="Pause/Resume">{pause_label}</button>
    <button class="{t.BTN_ICON}" onclick="cbRemove({index})" title="Remove">✕</button>
  </div>
</div>"""


def render_queue(queue: TaskQueue) -> str:
    """
    Render the full task queue as an HTML string.
    Inject into a gr.HTML component on a timer tick.
    Host must have applied CB_CSS (from ui/theme.py) for styling.
    JS bridge wires button clicks to a hidden #cb-cmd-input textbox.
    """
    if len(queue) == 0:
        return f'<div class="cb-task-queue">{_JS}<div class="{t.EMPTY}">No active tasks</div></div>'

    rows = [_task_row(bar.position, bar.name, bar.tick()) for bar in queue.tasks()]
    return f'<div class="cb-task-queue">{_JS}{"".join(rows)}</div>'
