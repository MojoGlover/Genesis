"""
GENESIS Gradio Interface - Thin UI layer
All business logic lives in core/services/orchestrator.py
"""

import gradio as gr
import logging
from typing import List, Tuple, Optional, Dict

from core.services.orchestrator import get_orchestrator

logger = logging.getLogger(__name__)


def _render_queue(tasks: List[Dict]) -> str:
    """Render HTML for task queue display (UI concern)"""
    if not tasks:
        return "<div style='padding: 20px; text-align: center; color: #888;'>No tasks in queue</div>"

    html = "<div style='padding: 10px;'>"
    for task in tasks:
        status_emoji = {
            "queued": "\u23f3",
            "in_progress": "\U0001f504",
            "complete": "\u2705",
            "failed": "\u274c",
            "pending": "\u23f3",
        }.get(task.get("status", ""), "\u2753")

        html += f"""
        <div style='margin: 10px 0; padding: 12px; border: 1px solid #ddd; border-radius: 8px; background: #f9f9f9;'>
            <div style='font-weight: bold;'>{status_emoji} {task['name']}</div>
            <div style='font-size: 0.9em; color: #666; margin-top: 4px;'>{task['description']}</div>
            <div style='font-size: 0.8em; color: #999; margin-top: 4px;'>Status: {task.get('status', 'unknown').title()}</div>
        </div>
        """
    html += "</div>"
    return html


def _format_logs(execution_log: List[Dict]) -> str:
    """Format execution log entries for display (UI concern)"""
    ok = "\u2705"
    fail = "\u274c"
    lines = []
    for i, entry in enumerate(execution_log, 1):
        if entry.get("type") == "fix_attempt":
            fix = entry.get("fix", {})
            fix_result = entry.get("result", {})
            status_icon = ok if fix_result.get("success") else fail
            lines.append(f"\U0001f527 Fix {entry.get('iteration', '?')}: {fix.get('description', '')}")
            lines.append(f"   {status_icon}")
        else:
            step = entry.get("step", {})
            step_result = entry.get("result", {})
            status_icon = ok if step_result.get("success") else fail
            lines.append(f"[{i}] {step.get('description', 'Step')}")
            lines.append(f"    {step.get('action', '')} - {status_icon}")
        lines.append("")
    return "\n".join(lines)


def _state_to_status(result: Dict) -> str:
    """Map orchestrator result to a Gradio status markdown string"""
    state = result.get("state", "ready")
    if state == "awaiting_confirmation":
        return "\u23f3 *Awaiting confirmation...*"
    if result.get("task_ready"):
        return "\u23f3 *Task ready - say 'build it' to queue!*"
    return "*Ready*"


