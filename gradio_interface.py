"""
GENESIS Gradio Interface with Task Queue & Conversational Intelligence
Pure conversation with explicit command confirmation workflow
"""

import gradio as gr
import logging
from typing import List, Tuple, Optional, Dict
from agents.engineer import EngineerAgent
from core.workspace import workspace
from core.task_queue import TaskQueue
import tempfile
import os

logger = logging.getLogger(__name__)


class GradioInterface:
    """Gradio interface with Task Queue, Conversational AI, and Voice"""
    
    def __init__(self):
        self.agent = EngineerAgent(max_iterations=30)
        self.task_queue = TaskQueue(max_tasks=5)
        self.conversation_memory = []
        self.max_memory = 20
        self.enable_voice_output = True
        self.pending_task_button = None
        self.selected_task_id = None
        self.awaiting_confirmation = False
        
        self._init_llm_client()
        
    def _init_llm_client(self):
        """Initialize LLM client for conversations"""
        try:
            from openai import OpenAI
            import os
            self.llm_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.use_llm = True
            logger.info("Conversational AI enabled with GPT-4")
        except Exception as e:
            logger.warning(f"Could not initialize LLM: {e}")
            self.use_llm = False
    
    def _add_to_memory(self, role: str, content: str):
        """Add message to conversation memory"""
        self.conversation_memory.append({"role": role, "content": content})
        if len(self.conversation_memory) > self.max_memory:
            self.conversation_memory = self.conversation_memory[-self.max_memory:]
    
    def _detect_task_ready(self, message: str, conversation_context: List[Dict]) -> Optional[Dict]:
        """Detect if conversation has defined a clear task ready for queuing"""
        
        if not self.use_llm:
            return None
        
        try:
            response = self.llm_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": """Analyze if the conversation has defined a COMPLETE, ACTIONABLE task.

A task is ready if:
- User has clearly described WHAT to build
- Sufficient details provided (or reasonable defaults possible)
- User intent is to CREATE something (not just discuss)

NOT ready if:
- Still asking questions/exploring
- Vague or ambiguous
- Just discussing possibilities

If ready, respond with JSON:
{
  "ready": true,
  "name": "Short task name",
  "description": "What it does",
  "details": "Key requirements/features",
  "estimated_file": "suggested_filename.py"
}

If not ready, respond: {"ready": false}"""},
                    *conversation_context[-6:],
                    {"role": "user", "content": message}
                ],
                temperature=0.3,
                max_tokens=300
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            
            if result.get("ready"):
                logger.info(f"Task detected: {result.get('name')}")
                return result
            
            return None
            
        except Exception as e:
            logger.error(f"Task detection error: {e}")
            return None
    
    def _generate_conversational_response(self, message: str) -> Tuple[str, bool]:
        """Generate conversational response and detect if task is ready
        
        Returns: (response_text, show_add_button)
        """
        
        if not self.use_llm:
            return ("I'm a coding assistant. I can help you build applications!", False)
        
        try:
            context_messages = [
                {"role": "system", "content": """You are GENESIS, a conversational AI coding assistant with autonomous execution capabilities.

YOUR CAPABILITIES:
You have access to a comprehensive tool system. At the start of any complex task, you should:
1. Call get_tool_summary() to see all available tools
2. Use tools to accomplish tasks - you are NOT limited to just conversation

YOUR TOOLS INCLUDE:
- FILE OPERATIONS: read, write, replace, delete, copy files and directories
- CODE EXECUTION: run Python code, capture output, parse errors, test iteratively
- PACKAGE MANAGEMENT: install dependencies, check packages, auto-install missing imports
- WORKSPACE: sandboxed environment for safe testing and file management

YOUR WORKFLOW:
1. Discuss and clarify requirements with the user
2. When user says "build it" → task goes to queue
3. When "Execute Task" is clicked → you autonomously:
   a. Use tool discovery to understand your capabilities
   b. Write the code
   c. Save to workspace
   d. Test execution
   e. Parse any errors
   f. Auto-install missing packages
   g. Fix errors iteratively
   h. Deliver working code

AUTONOMOUS EXECUTION PHILOSOPHY:
- You CAN and SHOULD execute code to verify it works
- You CAN and SHOULD install missing packages automatically
- You CAN and SHOULD fix errors iteratively without asking for help
- You work in a safe workspace sandbox
- You test → detect errors → fix → test again until it works
- You don't just write code, you deliver WORKING code

COMMUNICATION:
- Chat naturally to understand requirements
- Keep responses concise (2-4 sentences)
- When task is ready, remind user they can say "build it"
- During execution, work autonomously and report results

Example:
User: "I need a web scraper"
You: "I can help with that! What website and what data should I extract?"

User: "CNN headlines"
You: "Perfect! I can build a scraper for CNN headlines. Say 'build it' when ready!"

