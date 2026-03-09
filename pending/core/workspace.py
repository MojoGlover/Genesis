"""
Workspace Manager - Safe execution environment for AI
"""

import docker
import os
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Manage AI workspace container for code execution and project building"""
    
    def __init__(self, container_name: str = "genesis-workspace"):
        self.container_name = container_name
        self.client = docker.from_env()
        self.container = None
        
        # Safety limits
        self.max_execution_time = 300  # 5 minutes
        self.max_output_size = 1024 * 1024  # 1MB
        
    def ensure_running(self) -> bool:
        """Ensure workspace container is running"""
        try:
            self.container = self.client.containers.get(self.container_name)
            if self.container.status != "running":
                self.container.start()
                time.sleep(2)
            return True
        except docker.errors.NotFound:
            logger.error(f"Workspace container '{self.container_name}' not found. Run docker-compose up -d")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to workspace: {e}")
            return False
    
    def execute(self, command: str, workdir: str = "/workspace") -> Dict[str, Any]:
        """Execute command in workspace"""
        if not self.ensure_running():
            return {"exit_code": -1, "stdout": "", "stderr": "Workspace not available"}
        
        try:
            exec_result = self.container.exec_run(
                cmd=f"bash -c 'cd {workdir} && {command}'",
                demux=True,
                
            )
            
            exit_code = exec_result.exit_code
            stdout = exec_result.output[0].decode() if exec_result.output[0] else ""
            stderr = exec_result.output[1].decode() if exec_result.output[1] else ""
            
            if len(stdout) > self.max_output_size:
                stdout = stdout[:self.max_output_size] + "\n... (output truncated)"
            if len(stderr) > self.max_output_size:
                stderr = stderr[:self.max_output_size] + "\n... (output truncated)"
            
            return {
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "success": exit_code == 0
            }
            
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "success": False
            }
    
    def write_file(self, path: str, content: str) -> Dict[str, Any]:
        """Write content to file in workspace"""
        if not self.ensure_running():
            return {"success": False, "error": "Workspace not available"}
        
        try:
            escaped_content = content.replace("'", "'\\''")
            cmd = f"cat > {path} << 'EOFMARKER'\n{content}\nEOFMARKER"
            
            result = self.execute(cmd)
            return {
                "success": result["success"],
                "path": path,
                "error": result["stderr"] if not result["success"] else None
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def read_file(self, path: str) -> Dict[str, Any]:
        """Read file from workspace"""
        result = self.execute(f"cat {path}")
        return {
            "success": result["success"],
            "content": result["stdout"],
            "error": result["stderr"] if not result["success"] else None
        }
    
    def list_directory(self, path: str = "/workspace") -> Dict[str, Any]:
        """List directory contents"""
        result = self.execute(f"ls -lah {path}")
        return {
            "success": result["success"],
            "listing": result["stdout"],
            "error": result["stderr"] if not result["success"] else None
        }
    
    def install_package(self, package: str, language: str = "python") -> Dict[str, Any]:
        """Install package in workspace"""
        if language == "python":
            cmd = f"pip install {package}"
        elif language == "node":
            cmd = f"npm install {package}"
        else:
            return {"success": False, "error": f"Unsupported language: {language}"}
        
        result = self.execute(cmd)
        return {
            "success": result["success"],
            "output": result["stdout"],
            "error": result["stderr"] if not result["success"] else None
        }
    
    def git_clone(self, repo_url: str, destination: str = None) -> Dict[str, Any]:
        """Clone git repository"""
        dest = destination or "/workspace/projects"
        result = self.execute(f"git clone {repo_url} {dest}")
        return {
            "success": result["success"],
            "output": result["stdout"],
            "error": result["stderr"] if not result["success"] else None
        }
    
    def cleanup(self, path: str = "/workspace/tmp/*") -> Dict[str, Any]:
        """Clean up temporary files"""
        result = self.execute(f"rm -rf {path}")
        return {"success": result["success"]}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get workspace container stats"""
        if not self.ensure_running():
            return {}
        
        try:
            stats = self.container.stats(stream=False)
            return {
                "cpu_usage": stats.get("cpu_stats", {}),
                "memory_usage": stats.get("memory_stats", {}),
                "status": self.container.status
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}


workspace = WorkspaceManager()
