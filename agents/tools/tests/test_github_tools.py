"""
agents/tools/tests/test_github_tools.py
Tests for the GitHub tools: list_org_repos, list_deleted_repos, restore_repo.

Run:
    pytest agents/tools/tests/test_github_tools.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ─────────────────────────────────────────────────────────────────
GENESIS_ROOT = Path(__file__).parent.parent.parent.parent
if str(GENESIS_ROOT) not in sys.path:
    sys.path.insert(0, str(GENESIS_ROOT))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_httpx_response(status_code: int, json_data):
    """Create a minimal mock httpx response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.url = f"https://api.github.com/mock"
    return mock_resp


# ── Imports ────────────────────────────────────────────────────────────────────

class TestGithubToolsImport:
    def test_module_importable(self):
        from agents.tools import github_tools
        assert github_tools is not None

    def test_functions_exist(self):
        from agents.tools.github_tools import (
            github_list_org_repos,
            github_list_deleted_repos,
            github_restore_repo,
        )
        assert callable(github_list_org_repos)
        assert callable(github_list_deleted_repos)
        assert callable(github_restore_repo)

    def test_tools_registered(self):
        from agents.tools.tool_registry import get_registry
        from agents.tools import github_tools  # noqa: ensure registered

        registry = get_registry()
        tool_names = {t["name"] for t in registry.list_tools()}
        assert "github_list_org_repos" in tool_names
        assert "github_list_deleted_repos" in tool_names
        assert "github_restore_repo" in tool_names


# ── github_list_org_repos ──────────────────────────────────────────────────────

class TestGithubListOrgRepos:
    def test_success_returns_repo_list(self):
        from agents.tools.github_tools import github_list_org_repos

        mock_repos = [
            {"name": "repo-a", "full_name": "MojoGlover/repo-a", "private": False, "html_url": "https://github.com/MojoGlover/repo-a"},
            {"name": "repo-b", "full_name": "MojoGlover/repo-b", "private": True, "html_url": "https://github.com/MojoGlover/repo-b"},
        ]
        mock_resp = _make_httpx_response(200, mock_repos)

        with patch("httpx.request", return_value=mock_resp):
            result = github_list_org_repos("MojoGlover", token="ghp_fake")

        assert result["success"] is True
        assert result["org"] == "MojoGlover"
        assert result["count"] == 2
        assert result["repos"][0]["name"] == "repo-a"
        assert result["repos"][1]["name"] == "repo-b"

    def test_no_token_still_calls_api(self):
        from agents.tools.github_tools import github_list_org_repos

        mock_resp = _make_httpx_response(200, [])

        with patch("httpx.request", return_value=mock_resp) as mock_req:
            result = github_list_org_repos("MojoGlover")

        assert result["success"] is True
        assert result["count"] == 0
        call_kwargs = mock_req.call_args
        # Authorization header should NOT be set when no token
        headers = call_kwargs[1].get("headers") or call_kwargs[0][2] if len(call_kwargs[0]) > 2 else {}
        assert "Authorization" not in headers

    def test_api_error_returns_failure(self):
        from agents.tools.github_tools import github_list_org_repos

        mock_resp = _make_httpx_response(404, {"message": "Not Found"})

        with patch("httpx.request", return_value=mock_resp):
            result = github_list_org_repos("nonexistent-org", token="ghp_fake")

        assert result["success"] is False
        assert "error" in result
        assert result["org"] == "nonexistent-org"

    def test_httpx_import_error(self):
        from agents.tools.github_tools import github_list_org_repos

        with patch.dict("sys.modules", {"httpx": None}):
            result = github_list_org_repos("MojoGlover", token="ghp_fake")

        assert result["success"] is False
        assert "httpx" in result["error"]

    def test_repo_type_forwarded_in_url(self):
        from agents.tools.github_tools import github_list_org_repos

        mock_resp = _make_httpx_response(200, [])

        with patch("httpx.request", return_value=mock_resp) as mock_req:
            github_list_org_repos("MojoGlover", token="ghp_fake", repo_type="public")

        called_url = mock_req.call_args[0][1]
        assert "type=public" in called_url


# ── github_list_deleted_repos ──────────────────────────────────────────────────

