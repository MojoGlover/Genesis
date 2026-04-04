"""
GitHub Tools Module
Provides GitHub API capabilities: list repos, list deleted repos, restore deleted repos.
"""

import logging
from typing import Dict, Any, Optional, List

from .tool_registry import register_tool

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def _github_request(
    method: str,
    path: str,
    token: Optional[str],
    json_body: Optional[dict] = None,
) -> Dict[str, Any]:
    """Internal helper for GitHub REST API requests."""
    try:
        import httpx

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GENESIS-Agent/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        url = f"{GITHUB_API_BASE}{path}"
        resp = httpx.request(
            method,
            url,
            headers=headers,
            json=json_body,
            timeout=30,
            follow_redirects=True,
        )

        data = None
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        return {
            "success": resp.status_code < 400,
            "status_code": resp.status_code,
            "data": data,
        }
    except ImportError:
        return {"success": False, "error": "httpx not installed. Run: pip install httpx"}
    except Exception as e:
        logger.error(f"GitHub API error: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="github_list_org_repos",
    description="List repositories for a GitHub organization.",
    category="github",
    examples=[
        "github_list_org_repos('MojoGlover', token='ghp_...')",
        "github_list_org_repos('my-org', repo_type='public', token='ghp_...')",
    ],
)
def github_list_org_repos(
    org: str,
    token: Optional[str] = None,
    repo_type: str = "all",
    per_page: int = 100,
) -> Dict[str, Any]:
    """
    List repositories in a GitHub organization.

    Args:
        org: GitHub organization name
        token: GitHub personal access token (required for private repos)
        repo_type: Type of repos to list ('all', 'public', 'private', 'forks', 'sources', 'member')
        per_page: Number of results per page (max 100)

    Returns:
        dict with 'success', 'org', 'count', 'repos', and optional 'error'
    """
    result = _github_request(
        "GET",
        f"/orgs/{org}/repos?type={repo_type}&per_page={per_page}",
        token,
    )
    if not result["success"]:
        data = result.get("data", {})
        error_msg = (
            result.get("error")
            or (data.get("message", "Unknown error") if isinstance(data, dict) else str(data))
        )
        return {
            "success": False,
            "org": org,
            "error": error_msg,
            "status_code": result.get("status_code"),
        }

    repos = result["data"] if isinstance(result["data"], list) else []
    return {
        "success": True,
        "org": org,
        "count": len(repos),
        "repos": [
            {
                "name": r.get("name"),
                "full_name": r.get("full_name"),
                "private": r.get("private"),
                "url": r.get("html_url"),
            }
            for r in repos
        ],
    }


@register_tool(
    name="github_list_deleted_repos",
    description=(
        "List recently deleted repositories in a GitHub organization via the audit log. "
        "Requires a token with 'read:audit_log' scope."
    ),
    category="github",
    examples=[
        "github_list_deleted_repos('MojoGlover', token='ghp_...')",
        "github_list_deleted_repos('my-org', token='ghp_...', limit=50)",
    ],
)
def github_list_deleted_repos(
    org: str,
    token: str,
    limit: int = 30,
) -> Dict[str, Any]:
    """
    List recently deleted repositories in a GitHub organization.
    Uses the organization audit log API (requires a token with 'read:audit_log' scope).
    Repositories are only visible in the audit log for 90 days after deletion.

    Args:
        org: GitHub organization name
        token: GitHub personal access token with 'read:audit_log' scope
        limit: Maximum number of deletion events to return (default 30)

    Returns:
        dict with 'success', 'org', 'count', 'deleted_repos', and optional 'error'
    """
    result = _github_request(
        "GET",
        f"/orgs/{org}/audit-log?phrase=action:repo.destroy&per_page={min(limit, 100)}",
        token,
    )
    if not result["success"]:
        data = result.get("data", {})
        error_msg = (
            result.get("error")
            or (data.get("message", "Unknown error") if isinstance(data, dict) else str(data))
        )
        return {
            "success": False,
            "org": org,
            "error": error_msg,
            "status_code": result.get("status_code"),
        }

    events = result["data"] if isinstance(result["data"], list) else []
    deleted_repos = [
        {
            "name": e.get("repo", "").split("/")[-1] if e.get("repo") else e.get("name", "unknown"),
            "full_name": e.get("repo", ""),
            "deleted_at": e.get("@timestamp") or e.get("created_at"),
            "actor": e.get("actor"),
        }
        for e in events
        if e.get("action") == "repo.destroy"
    ]

    return {
        "success": True,
        "org": org,
        "count": len(deleted_repos),
        "deleted_repos": deleted_repos,
    }


@register_tool(
    name="github_restore_repo",
    description=(
        "Restore a recently deleted repository in a GitHub organization. "
        "Requires organization admin access and must be within 90 days of deletion."
    ),
    category="github",
    examples=[
        "github_restore_repo('MojoGlover', 'my-deleted-repo', token='ghp_...')",
    ],
)
def github_restore_repo(
    org: str,
    repo_name: str,
    token: str,
) -> Dict[str, Any]:
    """
    Restore a recently deleted repository in a GitHub organization.
    Requires organization admin access.
    Only repositories deleted within the last 90 days can be restored.

    Args:
        org: GitHub organization name
        repo_name: Name of the deleted repository to restore (without the org prefix)
        token: GitHub personal access token with 'admin:org' scope

    Returns:
        dict with 'success', 'org', 'repo_name', 'message', and optional 'error'
    """
    result = _github_request(
        "POST",
        f"/orgs/{org}/restore-repo",
        token,
        json_body={"repo_name": repo_name},
    )

    if result["success"]:
        return {
            "success": True,
            "org": org,
            "repo_name": repo_name,
            "message": f"Repository '{repo_name}' restore initiated successfully.",
            "status_code": result["status_code"],
        }

    data = result.get("data", {})
    error_msg = (
        result.get("error")
        or (data.get("message", "Unknown error") if isinstance(data, dict) else str(data))
    )
    return {
        "success": False,
        "org": org,
        "repo_name": repo_name,
        "error": error_msg,
        "status_code": result.get("status_code"),
    }
