"""
runpod_tool.py — RunPod GPU cloud integration for Goldberg.

Five actions:
  list_pods()                         — list all pods in the account
  get_pod(pod_id)                     — get status/details for one pod
  create_pod(gpu_type, image, env)    — spin up a new on-demand pod
  stop_pod(pod_id)                    — stop (pause) a pod (keeps disk, no GPU charge)
  terminate_pod(pod_id)               — permanently delete a pod

API key: reads RUNPOD_API_KEY env var.
GraphQL endpoint: https://api.runpod.io/graphql?api_key={key}
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_GRAPHQL_URL = "https://api.runpod.io/graphql"
_TIMEOUT = httpx.Timeout(30.0)


def _api_key() -> str:
    key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not key:
        raise RuntimeError("RUNPOD_API_KEY not set")
    return key


def _gql(query: str, variables: dict | None = None) -> dict:
    resp = httpx.post(
        _GRAPHQL_URL,
        params={"api_key": _api_key()},
        json={"query": query, "variables": variables or {}},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data.get("data", {})


# ── Public functions ──────────────────────────────────────────────────────────

def list_pods() -> dict:
    """List all pods in the RunPod account."""
    q = """
    query {
      myself {
        pods {
          id
          name
          desiredStatus
          runtime {
            uptimeInSeconds
            gpus { id gpuUtilPercent memoryUtilPercent }
          }
          machine { gpuDisplayName podHostId }
          imageName
          costPerHr
        }
      }
    }
    """
    try:
        data = _gql(q)
        pods = data.get("myself", {}).get("pods", [])
        return {"ok": True, "pods": pods, "count": len(pods)}
    except Exception as e:
        logger.error("[runpod] list_pods error: %s", e)
        return {"ok": False, "error": str(e)}


def get_pod(pod_id: str) -> dict:
    """Get status and details for a single pod."""
    q = """
    query GetPod($id: String!) {
      pod(input: { podId: $id }) {
        id
        name
        desiredStatus
        runtime {
          uptimeInSeconds
          ports { ip isIpPublic privatePort publicPort type }
          gpus { id gpuUtilPercent memoryUtilPercent }
        }
        machine { gpuDisplayName podHostId }
        imageName
        costPerHr
        env { key value }
      }
    }
    """
    try:
        data = _gql(q, {"id": pod_id})
        pod = data.get("pod")
        if not pod:
            return {"ok": False, "error": f"Pod {pod_id} not found"}
        return {"ok": True, "pod": pod}
    except Exception as e:
        logger.error("[runpod] get_pod error: %s", e)
        return {"ok": False, "error": str(e)}


def create_pod(
    gpu_type: str = "NVIDIA GeForce RTX 4090",
    image: str = "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04",
    env: dict[str, str] | None = None,
    name: str = "goldberg-pod",
    disk_gb: int = 20,
    container_disk_gb: int = 20,
    ports: str = "8888/http",
) -> dict:
    """
    Create an on-demand RunPod GPU pod.

    gpu_type: GPU name string, e.g. "NVIDIA GeForce RTX 4090"
    image: Docker image to run
    env: dict of env vars to pass into the pod
    name: pod display name
    disk_gb: persistent volume size in GB
    container_disk_gb: container disk size in GB
    ports: exposed ports, e.g. "8888/http,22/tcp"
    """
    env_list = [{"key": k, "value": v} for k, v in (env or {}).items()]

    q = """
    mutation CreatePod($input: PodFindAndDeployOnDemandInput!) {
      podFindAndDeployOnDemand(input: $input) {
        id
        name
        desiredStatus
        imageName
        machine { gpuDisplayName podHostId }
        costPerHr
      }
    }
    """
    variables = {
        "input": {
            "cloudType": "SECURE",
            "gpuCount": 1,
            "gpuTypeId": gpu_type,
            "name": name,
            "imageName": image,
            "containerDiskInGb": container_disk_gb,
            "volumeInGb": disk_gb,
            "ports": ports,
            "env": env_list,
        }
    }
    try:
        data = _gql(q, variables)
        pod = data.get("podFindAndDeployOnDemand")
        if not pod:
            return {"ok": False, "error": "No pod returned — GPU may be unavailable"}
        return {"ok": True, "pod": pod}
    except Exception as e:
        logger.error("[runpod] create_pod error: %s", e)
        return {"ok": False, "error": str(e)}


def stop_pod(pod_id: str) -> dict:
    """
    Stop a pod (pauses it — keeps disk, stops GPU billing).
    The pod can be restarted later without data loss.
    """
    q = """
    mutation StopPod($id: String!) {
      podStop(input: { podId: $id }) {
        id
        desiredStatus
      }
    }
    """
    try:
        data = _gql(q, {"id": pod_id})
        pod = data.get("podStop")
        return {"ok": True, "pod": pod}
    except Exception as e:
        logger.error("[runpod] stop_pod error: %s", e)
        return {"ok": False, "error": str(e)}


def terminate_pod(pod_id: str) -> dict:
    """
    Permanently terminate and delete a pod. All data is lost.
    Use stop_pod() if you want to pause and resume later.
    """
    q = """
    mutation TerminatePod($id: String!) {
      podTerminate(input: { podId: $id })
    }
    """
    try:
        _gql(q, {"id": pod_id})
        return {"ok": True, "terminated": pod_id}
    except Exception as e:
        logger.error("[runpod] terminate_pod error: %s", e)
        return {"ok": False, "error": str(e)}
