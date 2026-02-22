"""
task_progress/demo.py
Standalone Gradio demo — run to test the progress bar component.

    cd /Users/darnieglover/ai/GENESIS
    python3 -m task_progress.demo
"""
from __future__ import annotations

import json
import math
import random
import time
import threading

import gradio as gr
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ui.theme import CB_CSS, cb_theme

from .queue import TaskQueue
from .gradio_component import render_queue

# ── Shared queue (module-level, lives for the session) ─────────────────────
_queue = TaskQueue()
_lock  = threading.Lock()

# ── Fake workloads for demo tasks ──────────────────────────────────────────

def _make_linear_poll(total: float, duration_s: float):
    """Simulates a task that progresses linearly over duration_s seconds."""
    start = time.monotonic()
    def poll() -> float:
        elapsed = time.monotonic() - start
        return min(total * (elapsed / duration_s), total)
    return poll

def _make_bursty_poll(total: float, duration_s: float):
    """Simulates a task that progresses in irregular bursts (like an LLM)."""
    start = time.monotonic()
    _state = {"completed": 0.0, "last_burst": start}
    def poll() -> float:
        now = time.monotonic()
        elapsed = now - start
        if elapsed >= duration_s:
            _state["completed"] = total
            return total
        # random burst every 1-3s
        if now - _state["last_burst"] > random.uniform(1, 3):
            increment = random.uniform(total * 0.05, total * 0.2)
            _state["completed"] = min(_state["completed"] + increment, total * (elapsed / duration_s) * 1.1)
            _state["last_burst"] = now
        return _state["completed"]
    return poll

def _make_stalling_poll(total: float, duration_s: float):
    """Simulates a task that stalls partway through then resumes."""
    start = time.monotonic()
    stall_start = duration_s * 0.4
    stall_end   = duration_s * 0.65
    def poll() -> float:
        elapsed = time.monotonic() - start
        if elapsed < stall_start:
            return total * (elapsed / stall_start) * 0.4
        if elapsed < stall_end:
            return total * 0.4   # stalled
        remaining = elapsed - stall_end
        total_remaining_time = duration_s - stall_end
        return min(total * 0.4 + total * 0.6 * (remaining / total_remaining_time), total)
    return poll


# ── Preset tasks ────────────────────────────────────────────────────────────
_PRESETS = {
    "LLM Inference (100 tokens)":     lambda: _make_bursty_poll(100,  20),
    "File Indexing (500 steps)":      lambda: _make_linear_poll(500,  30),
    "Model Download (2 GB)":          lambda: _make_linear_poll(2000, 45),
    "Embedding batch (1000 chunks)":  lambda: _make_stalling_poll(1000, 40),
    "Build + Deploy (5 steps)":       lambda: _make_linear_poll(5,    25),
}


# ── Gradio event handlers ───────────────────────────────────────────────────

def add_task(name: str, projected: float, poll_type: str) -> tuple[str, str]:
    """Add a task to the queue. Returns updated HTML + status message."""
    with _lock:
        factory = _PRESETS.get(poll_type, list(_PRESETS.values())[0])
        _queue.add(
            name=name or poll_type,
            projected=projected,
            poll_fn=factory(),
            poll_interval_s=0.5,
        )
    return render_queue(_queue), f"Added: {name or poll_type}"


def handle_command(cmd_json: str) -> tuple[str, str]:
    """Handle pause/move/remove commands from the JS buttons."""
    if not cmd_json or not cmd_json.strip():
        return render_queue(_queue), ""
    try:
        cmd = json.loads(cmd_json)
        action = cmd.get("action")
        index  = int(cmd.get("index", 0))
        with _lock:
            if action == "pause":
                if 0 <= index < len(_queue):
                    _queue[index].toggle_pause()
            elif action == "move":
                direction = int(cmd.get("dir", 0))
                if direction < 0:
                    _queue.move_up(index)
                elif direction > 0:
                    _queue.move_down(index)
            elif action == "remove":
                _queue.remove(index)
        return render_queue(_queue), ""
    except Exception as e:
        return render_queue(_queue), f"cmd error: {e}"


def poll_tick() -> str:
    """Called by gr.Timer every second — returns fresh HTML."""
    with _lock:
        return render_queue(_queue)


def clear_done() -> tuple[str, str]:
    with _lock:
        _queue.remove_done()
    return render_queue(_queue), "Cleared completed tasks"


# ── UI ──────────────────────────────────────────────────────────────────────
# No colors here — CB_CSS from ui/theme.py owns all styling.
# One extra rule to hide the cmd input from the layout.
_DEMO_EXTRA = "#cb-cmd-input { display: none !important; }"


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="CB Task Progress") as demo:

        gr.Markdown(
            "## Task Queue\n*Computer Black — progress bar component demo*",
            elem_classes=["panel"],
        )

        # ── Live queue display ───────────────────────────────────────────────
        queue_html = gr.HTML(
            value=render_queue(_queue),
            label="",
        )

        # Hidden command input — JS writes here, Python reads on change
        cmd_input = gr.Textbox(
            value="",
            elem_id="cb-cmd-input",
            visible=False,
            label="",
        )
        status_msg = gr.Markdown("", elem_id="status-msg")

        # ── Add task panel ───────────────────────────────────────────────────
        with gr.Row(elem_classes=["panel"]):
            with gr.Column(scale=3):
                task_name = gr.Textbox(
                    label="Task name",
                    placeholder="e.g. Summarise documents",
                    max_lines=1,
                )
            with gr.Column(scale=2):
                task_projected = gr.Number(
                    label="Projected workload",
                    value=100,
                    minimum=1,
                )
            with gr.Column(scale=3):
                task_type = gr.Dropdown(
                    label="Simulate as",
                    choices=list(_PRESETS.keys()),
                    value=list(_PRESETS.keys())[0],
                )

        with gr.Row():
            add_btn   = gr.Button("Add Task",        variant="primary")
            clear_btn = gr.Button("Clear Completed", variant="secondary")

        # ── Timer — polls every second ───────────────────────────────────────
        timer = gr.Timer(value=1.0)

        # ── Event wiring ─────────────────────────────────────────────────────
        timer.tick(
            fn=poll_tick,
            outputs=[queue_html],
        )

        add_btn.click(
            fn=add_task,
            inputs=[task_name, task_projected, task_type],
            outputs=[queue_html, status_msg],
        )

        clear_btn.click(
            fn=clear_done,
            outputs=[queue_html, status_msg],
        )

        # JS button → hidden textbox → Python handler
        cmd_input.change(
            fn=handle_command,
            inputs=[cmd_input],
            outputs=[queue_html, status_msg],
        )

    return demo


def main() -> None:
    demo = build_demo()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7862,
        css=CB_CSS + _DEMO_EXTRA,
        theme=cb_theme(),
    )


if __name__ == "__main__":
    main()
