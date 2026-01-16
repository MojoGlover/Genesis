"""
GENESIS Gradio Interface with Voice & Engineer Agent
Talk to your AI - watch it write, test, and fix code autonomously
"""

import gradio as gr
import logging
from typing import List, Tuple, Optional
from agents.engineer import EngineerAgent
from core.workspace import workspace
import tempfile
import os

logger = logging.getLogger(__name__)


class GradioInterface:
    """Gradio interface with Engineer Agent and Voice"""
    
    def __init__(self):
        self.agent = EngineerAgent(max_iterations=30)
        self.conversation_history = []
        self.enable_voice_output = True
        
    def process_voice_input(self, audio) -> str:
        """Convert speech to text using Whisper"""
        if audio is None:
            return ""
        
        try:
            # Import whisper/STT library
            # For now, return placeholder
            # TODO: Implement actual Whisper STT
            logger.info("Voice input received (STT not implemented yet)")
            return "Voice input: [Whisper STT to be implemented]"
        except Exception as e:
            logger.error(f"Voice input error: {e}")
            return ""
    
    def chat(self, message: str, history: List, voice_input) -> Tuple[List, str, str, str, Optional[str]]:
        """Process chat message with Engineer Agent"""
        
        # Handle voice input if present
        if voice_input is not None:
            voice_text = self.process_voice_input(voice_input)
            if voice_text:
                message = voice_text
        
        if not message.strip():
            return history, "", "", "", None
        
        # Determine if this is a coding task
        is_coding_task = any(word in message.lower() for word in
            ["write", "create", "build", "code", "script", "program", "function", "read", "modify", "update", "fix"])
        
        if is_coding_task:
            logger.info(f"Processing coding task: {message}")
            result = self.agent.run_coding_task(message)
        else:
            logger.info(f"Processing task: {message}")
            result = self.agent.run(message)
        
        # Format AI response
        response = self._format_response(result)
        
        # NEW FORMAT - Create proper message format with role/content dicts
        new_history = history.copy() if history else []
        new_history.append({"role": "user", "content": message})
        new_history.append({"role": "assistant", "content": response})
        
        # Generate voice output if enabled
        voice_output = self._generate_voice_output(response) if self.enable_voice_output else None
        
        # Get workspace files and code
        code_output = self._get_latest_code()
        
        # Get execution logs
        logs = self._format_execution_logs(result)
        
        # Get status with fix attempts
        status = self._format_status(result)
        
        return new_history, code_output, logs, status, voice_output
    
    def _generate_voice_output(self, text: str) -> Optional[str]:
        """Generate TTS audio from text"""
        try:
            # Use pyttsx3 for offline TTS
            import pyttsx3
            
            engine = pyttsx3.init()
            
            # Configure voice
            engine.setProperty('rate', 175)  # Speed
            engine.setProperty('volume', 0.9)
            
            # Save to temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            engine.save_to_file(text, temp_file.name)
            engine.runAndWait()
            
            return temp_file.name
            
        except ImportError:
            logger.warning("pyttsx3 not installed - voice output disabled")
            return None
        except Exception as e:
            logger.error(f"Voice output error: {e}")
            return None
    
    def _format_response(self, result: dict) -> str:
        """Format agent result as chat response"""
        status_emoji = "✅" if result['success'] else "❌"
        
        response_parts = [
            f"{status_emoji} Task {result['status']}",
            f"Completed in {result['iterations']} iterations"
        ]
        
        fix_attempts = sum(1 for entry in result['execution_history']
                          if entry.get('type') == 'fix_attempt')
        if fix_attempts > 0:
            response_parts.append(f"Applied {fix_attempts} fixes automatically")
        
        if result.get('files_created'):
            response_parts.append("Files created in workspace")
        
        return " - ".join(response_parts)
    
    def _get_latest_code(self) -> str:
        """Get the most recently created/modified code file"""
        try:
            result = workspace.execute("ls -lt /workspace/*.py 2>/dev/null | head -5")
            
            if result.get('success') and result['stdout']:
                lines = result['stdout'].strip().split('\n')
                if lines and lines[0]:
                    latest_file = lines[0].split()[-1] if lines[0] else None
                    
                    if latest_file:
                        code_result = workspace.read_file(latest_file)
                        if code_result.get('success'):
                            return f"# {latest_file}\n\n{code_result['content']}"
            
            result = workspace.list_directory("/workspace")
            return result.get('listing', 'No files found')
            
        except Exception as e:
            return f"Error reading code: {e}"
    
    def _format_execution_logs(self, result: dict) -> str:
        """Format execution history including fix attempts"""
        logs = []
        
        for i, entry in enumerate(result['execution_history'], 1):
            if entry.get('type') == 'fix_attempt':
                fix = entry.get('fix', {})
                fix_result = entry.get('result', {})
                logs.append(f"🔧 Fix {entry['iteration']}: {fix.get('description')}")
                logs.append(f"   {'✅ Success' if fix_result.get('success') else '❌ Failed'}")
            else:
                step = entry.get('step', {})
                step_result = entry.get('result', {})
                logs.append(f"[{i}] {step.get('description', 'Step')}")
                logs.append(f"    {step.get('action')} - {'✅' if step_result.get('success') else '❌'}")
                
                if step.get('fixes_applied'):
                    logs.append(f"    Fixes: {step['fixes_applied']}")
            
            logs.append("")
        
        return "\n".join(logs)
    
    def _format_status(self, result: dict) -> str:
        """Format current agent status"""
        fix_count = sum(1 for entry in result['execution_history']
                       if entry.get('type') == 'fix_attempt')
        
        status_parts = [
            f"**Status:** {result['status'].upper()}",
            f"**Iterations:** {result['iterations']}/30",
            f"**Success:** {'✅' if result['success'] else '❌'}",
            f"**Steps:** {len([e for e in result['execution_history'] if e.get('step')])}"
        ]
        
        if fix_count > 0:
            status_parts.append(f"**Fixes:** 🔧 {fix_count}")
        
        return "\n".join(status_parts)
    
    def create_interface(self):
        """Create the Gradio interface with voice"""
        
        with gr.Blocks(title="GENESIS Engineer") as interface:
            gr.Markdown("# 🤖 GENESIS - Voice-Enabled Engineer Agent")
            gr.Markdown("Talk or type your coding tasks - watch autonomous development in real-time!")
            
            with gr.Row():
                # Left column - Chat & Voice
                with gr.Column(scale=1):
                    with gr.Accordion("💬 Chat & Voice", open=True):
                        chatbot = gr.Chatbot(
                            height=350,
                            label="Conversation"
                        )
                        
                        with gr.Row():
                            msg_input = gr.Textbox(
                                placeholder="Type or speak your task...",
                                label="Your Task",
                                lines=2,
                                scale=3
                            )
                            voice_input = gr.Audio(
                                sources=["microphone"],
                                type="filepath",
                                label="🎤",
                                scale=1
                            )
                        
                        with gr.Row():
                            submit_btn = gr.Button("▶️ Send", variant="primary", scale=2)
                            clear_btn = gr.Button("🗑️ Clear", scale=1)
                        
                        with gr.Accordion("📢 Voice Output", open=False):
                            voice_output = gr.Audio(
                                label="Agent Response",
                                autoplay=True
                            )
                        
                        gr.Examples(
                            examples=[
                                "Create a Python script that calculates fibonacci",
                                "Write a web scraper for news",
                                "Build a REST API with Flask"
                            ],
                            inputs=msg_input
                        )
                
                # Right column - Code & Monitoring
                with gr.Column(scale=1):
                    with gr.Accordion("📝 Generated Code", open=True):
                        code_viewer = gr.Code(
                            label="Latest Code",
                            language="python",
                            lines=12
                        )
                        refresh_code_btn = gr.Button("🔄 Refresh")
                    
                    with gr.Accordion("📊 Status", open=True):
                        status_display = gr.Markdown("*Ready - awaiting task*")
                    
                    with gr.Accordion("🔧 Execution Log", open=False):
                        logs_display = gr.Textbox(
                            label="Steps & Auto-fixes",
                            lines=10,
                            max_lines=20
                        )
            
            # Event handlers
            def submit_task(message, history, voice):
                result = self.chat(message, history, voice)
                return result + ("",)  # Clear text input
            
            submit_btn.click(
                fn=submit_task,
                inputs=[msg_input, chatbot, voice_input],
                outputs=[chatbot, code_viewer, logs_display, status_display, voice_output, msg_input]
            )
            
            msg_input.submit(
                fn=submit_task,
                inputs=[msg_input, chatbot, voice_input],
                outputs=[chatbot, code_viewer, logs_display, status_display, voice_output, msg_input]
            )
            
            clear_btn.click(
                fn=lambda: ([], "", "", "*Ready*", None),
                outputs=[chatbot, code_viewer, logs_display, status_display, voice_output]
            )
            
            refresh_code_btn.click(
                fn=self._get_latest_code,
                outputs=code_viewer
            )
        
        return interface


def main():
    """Launch voice-enabled Gradio interface"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("="*60)
    print("🎤 GENESIS Engineer Agent with Voice - Starting...")
    print("="*60)
    
    # Try to import voice dependencies
    try:
        import pyttsx3
        print("✅ Text-to-Speech (pyttsx3) available")
    except ImportError:
        print("⚠️  pyttsx3 not installed - voice output disabled")
        print("   Install with: pip3 install pyttsx3")
    
    ui = GradioInterface()
    interface = ui.create_interface()
    
    print("\n✅ Interface ready!")
    print("🌐 Opening at: http://localhost:7860")
    print("🎤 Click microphone icon to use voice input\n")
    
    interface.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=True,  # ← Change this to True
        theme=gr.themes.Soft()
)


if __name__ == "__main__":
    main()