class TestGithubListDeletedRepos:
    def test_success_filters_destroy_events(self):
        from agents.tools.github_tools import github_list_deleted_repos

        audit_events = [
            {"action": "repo.destroy", "repo": "MojoGlover/deleted-repo", "@timestamp": "2024-01-01T00:00:00Z", "actor": "adminuser"},
            {"action": "repo.create", "repo": "MojoGlover/other-repo", "@timestamp": "2024-01-02T00:00:00Z", "actor": "adminuser"},
        ]
        mock_resp = _make_httpx_response(200, audit_events)

        with patch("httpx.request", return_value=mock_resp):
            result = github_list_deleted_repos("MojoGlover", token="ghp_fake")

        assert result["success"] is True
        assert result["org"] == "MojoGlover"
        assert result["count"] == 1
        assert result["deleted_repos"][0]["name"] == "deleted-repo"
        assert result["deleted_repos"][0]["full_name"] == "MojoGlover/deleted-repo"
        assert result["deleted_repos"][0]["actor"] == "adminuser"

    def test_no_deletions_returns_empty_list(self):
        from agents.tools.github_tools import github_list_deleted_repos

        mock_resp = _make_httpx_response(200, [])

        with patch("httpx.request", return_value=mock_resp):
            result = github_list_deleted_repos("MojoGlover", token="ghp_fake")

        assert result["success"] is True
        assert result["count"] == 0
        assert result["deleted_repos"] == []

    def test_audit_log_api_error(self):
        from agents.tools.github_tools import github_list_deleted_repos

        mock_resp = _make_httpx_response(403, {"message": "Must have admin rights to Repository."})

        with patch("httpx.request", return_value=mock_resp):
            result = github_list_deleted_repos("MojoGlover", token="ghp_fake")

        assert result["success"] is False
        assert "error" in result

    def test_limit_caps_per_page(self):
        from agents.tools.github_tools import github_list_deleted_repos

        mock_resp = _make_httpx_response(200, [])

        with patch("httpx.request", return_value=mock_resp) as mock_req:
            github_list_deleted_repos("MojoGlover", token="ghp_fake", limit=200)

        called_url = mock_req.call_args[0][1]
        # per_page is capped at 100 by min(limit, 100)
        assert "per_page=100" in called_url

    def test_deleted_at_fallback_field(self):
        from agents.tools.github_tools import github_list_deleted_repos

        audit_events = [
            {"action": "repo.destroy", "repo": "MojoGlover/old-repo", "created_at": "2024-06-01T00:00:00Z", "actor": "bot"},
        ]
        mock_resp = _make_httpx_response(200, audit_events)

        with patch("httpx.request", return_value=mock_resp):
            result = github_list_deleted_repos("MojoGlover", token="ghp_fake")

        assert result["success"] is True
        assert result["deleted_repos"][0]["deleted_at"] == "2024-06-01T00:00:00Z"


# ── github_restore_repo ────────────────────────────────────────────────────────

class TestGithubRestoreRepo:
    def test_successful_restore(self):
        from agents.tools.github_tools import github_restore_repo

        mock_resp = _make_httpx_response(200, {})

        with patch("httpx.request", return_value=mock_resp):
            result = github_restore_repo("MojoGlover", "deleted-repo", token="ghp_fake")

        assert result["success"] is True
        assert result["org"] == "MojoGlover"
        assert result["repo_name"] == "deleted-repo"
        assert "restore initiated" in result["message"]

    def test_restore_sends_correct_payload(self):
        from agents.tools.github_tools import github_restore_repo

        mock_resp = _make_httpx_response(200, {})

        with patch("httpx.request", return_value=mock_resp) as mock_req:
            github_restore_repo("MojoGlover", "my-repo", token="ghp_fake")

        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["json"] == {"repo_name": "my-repo"}

    def test_restore_uses_correct_endpoint(self):
        from agents.tools.github_tools import github_restore_repo

        mock_resp = _make_httpx_response(200, {})

        with patch("httpx.request", return_value=mock_resp) as mock_req:
            github_restore_repo("MojoGlover", "my-repo", token="ghp_fake")

        called_url = mock_req.call_args[0][1]
        assert "/orgs/MojoGlover/restore-repo" in called_url

    def test_restore_uses_post_method(self):
        from agents.tools.github_tools import github_restore_repo

        mock_resp = _make_httpx_response(200, {})

        with patch("httpx.request", return_value=mock_resp) as mock_req:
            github_restore_repo("MojoGlover", "my-repo", token="ghp_fake")

        called_method = mock_req.call_args[0][0]
        assert called_method == "POST"

    def test_repo_not_found_returns_failure(self):
        from agents.tools.github_tools import github_restore_repo

        mock_resp = _make_httpx_response(404, {"message": "Not Found"})

        with patch("httpx.request", return_value=mock_resp):
            result = github_restore_repo("MojoGlover", "nonexistent-repo", token="ghp_fake")

        assert result["success"] is False
        assert result["repo_name"] == "nonexistent-repo"
        assert "error" in result

    def test_unauthorized_returns_failure(self):
        from agents.tools.github_tools import github_restore_repo

        mock_resp = _make_httpx_response(401, {"message": "Requires authentication"})

        with patch("httpx.request", return_value=mock_resp):
            result = github_restore_repo("MojoGlover", "deleted-repo", token="bad_token")

        assert result["success"] is False
        assert result["status_code"] == 401

    def test_token_sent_as_bearer_header(self):
        from agents.tools.github_tools import github_restore_repo

        mock_resp = _make_httpx_response(200, {})

        with patch("httpx.request", return_value=mock_resp) as mock_req:
            github_restore_repo("MojoGlover", "my-repo", token="ghp_mytoken")

        headers = mock_req.call_args[1]["headers"]
        assert headers.get("Authorization") == "Bearer ghp_mytoken"
