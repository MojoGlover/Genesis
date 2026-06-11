"""
git_tool.py — Git operations for BlackZero agents.

Wraps common git commands with safe defaults.
Force pushes and hard resets require explicit confirmation.
"""
from __future__ import annotations

import logging
from pathlib import Path
from agent.tools.shell import run, format_result

logger = logging.getLogger(__name__)


def status(repo_path: str = ".") -> str:
    return format_result(run("git status", cwd=repo_path))


def diff(repo_path: str = ".", staged: bool = False) -> str:
    cmd = "git diff --staged" if staged else "git diff"
    return format_result(run(cmd, cwd=repo_path))


def log(repo_path: str = ".", n: int = 10) -> str:
    return format_result(run(f"git log --oneline -{n}", cwd=repo_path))


def add(paths: str | list[str], repo_path: str = ".") -> str:
    if isinstance(paths, list):
        paths = " ".join(f'"{p}"' for p in paths)
    return format_result(run(f"git add {paths}", cwd=repo_path))


def commit(message: str, repo_path: str = ".") -> str:
    # Always co-author with Claude
    full_msg = f"{message}\n\nCo-Authored-By: Computer Black Agent <noreply@computerblack.ai>"
    return format_result(run(f'git commit -m "{full_msg}"', cwd=repo_path))


def push(repo_path: str = ".", branch: str = "main", force: bool = False) -> str:
    if force:
        return format_result(run(f"git push --force origin {branch}", cwd=repo_path, confirm_destructive=True))
    return format_result(run(f"git push origin {branch}", cwd=repo_path))


def pull(repo_path: str = ".", rebase: bool = True) -> str:
    flag = "--rebase" if rebase else ""
    return format_result(run(f"git pull {flag}", cwd=repo_path))


def fetch(repo_path: str = ".") -> str:
    return format_result(run("git fetch origin", cwd=repo_path))


def branch(repo_path: str = ".") -> str:
    return format_result(run("git branch -a", cwd=repo_path))


def clone(url: str, dest: str, repo_path: str = ".") -> str:
    return format_result(run(f"git clone {url} {dest}", cwd=repo_path, timeout=120))
