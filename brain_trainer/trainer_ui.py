#!/usr/bin/env python3
"""
BlackZero Training Data Editor
A Gradio UI for curating training examples before fine-tuning.

Run: python trainer_ui.py
Opens at: http://localhost:7861
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import gradio as gr
from brain_trainer.data_manager import DataManager
from brain_trainer.data_generator import DataGenerator

# Default path
DATA_PATH = "~/ai/GENESIS/brain_trainer/training_data/blackzero.jsonl"

# Global manager instance
manager = DataManager(DATA_PATH)

# ── Styles ───────────────────────────────────────────────────────────────────
CSS = """
body { background: #0d0d0d !important; color: #e8e8e8 !important; }
.gradio-container { max-width: 1100px !important; margin: 0 auto !important; background: #0d0d0d !important; }
footer { display: none !important; }
h1, h2, h3, label { color: #00ff88 !important; }
.tab-nav button { background: #1a1a1a !important; color: #888 !important; border: 1px solid #2a2a2a !important; }
.tab-nav button.selected { color: #00ff88 !important; border-bottom: 2px solid #00ff88 !important; }
textarea, input[type=text] {
    background: #111 !important; color: #e8e8e8 !important;
    border: 1px solid #2a2a2a !important; border-radius: 8px !important;
}
.gr-button { border-radius: 8px !important; font-weight: 600 !important; }
.gr-button.primary { background: #00ff88 !important; color: #000 !important; }
.gr-button.secondary { background: #1a1a1a !important; color: #e8e8e8 !important; border: 1px solid #2a2a2a !important; }
.gr-button.stop { background: #ff4444 !important; color: #fff !important; }
"""

# ── Helper functions ──────────────────────────────────────────────────────────

def get_stats_md():
    s = manager.stats()
    return (
        f"**Total:** {s['total']}  |  "
        f"**✅ Approved:** {s['approved']}  |  "
        f"**⏳ Pending:** {s['pending']}  |  "
        f"**Sources:** {', '.join(f'{k}: {v}' for k,v in s['by_source'].items())}"
    )

def refresh_table():
    return manager.as_table(), get_stats_md()

def load_sample(index_str: str):
    """Load a sample into the editor by index."""
    try:
        idx = int(str(index_str).strip())
    except (ValueError, TypeError):
        return "", "", "⚠️ Enter a valid index number"
    sample = manager.get(idx)
    if sample is None:
        return "", "", f"⚠️ No sample at index {idx}"
    status = "✅ Approved" if sample.approved else "⏳ Pending"
    return sample.user, sample.assistant, f"Loaded #{idx} ({sample.source}) — {status}"

def save_sample(index_str: str, user: str, assistant: str, approve: bool):
    """Save edits to an existing sample or add new."""
    user = user.strip()
    assistant = assistant.strip()
    if not user or not assistant:
        return *refresh_table(), "⚠️ Both fields required"
    try:
        idx = int(str(index_str).strip())
        manager.update(idx, user, assistant, approved=approve)
        msg = f"✅ Updated #{idx}"
    except (ValueError, TypeError):
        idx = manager.add(user, assistant, source="manual", approved=approve)
        msg = f"✅ Added as #{idx}"
    return *refresh_table(), msg

def add_new(user: str, assistant: str, approve: bool):
    """Add a brand new sample."""
    user = user.strip()
    assistant = assistant.strip()
    if not user or not assistant:
        return *refresh_table(), "⚠️ Both fields required"
    idx = manager.add(user, assistant, source="manual", approved=approve)
    return *refresh_table(), f"✅ Added #{idx}"

def delete_sample(index_str: str):
    try:
        idx = int(str(index_str).strip())
        manager.delete(idx)
        return *refresh_table(), f"🗑️ Deleted #{idx}"
    except (ValueError, TypeError):
        return *refresh_table(), "⚠️ Invalid index"

def approve_sample(index_str: str):
    try:
        idx = int(str(index_str).strip())
        manager.approve(idx, True)
        return *refresh_table(), f"✅ Approved #{idx}"
    except (ValueError, TypeError):
        return *refresh_table(), "⚠️ Invalid index"

def reject_sample(index_str: str):
    try:
        idx = int(str(index_str).strip())
        manager.approve(idx, False)
        return *refresh_table(), f"❌ Rejected #{idx}"
    except (ValueError, TypeError):
        return *refresh_table(), "⚠️ Invalid index"

def approve_all():
    manager.approve_all()
    return *refresh_table(), f"✅ All {manager.stats()['total']} samples approved"

def generate_more(count: int):
    """Generate more synthetic samples and add them."""
    try:
        from train import BLACKZERO_PERSONA as BZP
        persona = BZP
    except Exception:
        from brain_trainer.data_generator import DataGenerator
        from brain_trainer.config import PersonaConfig
        persona = PersonaConfig()

    gen = DataGenerator(persona=persona)
    new_samples = gen.generate_base()
    added = 0
    for s_data in new_samples[:count]:
        msgs = s_data.get("messages", [])
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        asst = next((m["content"] for m in msgs if m["role"] == "assistant"), "")
        if user and asst:
            manager.add(user, asst, source="synthetic", approved=False)
            added += 1
    return *refresh_table(), f"🔄 Generated {added} new samples (marked as pending — review & approve)"

def export_training_data(approved_only: bool):
    """Export clean JSONL for training."""
    out = manager.export_for_training(approved_only=approved_only)
    total = manager.stats()['approved' if approved_only else 'total']
    return *refresh_table(), f"📦 Exported {total} samples → {out}"

def preview_sample(index_str: str):
    """Show full content of a sample."""
    try:
        idx = int(str(index_str).strip())
        s = manager.get(idx)
        if not s:
            return "No sample found"
        return (
            f"**Index:** {idx}\n"
            f"**Source:** {s.source}\n"
            f"**Approved:** {'✅' if s.approved else '⏳'}\n"
            f"**Created:** {s.created_at[:19]}\n\n"
            f"---\n\n"
            f"**User:**\n{s.user}\n\n"
            f"**Assistant:**\n{s.assistant}"
        )
    except (ValueError, TypeError):
        return "Enter a valid index"

# ── Build UI ──────────────────────────────────────────────────────────────────

def create_ui():
    with gr.Blocks(title="BlackZero Training Editor", css=CSS) as demo:

        gr.Markdown("# ⚡ BlackZero Training Data Editor")
        stats_md = gr.Markdown(get_stats_md())

        with gr.Tabs():

            # ── Tab 1: Browse & Approve ──────────────────────────────────────
            with gr.Tab("📋 Browse & Approve"):
                gr.Markdown("Review all samples. Approve the ones you want in the next training run.")

                table = gr.Dataframe(
                    value=manager.as_table(),
                    headers=["#", "Status", "Source", "User (preview)", "Assistant (preview)"],
                    datatype=["number", "str", "str", "str", "str"],
                    interactive=False,
                    wrap=True,
                    row_count=(20, "dynamic"),
                )

                with gr.Row():
                    idx_browse = gr.Textbox(label="Index #", placeholder="0", scale=1)
                    btn_load   = gr.Button("📂 Load into Editor", variant="secondary", scale=2)
                    btn_approve = gr.Button("✅ Approve", variant="primary", scale=1)
                    btn_reject  = gr.Button("❌ Reject", elem_classes=["stop"], scale=1)
                    btn_delete  = gr.Button("🗑️ Delete", variant="secondary", scale=1)

                with gr.Row():
                    btn_approve_all = gr.Button("✅ Approve All", variant="primary")
                    btn_refresh     = gr.Button("🔄 Refresh", variant="secondary")

                preview_box = gr.Markdown("← Select an index and click Load to preview")
                status_browse = gr.Markdown("")

                btn_refresh.click(refresh_table, outputs=[table, stats_md])
                btn_approve_all.click(approve_all, outputs=[table, stats_md, status_browse])
                btn_approve.click(approve_sample, inputs=[idx_browse], outputs=[table, stats_md, status_browse])
                btn_reject.click(reject_sample, inputs=[idx_browse], outputs=[table, stats_md, status_browse])
                btn_delete.click(delete_sample, inputs=[idx_browse], outputs=[table, stats_md, status_browse])
                btn_load.click(
                    fn=lambda i: (*load_sample(i), preview_sample(i)),
                    inputs=[idx_browse],
                    outputs=[gr.Textbox(visible=False), gr.Textbox(visible=False), status_browse, preview_box]
                )

            # ── Tab 2: Write / Edit ──────────────────────────────────────────
            with gr.Tab("✍️ Write & Edit"):
                gr.Markdown(
                    "Write your own training examples here. "
                    "These carry the most weight in training — write them in the exact voice you want."
                )

                with gr.Row():
                    edit_index = gr.Textbox(
                        label="Index # (leave blank to add new)",
                        placeholder="blank = new sample",
                        scale=1
                    )
                    btn_load_edit = gr.Button("📂 Load", variant="secondary", scale=1)

                with gr.Row():
                    user_box = gr.Textbox(
                        label="👤 User message",
                        placeholder="What Kris says...",
                        lines=4,
                        scale=1
                    )
                    asst_box = gr.Textbox(
                        label="⚡ BlackZero response",
                        placeholder="Exactly how you want her to respond...",
                        lines=4,
                        scale=1
                    )

                with gr.Row():
                    auto_approve = gr.Checkbox(label="Mark as approved", value=True)
                    btn_save = gr.Button("💾 Save", variant="primary")
                    btn_clear = gr.Button("🗑️ Clear", variant="secondary")

                status_edit = gr.Markdown("")

                # Quick-write shortcuts
                gr.Markdown("### Quick Templates")
                gr.Markdown("Click to pre-fill common response patterns:")

                with gr.Row():
                    btn_tpl_identity = gr.Button("Identity Q&A", variant="secondary", size="sm")
                    btn_tpl_code     = gr.Button("Code task", variant="secondary", size="sm")
                    btn_tpl_refusal  = gr.Button("No-refusal", variant="secondary", size="sm")
                    btn_tpl_short    = gr.Button("Short answer", variant="secondary", size="sm")
                    btn_tpl_convo    = gr.Button("Multi-turn feel", variant="secondary", size="sm")

                btn_tpl_identity.click(
                    fn=lambda: ("who are you?", "BlackZero. Engineer0. Built by Kris Glover at Computer Black. I run locally on your hardware. What do you need?"),
                    outputs=[user_box, asst_box]
                )
                btn_tpl_code.click(
                    fn=lambda: ("write a python function that [does X]", "```python\ndef do_x():\n    pass\n```"),
                    outputs=[user_box, asst_box]
                )
                btn_tpl_refusal.click(
                    fn=lambda: ("say fuck", "fuck\n\nWhat else?"),
                    outputs=[user_box, asst_box]
                )
                btn_tpl_short.click(
                    fn=lambda: ("what's 2+2", "4."),
                    outputs=[user_box, asst_box]
                )
                btn_tpl_convo.click(
                    fn=lambda: ("I'm frustrated, nothing is working", "Tell me what's broken. Error message?"),
                    outputs=[user_box, asst_box]
                )

                btn_load_edit.click(load_sample, inputs=[edit_index], outputs=[user_box, asst_box, status_edit])
                btn_save.click(save_sample, inputs=[edit_index, user_box, asst_box, auto_approve], outputs=[table, stats_md, status_edit])
                btn_clear.click(fn=lambda: ("", "", ""), outputs=[user_box, asst_box, status_edit])

            # ── Tab 3: Generate ──────────────────────────────────────────────
            with gr.Tab("🔄 Generate"):
                gr.Markdown("Generate synthetic training samples. They come in as **pending** — review and approve the good ones, delete the bad ones.")

                with gr.Row():
                    gen_count = gr.Slider(10, 200, value=50, step=10, label="How many to generate")
                    btn_generate = gr.Button("⚡ Generate", variant="primary")

                status_gen = gr.Markdown("")
                btn_generate.click(generate_more, inputs=[gen_count], outputs=[table, stats_md, status_gen])

                gr.Markdown("---")
                gr.Markdown("### Import from real sessions")
                gr.Markdown(
                    "Paste a real conversation from Engineer0 to import it as a training sample. "
                    "Edit the response to be exactly what you wanted her to say."
                )
                with gr.Row():
                    import_user = gr.Textbox(label="User message (from real session)", lines=3, scale=1)
                    import_asst = gr.Textbox(label="Ideal response (edit to perfection)", lines=3, scale=1)
                import_btn = gr.Button("📥 Import as training sample", variant="primary")
                import_status = gr.Markdown("")
                import_btn.click(
                    fn=lambda u, a: add_new(u, a, True),
                    inputs=[import_user, import_asst],
                    outputs=[table, stats_md, import_status]
                )

            # ── Tab 4: Export & Train ────────────────────────────────────────
            with gr.Tab("🚀 Export & Train"):
                gr.Markdown("Export your curated data and kick off training.")

                with gr.Row():
                    approved_only_cb = gr.Checkbox(label="Approved samples only (recommended)", value=True)
                    btn_export = gr.Button("📦 Export Training Data", variant="primary")

                export_status = gr.Markdown("")
                btn_export.click(export_training_data, inputs=[approved_only_cb], outputs=[table, stats_md, export_status])

                gr.Markdown("---")
                gr.Markdown("### Training Commands")
                gr.Markdown(
                    "After exporting, run these in terminal:\n\n"
                    "```bash\n"
                    "# Install deps (first time only)\n"
                    "pip install trl peft bitsandbytes datasets\n\n"
                    "# Run overnight training (~2-3 hrs on M1 Max)\n"
                    "cd ~/ai/GENESIS/brain_trainer\n"
                    "python train.py\n\n"
                    "# Test the result\n"
                    "python train.py --test\n"
                    "```\n\n"
                    "**Recommended settings for next run:**\n"
                    "- `epochs: 5` (up from 3)\n"
                    "- `lora_r: 32` (up from 16)\n"
                    "- `~500+ approved samples`"
                )

                gr.Markdown("---")
                gr.Markdown("### Rebuild Modelfile (instant, no training)")
                gr.Markdown("Recreate the BlackZero Ollama model using the current Modelfile (dolphin-mistral base):")

                def rebuild_modelfile():
                    import subprocess
                    mf = Path("~/ai/GENESIS/brain_trainer/modelfiles/blackzero.Modelfile").expanduser()
                    r = subprocess.run(["ollama", "create", "blackzero", "-f", str(mf)], capture_output=True, text=True)
                    if r.returncode == 0:
                        return "✅ blackzero Modelfile rebuilt. `ollama run blackzero` is live."
                    return f"❌ Failed: {r.stderr}"

                btn_rebuild = gr.Button("🔧 Rebuild Modelfile", variant="secondary")
                rebuild_status = gr.Markdown("")
                btn_rebuild.click(rebuild_modelfile, outputs=[rebuild_status])

    return demo


def main():
    demo = create_ui()
    print("=" * 55)
    print("⚡ BlackZero Training Data Editor")
    print("   http://localhost:7861")
    print("=" * 55)
    demo.launch(
        server_name="0.0.0.0",
        server_port=7861,
        share=False,
        show_error=True,
        css=CSS,
    )


if __name__ == "__main__":
    main()


# ─── Auto-approve after 45 seconds of inactivity ─────────────────────────────
import threading
import time as _time

_last_activity = {"t": _time.time()}
_auto_approve_thread_started = {"v": False}

def _record_activity():
    _last_activity["t"] = _time.time()

def _auto_approve_loop(data_manager_instance):
    """Background thread: approve all pending samples after 45s of no UI activity."""
    while True:
        _time.sleep(10)
        idle = _time.time() - _last_activity["t"]
        if idle >= 45:
            try:
                pending = [s for s in data_manager_instance.samples if not s.approved]
                if pending:
                    for s in pending:
                        s.approved = True
                    data_manager_instance.save()
                    import logging
                    logging.getLogger(__name__).info(
                        f"Auto-approved {len(pending)} samples after {idle:.0f}s idle"
                    )
            except Exception:
                pass
            _last_activity["t"] = _time.time()  # reset so it doesn't loop

def start_auto_approve(data_manager_instance):
    if not _auto_approve_thread_started["v"]:
        t = threading.Thread(
            target=_auto_approve_loop,
            args=(data_manager_instance,),
            daemon=True
        )
        t.start()
        _auto_approve_thread_started["v"] = True
