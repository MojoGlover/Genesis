"""
task_progress — Computer Black task progress bar component.

Tracks arbitrary tasks by polling a callable for completed units,
renders as a subtle inline bar in Gradio with pause/reorder controls.

Usage:
    from task_progress import TaskProgressBar, TaskQueue, render_queue

    queue = TaskQueue()
    queue.add("My task", projected=100, poll_fn=lambda: my_counter)

    # In Gradio:
    html = render_queue(queue)   # push into gr.HTML component on a timer

Demo:
    cd /Users/darnieglover/ai/GENESIS
    python3 -m task_progress.demo
"""
from .bar import TaskProgressBar, ProgressSnapshot
from .queue import TaskQueue
from .gradio_component import render_queue

__all__ = [
    "TaskProgressBar",
    "ProgressSnapshot",
    "TaskQueue",
    "render_queue",
]
