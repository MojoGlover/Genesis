"""
Task Queue Management
Handles task storage, execution queue, and history
"""

import logging
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class TaskQueue:
    """Manages pending tasks and execution history"""
    
    def __init__(self, max_tasks: int = 5):
        self.max_tasks = max_tasks
        self.tasks: List[Dict[str, Any]] = []
        self.history_dir = Path.home() / "ai" / "genesis" / ".history"
        self.history_dir.mkdir(exist_ok=True)
        logger.info(f"TaskQueue initialized (max: {max_tasks})")
    
    def add_task(self, task: Dict[str, Any]) -> Optional[str]:
        """Add task to queue if space available.

        Returns:
            task_id on success, None on failure.
            Backward-compatible: non-empty string is truthy, None is falsy.
        """
        if len(self.tasks) >= self.max_tasks:
            logger.warning(f"Queue full ({self.max_tasks} tasks)")
            return None

        # Generate unique ID
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        task["id"] = task_id
        task["status"] = "pending"
        task["added_at"] = datetime.now().isoformat()

        self.tasks.append(task)
        logger.info(f"Added task: {task_id}")
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task by ID"""
        for task in self.tasks:
            if task["id"] == task_id:
                return task
        return None
    
    def remove_task(self, task_id: str) -> bool:
        """Remove task from queue"""
        for i, task in enumerate(self.tasks):
            if task["id"] == task_id:
                self.tasks.pop(i)
                logger.info(f"Removed task: {task_id}")
                return True
        return False
    
    def update_task_status(self, task_id: str, status: str, result: Optional[Dict] = None):
        """Update task execution status"""
        task = self.get_task(task_id)
        if task:
            task["status"] = status
            if result:
                task["result"] = result
            task["updated_at"] = datetime.now().isoformat()
    
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """Get all tasks in queue"""
        return self.tasks.copy()
    
    def is_full(self) -> bool:
        """Check if queue is full"""
        return len(self.tasks) >= self.max_tasks
    
    def save_to_history(self, task: Dict[str, Any], code: str, filepath: str):
        """Save completed task and code to history"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            task_name = task.get('name', 'unnamed').replace(' ', '_').lower()
            
            # Save code file
            code_file = self.history_dir / f"{timestamp}_{task_name}.py"
            code_file.write_text(code)
            
            # Save metadata
            metadata = {
                "task": task,
                "filepath": filepath,
                "saved_at": datetime.now().isoformat(),
                "code_file": str(code_file)
            }
            
            meta_file = self.history_dir / f"{timestamp}_{task_name}.json"
            meta_file.write_text(json.dumps(metadata, indent=2))
            
            logger.info(f"Saved to history: {code_file}")
            return str(code_file)
            
        except Exception as e:
            logger.error(f"Failed to save history: {e}")
            return None
    
    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent history"""
        try:
            history_files = sorted(
                self.history_dir.glob("*.json"),
                key=os.path.getmtime,
                reverse=True
            )[:limit]
            
            history = []
            for file in history_files:
                try:
                    metadata = json.loads(file.read_text())
                    history.append(metadata)
                except Exception as e:
                    logger.error(f"Error reading {file}: {e}")
            
            return history
            
        except Exception as e:
            logger.error(f"Failed to get history: {e}")
            return []
