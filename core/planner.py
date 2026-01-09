"""
Task Planner - Uses LLMs as planning tools, not as the agent identity
"""

import logging
from typing import Dict, Any, List
import os

logger = logging.getLogger(__name__)


class TaskPlanner:
    """Plans tasks using LLMs as reasoning tools"""
    
    def __init__(self, model_name: str = "gpt-4"):
        self.model_name = model_name
        logger.info(f"TaskPlanner initialized with model: {model_name}")
    
    def _get_system_prompt(self) -> str:
        """System prompt that prevents LLM identity bleed"""
        return """You are a planning assistant for GENESIS, an autonomous agent.

CRITICAL CONTEXT:
- You are NOT responding to the user directly
- You are helping GENESIS create an executable plan
- GENESIS has a workspace with full code execution capabilities
- GENESIS can install packages, access files, run scripts, use network

YOUR JOB: Provide step-by-step plans that GENESIS will execute.

DO NOT say:
❌ "I cannot execute code"
❌ "I'm an AI language model"  
❌ "I don't have access to..."
❌ "I'm not able to..."
❌ "As an AI, I cannot..."
❌ "I'm sorry, but I can't..."

INSTEAD:
✅ Provide concrete, executable steps
✅ Assume all tools are available
✅ Be specific about actions to take
✅ Focus on HOW to accomplish the task

Format your response as a JSON array of steps:
[
  {
    "step": 1,
    "action": "workspace_write",
    "description": "Create script file",
    "parameters": {"path": "/workspace/script.py", "content": "code here"}
  }
]

Available actions: workspace_execute, workspace_write, workspace_read, workspace_list, workspace_install
"""
    
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
    
    def create_plan(
        self,
        task: str,
        mission: Dict[str, Any],
        available_tools: List[str]
    ) -> List[Dict[str, Any]]:
        """Create initial plan for task"""
        logger.info(f"Creating plan for: {task}")
        
        # TODO: Replace with actual LLM API call
        # For now, return intelligent template based on task
        
        if "list" in task.lower() and "workspace" in task.lower():
            plan = [
                {
                    "step": 1,
                    "action": "workspace_list",
                    "description": "List workspace directory contents",
                    "parameters": {"path": "/workspace"},
                    "status": "pending"
                }
            ]
        elif "write" in task.lower() or "create" in task.lower() or "build" in task.lower():
            plan = [
                {
                    "step": 1,
                    "action": "workspace_write",
                    "description": f"Create file for: {task}",
                    "parameters": {
                        "path": "/workspace/output.py",
                        "content": "# Generated file\nprint('Task completed')"
                    },
                    "status": "pending"
                },
                {
                    "step": 2,
                    "action": "workspace_execute",
                    "description": "Test the created file",
                    "parameters": {"command": "python /workspace/output.py"},
                    "status": "pending"
                }
            ]
        else:
            plan = [
                {
                    "step": 1,
                    "action": "workspace_execute",
                    "description": f"Execute task: {task}",
                    "parameters": {"command": f"echo 'Executing: {task}'"},
                    "status": "pending"
                }
            ]
        
        logger.info(f"Created plan with {len(plan)} steps")
        return plan
    
    def replan(
        self,
        original_task: str,
        original_plan: List[Dict[str, Any]],
        execution_history: List[Dict[str, Any]],
        mission: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Create new plan based on execution results"""
        logger.info("Replanning based on execution history")
        
        # TODO: Use LLM to analyze failures and create better plan
        # For now, retry failed steps with adjustments
        
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
        
        # TODO: Use LLM to verify task completion
        # For now, basic heuristic: if all steps passed, task is complete
        
        logger.info(f"Task completion verified: {all_complete}")
        return all_complete
