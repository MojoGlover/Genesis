"""
Workspace Service - File retrieval from Docker workspace
Replaces gradio_interface.py lines 483-502 (_get_latest_code)
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Workspace file retrieval and listing"""

    def __init__(self):
        self._workspace = None
        self._init_workspace()

    def _init_workspace(self):
        """Initialize workspace reference"""
        try:
            from core.workspace import workspace
            self._workspace = workspace
            logger.info("WorkspaceService initialized")
        except Exception as e:
            logger.warning(f"Workspace unavailable: {e}")

    def get_latest_code(self) -> Dict[str, Any]:
        """Get the most recently created/modified code file from workspace"""
        if not self._workspace:
            return {"success": False, "filename": "", "content": "Workspace not available"}

        try:
            result = self._workspace.execute("ls -lt /workspace/*.py 2>/dev/null | head -5")

            if result.get("success") and result.get("stdout"):
                lines = result["stdout"].strip().split("\n")
                if lines and lines[0]:
                    latest_file = lines[0].split()[-1] if lines[0] else None

                    if latest_file:
                        code_result = self._workspace.read_file(latest_file)
                        if code_result.get("success"):
                            return {
                                "success": True,
                                "filename": latest_file,
                                "content": code_result["content"],
                            }

            # Fallback: list directory
            dir_result = self._workspace.list_directory("/workspace")
            return {
                "success": True,
                "filename": "",
                "content": dir_result.get("listing", "No files found"),
            }

        except Exception as e:
            logger.error(f"Error reading workspace code: {e}")
            return {"success": False, "filename": "", "content": f"Error: {e}"}

    def list_files(self, path: str = "/workspace") -> Dict[str, Any]:
        """List files at the given workspace path"""
        if not self._workspace:
            return {"success": False, "listing": "Workspace not available"}

        try:
            result = self._workspace.list_directory(path)
            return {
                "success": result.get("success", False),
                "listing": result.get("listing", ""),
            }
        except Exception as e:
            logger.error(f"Error listing workspace files: {e}")
            return {"success": False, "listing": f"Error: {e}"}


# Singleton
_workspace_service = None


def get_workspace_service() -> WorkspaceService:
    """Get or create WorkspaceService singleton"""
    global _workspace_service
    if _workspace_service is None:
        _workspace_service = WorkspaceService()
    return _workspace_service
