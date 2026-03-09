"""
Task Execution Service - Task queue management and execution via EngineerAgent
Replaces gradio_interface.py lines 304-481
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class TaskExecutionService:
    """Manages task queue and executes tasks through EngineerAgent"""

    def __init__(self):
        self._agent = None
        self._task_queue = None
        self._init_components()

    def _init_components(self):
        """Initialize agent and task queue"""
        try:
            from agents.engineer import EngineerAgent
            self._agent = EngineerAgent(max_iterations=30)
            logger.info("EngineerAgent initialized")
        except Exception as e:
            logger.error(f"Failed to initialize EngineerAgent: {e}")

        try:
            from core.task_queue import TaskQueue
            self._task_queue = TaskQueue(max_tasks=5)
            logger.info("TaskQueue initialized")
        except Exception as e:
            logger.error(f"Failed to initialize TaskQueue: {e}")

    def add_task(self, task_info: Dict[str, Any]) -> Dict[str, Any]:
        """Add a task to the queue.

        Args:
            task_info: {"name": str, "description": str, "details": str, "estimated_file": str}

        Returns:
            {"success": bool, "task_id": str | None}
        """
        if not self._task_queue:
            return {"success": False, "task_id": None, "error": "Task queue unavailable"}

        task_dict = {
            "name": task_info.get("name", ""),
            "description": task_info.get("description", ""),
            "details": task_info.get("details", ""),
            "estimated_file": task_info.get("estimated_file", "script.py"),
        }

        result = self._task_queue.add_task(task_dict)

        if result:
            # After add_task, the task_id is set on task_dict by TaskQueue
            task_id = task_dict.get("id")
            return {"success": True, "task_id": task_id}
        else:
            return {"success": False, "task_id": None, "error": "Queue full"}

    def execute_task(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """Execute a task by ID, or the first queued/pending task.

        Returns:
            {"success": bool, "code": str, "iterations": int, "status": str, "execution_log": list}
        """
        if not self._agent:
            return {
                "success": False,
                "code": "# Agent unavailable",
                "iterations": 0,
                "status": "error",
                "execution_log": [],
            }

        if not self._task_queue:
            return {
                "success": False,
                "code": "# Task queue unavailable",
                "iterations": 0,
                "status": "error",
                "execution_log": [],
            }

        # Find the task to execute
        task = None
        if task_id:
            task = self._task_queue.get_task(task_id)
            if task and task["status"] not in ["queued", "pending"]:
                task = None

        # Fallback to most recent queued/pending task
        if not task:
            all_tasks = self._task_queue.get_all_tasks()
            pending = [t for t in all_tasks if t["status"] in ["queued", "pending"]]
            task = pending[-1] if pending else None

        if not task:
            return {
                "success": False,
                "code": "# No queued tasks",
                "iterations": 0,
                "status": "no_tasks",
                "execution_log": [],
            }

        # Update status to in_progress
        self._task_queue.update_task_status(task["id"], "in_progress")

        # Build task description for the agent
        task_description = f"{task['name']}: {task['description']}"
        if task.get("details"):
            task_description += f"\nRequirements: {task['details']}"

        filepath = f"/workspace/{task.get('estimated_file', 'script.py')}"

        # Execute with engineer agent
        result = self._agent.run_coding_task(
            task=task_description,
            filepath=filepath,
        )

        # Update task status
        final_status = "complete" if result.get("success") else "failed"
        self._task_queue.update_task_status(task["id"], final_status, result)

        return {
            "success": result.get("success", False),
            "code": result.get("final_code", "# No code generated"),
            "iterations": result.get("iterations", 0),
            "status": final_status,
            "execution_log": result.get("execution_history", []),
        }

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """Get all tasks in the queue"""
        if not self._task_queue:
            return []
        return self._task_queue.get_all_tasks()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a single task by ID"""
        if not self._task_queue:
            return None
        return self._task_queue.get_task(task_id)

    def get_task_choices(self) -> List[str]:
        """Get formatted task list for dropdown UI"""
        tasks = self.get_all_tasks()
        if not tasks:
            return ["No tasks"]
        # Newest first so the most recent task is the default selection
        return [f"{t['id']}: {t['name']} ({t['status']})" for t in reversed(tasks)]


# Singleton
_task_execution_service = None


def get_task_execution_service() -> TaskExecutionService:
    """Get or create TaskExecutionService singleton"""
    global _task_execution_service
    if _task_execution_service is None:
        _task_execution_service = TaskExecutionService()
    return _task_execution_service
