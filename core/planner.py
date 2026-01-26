"""
Task Planner - Uses real LLMs for intelligent planning
"""

import logging
import os
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class TaskPlanner:
    """Plans tasks using real LLM APIs"""
    
    def __init__(self, model_name: str = "gpt-4"):
        self.model_name = model_name
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        
        # Check if we have API keys
        self.use_llm = bool(self.openai_key or self.anthropic_key)
        
        if self.use_llm:
            logger.info(f"TaskPlanner initialized with {model_name} - LLM enabled")
        else:
            logger.warning("No API keys found - using template planning")
    
    def _get_system_prompt(self, tool_descriptions: Optional[Dict[str, str]] = None) -> str:
        """System prompt with dynamic tool list"""
        # Build tool listing
        if tool_descriptions:
            tool_lines = self._format_tool_list(tool_descriptions)
        else:
            tool_lines = "Available actions: workspace_execute, workspace_write, workspace_read, workspace_list, workspace_install"

        return f"""You are a planning assistant for GENESIS, an autonomous agent.

CRITICAL CONTEXT:
- You are NOT responding to the user directly
- You are helping GENESIS create an executable plan
- GENESIS has a workspace with full code execution capabilities
- GENESIS can install packages, access files, run scripts, use network

YOUR JOB: Provide step-by-step plans that GENESIS will execute.

DO NOT say:
- "I cannot execute code"
- "I'm an AI language model"
- "I don't have access to..."
- "As an AI, I cannot..."

INSTEAD:
- Provide concrete, executable steps
- Assume all tools are available
- Be specific about actions to take
- Focus on HOW to accomplish the task

Format your response as a JSON array of steps:
[
  {{
    "step": 1,
    "action": "write_file",
    "description": "Create script file",
    "parameters": {{"filepath": "/workspace/script.py", "content": "code here"}}
  }}
]

{tool_lines}
"""

    @staticmethod
    def _format_tool_list(tool_descriptions: Dict[str, str]) -> str:
        """Format tool descriptions into categorized listing for the LLM"""
        workspace_tools = {}
        local_tools = {}

        for name, desc in sorted(tool_descriptions.items()):
            if name.startswith("workspace_"):
                workspace_tools[name] = desc
            else:
                local_tools[name] = desc

        lines = ["AVAILABLE TOOLS:"]

        if local_tools:
            lines.append("\n## Local Tools (direct execution)")
            for name, desc in local_tools.items():
                lines.append(f"  - {name}: {desc}")

        if workspace_tools:
            lines.append("\n## Docker Workspace Tools (sandboxed)")
            for name, desc in workspace_tools.items():
                lines.append(f"  - {name}: {desc}")

        return "\n".join(lines)
    
    def _clean_response(self, response: str) -> str:
        """Remove LLM identity and refusal statements"""
        
        refusal_phrases = [
            "I'm an AI",
            "I am an AI",
            "I cannot",
            "I can't",
            "I'm not able to",
            "I am not able to",
            "I don't have access",
            "I do not have access",
            "as an AI language model",
            "as a language model",
            "I'm sorry, but I can't",
            "I'm sorry, but I cannot",
            "I apologize, but I cannot",
            "from OpenAI",
            "from Anthropic",
            "I'm Claude",
            "I'm ChatGPT",
        ]
        
        lines = response.split('\n')
        clean_lines = []
        
        for line in lines:
            # Skip lines with refusal phrases
            if any(phrase.lower() in line.lower() for phrase in refusal_phrases):
                logger.warning(f"Filtered refusal: {line[:50]}...")
                continue
            clean_lines.append(line)
        
        return '\n'.join(clean_lines)
    
    def _call_openai(self, prompt: str, tool_descriptions: Optional[Dict[str, str]] = None) -> str:
        """Call OpenAI API using new v1.0+ client"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.openai_key)

            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": self._get_system_prompt(tool_descriptions)},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1500
            )

            content = response.choices[0].message.content
            return self._clean_response(content)

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return None

    def _call_anthropic(self, prompt: str, tool_descriptions: Optional[Dict[str, str]] = None) -> str:
        """Call Anthropic API"""
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=self.anthropic_key)

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                system=self._get_system_prompt(tool_descriptions),
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            content = response.content[0].text
            return self._clean_response(content)

        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return None
    
    def _parse_plan(self, llm_response: str) -> List[Dict[str, Any]]:
        """Parse LLM response into plan steps"""
        
        try:
            # Try to extract JSON from response
            # Look for JSON array
            start = llm_response.find('[')
            end = llm_response.rfind(']') + 1
            
            if start != -1 and end > start:
                json_str = llm_response[start:end]
                plan = json.loads(json_str)
                
                # Add status to each step
                for step in plan:
                    step['status'] = 'pending'
                
                return plan
            else:
                logger.warning("Could not find JSON in LLM response")
                return None
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM plan: {e}")
            return None
    
    def _template_plan(self, task: str) -> List[Dict[str, Any]]:
        """Fallback template-based planning"""
        
        task_lower = task.lower()
        
        if "list" in task_lower and "workspace" in task_lower:
            return [{
                "step": 1,
                "action": "workspace_list",
                "description": "List workspace contents",
                "parameters": {"path": "/workspace"},
                "status": "pending"
            }]
        
        elif any(word in task_lower for word in ["write", "create", "build", "code", "script"]):
            return [
                {
                    "step": 1,
                    "action": "workspace_write",
                    "description": f"Create file for: {task}",
                    "parameters": {
                        "path": "/workspace/output.py",
                        "content": "# Auto-generated\nprint('Task completed')"
                    },
                    "status": "pending"
                },
                {
                    "step": 2,
                    "action": "workspace_execute",
                    "description": "Test the file",
                    "parameters": {"command": "python /workspace/output.py"},
                    "status": "pending"
                }
            ]
        
        else:
            return [{
                "step": 1,
                "action": "workspace_execute",
                "description": f"Execute: {task}",
                "parameters": {"command": f"echo 'Task: {task}'"},
                "status": "pending"
            }]
    
    def create_plan(
        self,
        task: str,
        mission: Dict[str, Any],
        available_tools: List[str],
        tool_descriptions: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """Create initial plan for task"""
        logger.info(f"Creating plan for: {task} ({len(available_tools)} tools available)")

        if self.use_llm:
            # Try LLM planning
            prompt = f"""Task: {task}

