"""
Autonomous Agent Loop - GENESIS Brain

This is the main autonomous loop that plans, executes, and iterates
until tasks are complete.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

from core.planner import TaskPlanner
from core.executor import ToolExecutor
from core.mission import load_mission

logger = logging.getLogger(__name__)


class AgentState(Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    REFLECTING = "reflecting"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class AgentContext:
    """Current context of agent's work"""
    task: str
    state: AgentState
    plan: List[Dict[str, Any]]
    execution_history: List[Dict[str, Any]]
    iterations: int
    max_iterations: int = 50


class AutonomousAgent:
    """
    Main autonomous agent that can:
    - Break down tasks into steps
    - Execute steps using available tools
    - Reflect on results and adjust
    - Iterate until task complete
    """
    
    def __init__(self, model_name: str = "gpt-4", max_iterations: int = 50):
        mission_data = load_mission()
        self.mission = mission_data if isinstance(mission_data, dict) else {"content": mission_data}
        self.planner = TaskPlanner(model_name=model_name)
        self.executor = ToolExecutor()
        self.max_iterations = max_iterations
        
        logger.info("Agent initialized with mission")
    
    def run(self, task: str) -> Dict[str, Any]:
        """
        Main autonomous loop
        
        Args:
            task: High-level task to accomplish
            
        Returns:
            Dict with results, history, and metadata
        """
        context = AgentContext(
            task=task,
            state=AgentState.PLANNING,
            plan=[],
            execution_history=[],
            iterations=0,
            max_iterations=self.max_iterations
        )
        
        logger.info(f"Starting task: {task}")
        
        try:
            while context.state != AgentState.COMPLETE and context.iterations < context.max_iterations:
                context.iterations += 1
                logger.info(f"Iteration {context.iterations}/{context.max_iterations} - State: {context.state.value}")
                
                if context.state == AgentState.PLANNING:
                    context = self._planning_step(context)
                elif context.state == AgentState.EXECUTING:
                    context = self._execution_step(context)
                elif context.state == AgentState.REFLECTING:
                    context = self._reflection_step(context)
                
                # Safety check
                if context.iterations >= context.max_iterations:
                    logger.warning("Max iterations reached")
                    context.state = AgentState.ERROR
                    break
            
            return self._format_results(context)
            
        except Exception as e:
            logger.error(f"Agent error: {e}")
            context.state = AgentState.ERROR
            return self._format_results(context, error=str(e))
    
    def _planning_step(self, context: AgentContext) -> AgentContext:
        """Create or update plan based on current state"""
        logger.info("Planning step...")

        # Generate plan if we don't have one
        if not context.plan:
            context.plan = self.planner.create_plan(
                task=context.task,
                mission=self.mission,
                available_tools=self.executor.get_available_tools(),
                tool_descriptions=self.executor.get_tool_descriptions(),
            )
            logger.info(f"Created plan with {len(context.plan)} steps")

        # Move to execution
        context.state = AgentState.EXECUTING
        return context
    
    def _execution_step(self, context: AgentContext) -> AgentContext:
        """Execute next step in plan"""
        logger.info("Execution step...")
        
        # Get next unfinished step
        next_step = self._get_next_step(context.plan)
        
        if not next_step:
            # All steps complete
            context.state = AgentState.REFLECTING
            return context
        
        logger.info(f"Executing: {next_step.get('action', 'unknown')}")
        
        # Execute the step
        result = self.executor.execute(
            action=next_step.get("action"),
            parameters=next_step.get("parameters", {}),
            context=context.execution_history
        )
        
        # Record result
        context.execution_history.append({
            "step": next_step,
            "result": result,
            "iteration": context.iterations
        })
        
        # Update step status
        next_step["status"] = "complete" if result.get("success") else "failed"
        next_step["result"] = result
        
        # If step failed, go to reflection
        if not result.get("success"):
            logger.warning(f"Step failed: {result.get('error')}")
            context.state = AgentState.REFLECTING
        
        return context
    
    def _reflection_step(self, context: AgentContext) -> AgentContext:
        """Reflect on progress and decide next action"""
        logger.info("Reflection step...")
        
        # Check if task is complete
        if self._is_task_complete(context):
            logger.info("Task complete!")
            context.state = AgentState.COMPLETE
            return context
        
        # Check if we need to replan
        failed_steps = [s for s in context.plan if s.get("status") == "failed"]
        
        if failed_steps:
            logger.info(f"Replanning due to {len(failed_steps)} failed steps")
            # Create new plan based on what we've learned
            context.plan = self.planner.replan(
                original_task=context.task,
                original_plan=context.plan,
                execution_history=context.execution_history,
                mission=self.mission,
                tool_descriptions=self.executor.get_tool_descriptions(),
            )
            context.state = AgentState.EXECUTING
        else:
            # Continue executing
            context.state = AgentState.EXECUTING
        
        return context
    
    def _get_next_step(self, plan: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Get next step to execute from plan"""
        for step in plan:
            if step.get("status") != "complete":
                return step
        return None
    
    def _is_task_complete(self, context: AgentContext) -> bool:
        """Determine if task is complete based on plan and execution"""
        # All planned steps complete
        all_complete = all(s.get("status") == "complete" for s in context.plan)
        
        if not all_complete:
            return False
        
        # Ask planner to verify task completion
        return self.planner.verify_completion(
            task=context.task,
            plan=context.plan,
            execution_history=context.execution_history
        )
    
    def _format_results(self, context: AgentContext, error: str = None) -> Dict[str, Any]:
        """Format final results"""
        return {
            "task": context.task,
            "status": context.state.value,
            "iterations": context.iterations,
            "plan": context.plan,
            "execution_history": context.execution_history,
            "success": context.state == AgentState.COMPLETE,
            "error": error
        }
