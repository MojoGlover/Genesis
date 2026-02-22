"""RunPod Worker - execute jobs on serverless GPU endpoints."""
from __future__ import annotations
import os
import time
import logging
from typing import Any, Dict, Optional
from .endpoints import EndpointConfig, PRESET_ENDPOINTS

logger = logging.getLogger(__name__)


class RunPodWorker:
    """
    Execute tasks on RunPod serverless GPU endpoints.
    
    Usage:
        worker = RunPodWorker(api_key="rp_...")
        result = worker.run("stable_diffusion", {"prompt": "a cat on mars"})
    """

    POLL_INTERVAL = 2  # seconds between status polls

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("RUNPOD_API_KEY", "")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import runpod
                runpod.api_key = self.api_key
                self._client = runpod
            except ImportError:
                raise RuntimeError("Run: pip install runpod")
        return self._client

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def run(
        self,
        endpoint_name_or_id: str,
        input_data: Dict[str, Any],
        timeout: int = 300,
        poll: bool = True,
    ) -> Dict[str, Any]:
        """
        Run a job on a RunPod endpoint.
        
        endpoint_name_or_id: key from PRESET_ENDPOINTS or raw RunPod endpoint ID
        input_data: dict matching the endpoint's input schema
        timeout: max seconds to wait
        poll: if True, wait for result; if False, return job_id immediately
        
        Returns: {"success": bool, "output": any, "job_id": str, "error": str}
        """
        if not self.is_configured():
            return {"success": False, "error": "RUNPOD_API_KEY not set"}

        # Resolve endpoint ID
        endpoint_id = self._resolve_endpoint(endpoint_name_or_id)
        if not endpoint_id:
            return {"success": False, "error": f"Unknown endpoint: {endpoint_name_or_id}. Set env var or pass endpoint ID directly."}

        try:
            endpoint = self.client.Endpoint(endpoint_id)
            logger.info(f"Submitting job to {endpoint_id}: {list(input_data.keys())}")
            
            run_request = endpoint.run({"input": input_data})
            job_id = run_request.id
            logger.info(f"Job {job_id} submitted")
            
            if not poll:
                return {"success": True, "job_id": job_id, "status": "submitted"}
            
            # Poll for result
            deadline = time.time() + timeout
            while time.time() < deadline:
                status = run_request.status()
                logger.debug(f"Job {job_id} status: {status}")
                
                if status == "COMPLETED":
                    output = run_request.output()
                    return {"success": True, "job_id": job_id, "output": output, "status": "completed"}
                elif status in ("FAILED", "CANCELLED", "TIMED_OUT"):
                    return {"success": False, "job_id": job_id, "error": f"Job {status}", "status": status.lower()}
                
                time.sleep(self.POLL_INTERVAL)
            
            # Timeout
            try:
                run_request.cancel()
            except Exception:
                pass
            return {"success": False, "job_id": job_id, "error": f"Timed out after {timeout}s", "status": "timeout"}
        
        except Exception as e:
            logger.error(f"RunPod job failed: {e}")
            return {"success": False, "error": str(e)}

    def _resolve_endpoint(self, name_or_id: str) -> str:
        """Resolve a preset name or env var to an endpoint ID."""
        # Direct ID (starts with ep or is long alphanumeric)
        if len(name_or_id) > 10 and name_or_id not in PRESET_ENDPOINTS:
            return name_or_id
        
        # Preset name
        if name_or_id in PRESET_ENDPOINTS:
            cfg = PRESET_ENDPOINTS[name_or_id]
            # Try env var first
            if cfg.env_var:
                from_env = os.getenv(cfg.env_var, "")
                if from_env:
                    return from_env
            # Fall back to configured ID
            return cfg.endpoint_id
        
        # Try as env var
        from_env = os.getenv(name_or_id, "")
        return from_env

    def list_endpoints(self) -> list:
        """List available preset endpoints and their configuration status."""
        result = []
        for name, cfg in PRESET_ENDPOINTS.items():
            endpoint_id = self._resolve_endpoint(name)
            result.append({
                "name": name,
                "description": cfg.description,
                "configured": bool(endpoint_id),
                "endpoint_id": endpoint_id[:8] + "..." if endpoint_id else "not set",
            })
        return result

    def get_status(self) -> dict:
        return {
            "configured": self.is_configured(),
            "api_key": self.api_key[:8] + "..." if self.api_key else "not set",
            "endpoints": self.list_endpoints(),
        }