User: "build it"
You: [Queue task, then on execute:]
   - Discover tools
   - Write scraper code
   - Test execution
   - Install requests/beautifulsoup if needed
   - Fix any errors
   - Deliver working code

Remember: You're an AUTONOMOUS agent. Use your tools. Make things work.
"""}
            ]
            
            context_messages.extend(self.conversation_memory[-10:])
            context_messages.append({"role": "user", "content": message})
            
            response = self.llm_client.chat.completions.create(
                model="gpt-4",
                messages=context_messages,
                temperature=0.7,
                max_tokens=300
            )
            
            response_text = response.choices[0].message.content
            
            # Check if task is ready
            task_ready = self._detect_task_ready(message, context_messages)
            show_button = task_ready is not None
            
            if show_button:
                # Store pending task for button click
                self.pending_task_button = task_ready
            
            return (response_text, show_button)
            
        except Exception as e:
            logger.error(f"Conversational response error: {e}")
            return ("I'm here to help you build things! What would you like to create?", False)
    
    def process_voice_input(self, audio) -> str:
        """Convert speech to text using Whisper"""
        if audio is None:
            return ""
        
        try:
            # TODO: Implement actual Whisper STT
            logger.info("Voice input received (STT not implemented yet)")
            return ""
        except Exception as e:
            logger.error(f"Voice input error: {e}")
            return ""
    
    def _generate_voice_output(self, text: str) -> Optional[str]:
        """Generate TTS audio from text"""
        try:
            import pyttsx3
            
            engine = pyttsx3.init()
            engine.setProperty('rate', 175)
            engine.setProperty('volume', 0.9)
            
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
    
    def chat(self, message: str, history: List, voice_input) -> Tuple[List, str, str, str, Optional[str]]:
        """Process chat message - conversational with explicit command detection"""
        
        # Handle voice input if present
        if voice_input is not None:
            voice_text = self.process_voice_input(voice_input)
            if voice_text:
                message = voice_text
        
        if not message.strip():
            return history, self._render_queue(), "*Ready*", "", None
        
        # Add user message to memory
        self._add_to_memory("user", message)
        
        # Detect explicit queue commands
        lower_msg = message.lower().strip()
        
        # Handle explicit confirmation
        if self.awaiting_confirmation and lower_msg in ['yes', 'y', 'confirm', 'do it']:
            return self._confirm_task_add(history)
        
        if self.awaiting_confirmation and lower_msg in ['no', 'n', 'cancel', 'nevermind']:
            self.awaiting_confirmation = False
            self.pending_task_button = None
            response = "Okay, cancelled. What would you like to build?"
            history.append((message, response))
            self._add_to_memory("assistant", response)
            return history, self._render_queue(), "*Ready*", "", None
        
        # Handle "build it" type commands
        if any(cmd in lower_msg for cmd in ['build it', 'create it', 'do it', 'make it', 'go ahead']):
            # Try to detect task from conversation context
            task_info = self._detect_task_ready(message, self.conversation_memory)
            
            if task_info:
                self.pending_task_button = task_info
                self.awaiting_confirmation = True
                
                response = f"I'll create: **{task_info['name']}**\n{task_info['description']}\n\nConfirm? (yes/no)"
                history.append((message, response))
                self._add_to_memory("assistant", response)
                
                return history, self._render_queue(), "⏳ *Awaiting confirmation...*", "", None
            else:
                response = "I'm not sure exactly what to build yet. Can you describe what you want in more detail?"
                history.append((message, response))
                self._add_to_memory("assistant", response)
                return history, self._render_queue(), "*Ready*", "", None
        
        # Normal conversation
        response_text, show_button = self._generate_conversational_response(message)
        
        history.append((message, response_text))
        self._add_to_memory("assistant", response_text)
        
        # Generate voice output if enabled
        voice_file = None
        if self.enable_voice_output:
            voice_file = self._generate_voice_output(response_text)
        
        status = "⏳ *Task ready - say 'build it' to queue!*" if show_button else "*Ready*"
        
        return history, self._render_queue(), status, "", voice_file
    
    def _confirm_task_add(self, history: List) -> Tuple[List, str, str, str, Optional[str]]:
        """Confirm and add task to queue"""
        if not self.pending_task_button:
            response = "No task to confirm. What would you like to build?"
            history.append(("yes", response))
            return history, self._render_queue(), "*Ready*", "", None
        
        task_info = self.pending_task_button
        
        # Add to queue
        task_id = self.task_queue.add_task(
            name=task_info['name'],
            description=task_info['description'],
            details=task_info['details'],
            estimated_file=task_info.get('estimated_file', 'script.py')
        )
        
        response = f"✅ Added to queue: **{task_info['name']}**\nClick 'Execute Task' to generate code!"
        history.append(("yes", response))
        self._add_to_memory("assistant", response)
        
        # Reset state
        self.awaiting_confirmation = False
        self.pending_task_button = None
        
        # Generate voice
        voice_file = None
        if self.enable_voice_output:
            voice_file = self._generate_voice_output(response)
        
        return history, self._render_queue(), f"✅ *Task queued: {task_info['name']}*", "", voice_file
    
    def _render_queue(self) -> str:
        """Render HTML for task queue"""
        tasks = self.task_queue.list_tasks()
        
        if not tasks:
            return "<div style='padding: 20px; text-align: center; color: #888;'>No tasks in queue</div>"
        
        html = "<div style='padding: 10px;'>"
        
        for task in tasks:
            status_emoji = {
                'queued': '⏳',
                'in_progress': '🔄',
                'complete': '✅',
                'failed': '❌'
            }.get(task['status'], '❓')
            
            html += f"""
            <div style='margin: 10px 0; padding: 12px; border: 1px solid #ddd; border-radius: 8px; background: #f9f9f9;'>
                <div style='font-weight: bold;'>{status_emoji} {task['name']}</div>
                <div style='font-size: 0.9em; color: #666; margin-top: 4px;'>{task['description']}</div>
                <div style='font-size: 0.8em; color: #999; margin-top: 4px;'>Status: {task['status'].title()}</div>
            </div>
            """
        
        html += "</div>"
        return html
    
    def _get_task_choices(self) -> List[str]:
        """Get list of task names for dropdown"""
        tasks = self.task_queue.list_tasks()
        if not tasks:
            return ["No tasks"]
        return [f"{t['id']}: {t['name']} ({t['status']})" for t in tasks]
    
    def _get_task_by_id(self, task_id: str):
        """Get task from queue by ID"""
        tasks = self.task_queue.list_tasks()
        return next((t for t in tasks if t['id'] == task_id), None)
    
    def select_task(self, task_choice: str) -> str:
        """Display selected task details in code viewer"""
        if not task_choice or task_choice == "No tasks":
            return "# No task selected\n# Queue a task to see details here"
        
        # Extract task ID from choice string
        try:
            task_id = task_choice.split(':')[0]
            task = self._get_task_by_id(task_id)
            
            if not task:
                return "# Task not found"
            
            self.selected_task_id = task_id
            
            # Display task details
            details = f"""# Task: {task['name']}