class GradioInterface:
    """Thin Gradio UI — all logic delegated to ChatOrchestrator"""

    def __init__(self):
        self.orchestrator = get_orchestrator()

    def chat(
        self, message: str, history: List, voice_input
    ) -> Tuple[List, str, str, str, Optional[str]]:
        """Map orchestrator response to Gradio output tuple"""
        result = self.orchestrator.process_message(message, voice_input)

        response = result.get("response", "")
        if response:
            history = list(history)
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": response})

        queue_html = _render_queue(result.get("tasks", []))
        status = _state_to_status(result)
        voice_audio = result.get("voice_audio")

        return history, queue_html, status, "", voice_audio

    def select_task(self, task_choice: str) -> str:
        """Format task details for code viewer"""
        result = self.orchestrator.select_task(task_choice)
        return result.get("details", "# No task selected")

    def execute_task(self, current_code: str, save_path: str) -> Tuple[str, str, str]:
        """Delegate to orchestrator and format output"""
        result = self.orchestrator.execute_task()

        code = result.get("code", current_code)
        logs = _format_logs(result.get("execution_log", []))

        if result.get("success"):
            status = f"\u2705 **Complete** - {result.get('iterations', 0)} iterations"
        elif result.get("status") == "no_tasks":
            status = "\u26a0\ufe0f No queued tasks"
        else:
            status = f"\u274c **Failed** - {result.get('status', 'error')}"

        return code, logs, status

    def clear_all(self):
        """Reset orchestrator and return cleared UI state"""
        self.orchestrator.reset()
        return (
            [],
            "",
            "",
            "*Ready - start a conversation!*",
            None,
            gr.Dropdown(choices=["No tasks"], value="No tasks"),
        )

    def refresh_code(self) -> str:
        """Get latest code from workspace"""
        result = self.orchestrator.get_latest_code()
        if result.get("filename"):
            return f"# {result['filename']}\n\n{result['content']}"
        return result.get("content", "No files found")

    def create_interface(self):
        """Create the Gradio interface — same layout and UX as before"""

        with gr.Blocks(title="GENESIS Engineer", theme=gr.themes.Soft()) as interface:
            gr.Markdown("# \U0001f916 GENESIS - Conversational AI Engineer")
            gr.Markdown("Chat naturally - say 'build it' when ready to queue tasks!")

            with gr.Row():
                # Left: Chat
                with gr.Column(scale=1):
                    with gr.Accordion("\U0001f4ac Chat & Voice", open=True):
                        chatbot = gr.Chatbot(height=400, label="Conversation")

                        with gr.Row():
                            msg_input = gr.Textbox(
                                placeholder="Type your message... (Enter to send, Shift+Enter for new line)",
                                label="Your Message",
                                lines=2,
                                max_lines=5,
                                scale=3,
                            )
                            voice_input = gr.Audio(
                                sources=["microphone"],
                                type="filepath",
                                label="\U0001f3a4",
                                scale=1,
                            )

                        with gr.Row():
                            send_btn = gr.Button("\u25b6\ufe0f Send", variant="primary", scale=2)
                            clear_btn = gr.Button("\U0001f5d1\ufe0f Clear", scale=1)

                        with gr.Accordion("\U0001f4e2 Voice Output", open=False):
                            voice_output = gr.Audio(label="Agent Response", autoplay=True)

                        gr.Examples(
                            examples=[
                                "What can you help me build?",
                                "I need a web scraper for news sites",
                                "Build me a word alphabetizer",
                                "How do I deploy this to my phone?",
                            ],
                            inputs=msg_input,
                        )

                # Right: Task Queue & Code
                with gr.Column(scale=1):
                    with gr.Accordion("\U0001f4cb Task Queue (0/5)", open=True):
                        queue_display = gr.HTML(
                            value="<div style='padding: 20px; text-align: center;'>No tasks</div>"
                        )
                        task_selector = gr.Dropdown(
                            choices=["No tasks"],
                            label="Select Task to View/Execute",
                            value="No tasks",
                            interactive=True,
                        )

                    code_viewer = gr.Code(
                        label="\U0001f4dd Task Details / Generated Code",
                        language="python",
                        lines=12,
                        value="# Select a task from the dropdown to view details\n# Click Execute to generate code",
                    )

                    save_path_input = gr.Textbox(
                        label="\U0001f4be Save Location", value="/workspace/script.py"
                    )

                    with gr.Row():
                        execute_btn = gr.Button("\U0001f680 Execute Task", variant="primary", scale=2)
                        save_btn = gr.Button("\U0001f4be Save As", scale=1)
                        refresh_code_btn = gr.Button("\U0001f504 Refresh", scale=1)

                    status_display = gr.Markdown("*Ready - start a conversation!*")

                    with gr.Accordion("\U0001f527 Execution Logs", open=False):
                        logs_display = gr.Textbox(
                            label="Steps & Results", lines=10, max_lines=20
                        )

            # ---- Event handlers ----
            def send_message(message, history, voice):
                result = self.chat(message, history, voice)
                new_choices = self.orchestrator.get_task_choices()
                return result + ("",) + (
                    gr.Dropdown(
                        choices=new_choices,
                        value=new_choices[0] if new_choices else "No tasks",
                    ),
                )

            send_btn.click(
                fn=send_message,
                inputs=[msg_input, chatbot, voice_input],
                outputs=[chatbot, queue_display, status_display, logs_display, voice_output, msg_input, task_selector],
            )
            msg_input.submit(
                fn=send_message,
                inputs=[msg_input, chatbot, voice_input],
                outputs=[chatbot, queue_display, status_display, logs_display, voice_output, msg_input, task_selector],
            )
            task_selector.change(
                fn=self.select_task,
                inputs=[task_selector],
                outputs=[code_viewer],
            )
            execute_btn.click(
                fn=self.execute_task,
                inputs=[code_viewer, save_path_input],
                outputs=[code_viewer, logs_display, status_display],
            )
            clear_btn.click(
                fn=self.clear_all,
                outputs=[chatbot, code_viewer, logs_display, status_display, voice_output, task_selector],
            )
            refresh_code_btn.click(
                fn=self.refresh_code,
                outputs=code_viewer,
            )

        return interface


def main():
    """Launch interface"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("=" * 60)
    print("\U0001f916 GENESIS - Conversational AI with Task Queue")
    print("=" * 60)

    try:
        import pyttsx3
        print("\u2705 Text-to-Speech (pyttsx3) available")
    except ImportError:
        print("\u26a0\ufe0f  pyttsx3 not installed - voice output disabled")
        print("   Install with: pip3 install pyttsx3")

    ui = GradioInterface()
    interface = ui.create_interface()

    print("\n\u2705 Interface ready!")
    print("\U0001f310 http://localhost:7860")
    print("\U0001f4ac Pure conversation - say 'build it' to queue tasks")
    print("\U0001f3a4 Click microphone for voice input\n")

    interface.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        theme=gr.themes.Soft(),
    )


if __name__ == "__main__":
    main()