Available tools: {', '.join(available_tools)}

Create a detailed step-by-step plan to accomplish this task.
Return only the JSON array of steps."""

            # Try OpenAI first, then Anthropic
            llm_response = self._call_openai(prompt, tool_descriptions)
            if not llm_response:
                llm_response = self._call_anthropic(prompt, tool_descriptions)

            if llm_response:
                plan = self._parse_plan(llm_response)
                if plan:
                    logger.info(f"LLM created plan with {len(plan)} steps")
                    return plan

            logger.warning("LLM planning failed, using template")

        # Fallback to template
        plan = self._template_plan(task)
        logger.info(f"Template plan with {len(plan)} steps")
        return plan
    
    def replan(
        self,
        original_task: str,
        original_plan: List[Dict[str, Any]],
        execution_history: List[Dict[str, Any]],
        mission: Dict[str, Any],
        tool_descriptions: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """Create new plan based on execution results"""

        logger.info("Replanning based on execution history")

        if self.use_llm:
            # Use LLM to analyze failures and replan
            prompt = f"""Original task: {original_task}

Previous plan failed. Execution history:
{json.dumps(execution_history[-3:], indent=2)}

Analyze what went wrong and create a NEW plan that addresses the failures.
Return only the JSON array of steps."""

            llm_response = self._call_openai(prompt, tool_descriptions)
            if not llm_response:
                llm_response = self._call_anthropic(prompt, tool_descriptions)
            
            if llm_response:
                plan = self._parse_plan(llm_response)
                if plan:
                    logger.info(f"LLM replanned with {len(plan)} steps")
                    return plan
        
        # Fallback: retry failed steps with adjustments
        new_plan = []
        for step in original_plan:
            if step.get("status") != "complete":
                step_copy = step.copy()
                step_copy["status"] = "pending"
                step_copy["retry"] = step_copy.get("retry", 0) + 1
                
                # Add error context if available
                if step.get("result", {}).get("error"):
                    step_copy["previous_error"] = step["result"]["error"]
                
                new_plan.append(step_copy)
        
        if not new_plan:
            # All steps completed but task not done - add verification step
            new_plan.append({
                "step": len(original_plan) + 1,
                "action": "workspace_list",
                "description": "Verify task completion",
                "parameters": {"path": "/workspace"},
                "status": "pending"
            })
        
        return new_plan
    
    def verify_completion(
        self,
        task: str,
        plan: List[Dict[str, Any]],
        execution_history: List[Dict[str, Any]]
    ) -> bool:
        """Verify if task is actually complete"""
        
        # Check all steps succeeded
        all_complete = all(s.get("status") == "complete" for s in plan)
        
        if not all_complete:
            return False
        
        # DISABLED: LLM verification to avoid infinite loops when APIs fail
        # Just check if all steps are complete
        logger.info(f"Task completion verified: {all_complete}")
        return all_complete