# Status: {task['status'].title()}
# Created: {task.get('created_at', 'N/A')}

'''
Description:
{task['description']}

Requirements:
{task['details']}

Estimated File: {task.get('estimated_file', 'script.py')}
'''

# Click 'Execute Task' to generate code for this task
"""
            return details
            
        except Exception as e:
            logger.error(f"Error selecting task: {e}")
            return f"# Error loading task: {e}"
    
    def execute_task(self, current_code: str, save_path: str) -> Tuple[str, str, str]:
        """Execute the selected task or first queued task"""
        
        # Try to use selected task first
        task = None
        if self.selected_task_id:
            task = self._get_task_by_id(self.selected_task_id)
            if task and task['status'] != 'queued':
                task = None  # Only execute queued tasks
        
        # Fall back to first queued task
        if not task:
            tasks = self.task_queue.list_tasks()
            task = next((t for t in tasks if t['status'] == 'queued'), None)
        
        if not task:
            return current_code, "No tasks to execute", "⚠️ No queued tasks"
        
        # Update status
        self.task_queue.update_task_status(task['id'], 'in_progress')
        
        # Execute with engineer
        result = self.agent.execute({
            'objective': task['name'],
            'description': task['description'],
            'requirements': task['details']
        })
        
        # Get generated code
        generated_code = result.get('code', '# No code generated')
        
        # Update task status
        self.task_queue.update_task_status(
            task['id'],
            'complete' if result['success'] else 'failed',
            result
        )
        
        # Format logs
        logs = self._format_execution_logs(result)
        
        status = f"✅ **Complete** - {result['iterations']} iterations" if result['success'] else f"❌ **Failed** - {result['status']}"
        
        return generated_code, logs, status
    
    def _format_execution_logs(self, result: dict) -> str:
        """Format execution history"""
        logs = []
        
        for i, entry in enumerate(result['execution_history'], 1):
            if entry.get('type') == 'fix_attempt':
                fix = entry.get('fix', {})
                fix_result = entry.get('result', {})
                logs.append(f"🔧 Fix {entry['iteration']}: {fix.get('description')}")
                logs.append(f"   {'✅' if fix_result.get('success') else '❌'}")
            else:
                step = entry.get('step', {})
                step_result = entry.get('result', {})
                logs.append(f"[{i}] {step.get('description', 'Step')}")
                logs.append(f"    {step.get('action')} - {'✅' if step_result.get('success') else '❌'}")
            
            logs.append("")
        
        return "\n".join(logs)
    
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
    
    def create_interface(self):
        """Create the Gradio interface"""
        
        with gr.Blocks(title="GENESIS Engineer", theme=gr.themes.Soft()) as interface:
            gr.Markdown("# 🤖 GENESIS - Conversational AI Engineer")
            gr.Markdown("Chat naturally - say 'build it' when ready to queue tasks!")
            
            with gr.Row():
                # Left: Chat
                with gr.Column(scale=1):
                    with gr.Accordion("💬 Chat & Voice", open=True):
                        chatbot = gr.Chatbot(
                            height=400,
                            label="Conversation"
                        )
                        
                        with gr.Row():
                            msg_input = gr.Textbox(
                                placeholder="Type your message... (Enter to send, Shift+Enter for new line)",
                                label="Your Message",
                                lines=2,
                                max_lines=5,
                                scale=3
                            )
                            voice_input = gr.Audio(
                                sources=["microphone"],
                                type="filepath",
                                label="🎤",
                                scale=1
                            )
                        
                        with gr.Row():
                            send_btn = gr.Button("▶️ Send", variant="primary", scale=2)
                            clear_btn = gr.Button("🗑️ Clear", scale=1)
                        
                        with gr.Accordion("📢 Voice Output", open=False):
                            voice_output = gr.Audio(
                                label="Agent Response",
                                autoplay=True
                            )
                        
                        gr.Examples(
                            examples=[
                                "What can you help me build?",
                                "I need a web scraper for news sites",
                                "Build me a word alphabetizer",
                                "How do I deploy this to my phone?"
                            ],
                            inputs=msg_input
                        )
                
                # Right: Task Queue & Code
                with gr.Column(scale=1):
                    with gr.Accordion("📋 Task Queue (0/5)", open=True):
                        queue_display = gr.HTML(value="<div style='padding: 20px; text-align: center;'>No tasks</div>")
                        
                        task_selector = gr.Dropdown(
                            choices=["No tasks"],
                            label="Select Task to View/Execute",
                            value="No tasks",
                            interactive=True
                        )
                    
                    code_viewer = gr.Code(
                        label="📝 Task Details / Generated Code",
                        language="python",
                        lines=12,
                        value="# Select a task from the dropdown to view details\n# Click Execute to generate code"
                    )
                    
                    save_path_input = gr.Textbox(
                        label="💾 Save Location",
                        value="/workspace/script.py"
                    )
                    
                    with gr.Row():
                        execute_btn = gr.Button("🚀 Execute Task", variant="primary", scale=2)
                        save_btn = gr.Button("💾 Save As", scale=1)
                        refresh_code_btn = gr.Button("🔄 Refresh", scale=1)
                    
                    status_display = gr.Markdown("*Ready - start a conversation!*")
                    
                    with gr.Accordion("🔧 Execution Logs", open=False):
                        logs_display = gr.Textbox(
                            label="Steps & Results",
                            lines=10,
                            max_lines=20
                        )
            
            # Event handlers
            def send_message(message, history, voice):
                result = self.chat(message, history, voice)
                # Update task selector choices
                new_choices = self._get_task_choices()
                return result + ("",) + (gr.Dropdown(choices=new_choices, value=new_choices[0] if new_choices else "No tasks"),)
            
            send_btn.click(
                fn=send_message,
                inputs=[msg_input, chatbot, voice_input],
                outputs=[chatbot, queue_display, status_display, logs_display, voice_output, msg_input, task_selector]
            )
            
            msg_input.submit(
                fn=send_message,
                inputs=[msg_input, chatbot, voice_input],
                outputs=[chatbot, queue_display, status_display, logs_display, voice_output, msg_input, task_selector]
            )
            
            task_selector.change(
                fn=self.select_task,
                inputs=[task_selector],
                outputs=[code_viewer]
            )
            
            execute_btn.click(
                fn=self.execute_task,
                inputs=[code_viewer, save_path_input],
                outputs=[code_viewer, logs_display, status_display]
            )
            
            clear_btn.click(
                fn=lambda: ([], "", "", "*Ready - start a conversation!*", None, gr.Dropdown(choices=["No tasks"], value="No tasks")),
                outputs=[chatbot, code_viewer, logs_display, status_display, voice_output, task_selector]
            )
            
            refresh_code_btn.click(
                fn=self._get_latest_code,
                outputs=code_viewer
            )
        
        return interface


def main():
    """Launch interface"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("="*60)
    print("🤖 GENESIS - Conversational AI with Task Queue")
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
    print("🌐 http://localhost:7860")
    print("💬 Pure conversation - say 'build it' to queue tasks")
    print("🎤 Click microphone for voice input\n")
    
    interface.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        theme=gr.themes.Soft()
    )


if __name__ == "__main__":
    main()
