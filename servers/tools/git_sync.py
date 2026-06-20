#!/usr/bin/env python3
"""
Git Sync Module - Automatic Pull/Merge/Commit/Push for Tool Operations

Provides git synchronization when memory or skill tools make changes.
Ensures changes are backed up to a remote repository if configured.

Flow:
  1. Check if git repo exists, initialize if not
  2. Check if remote exists
  3. If remote: pull → handle conflicts → commit → push
  4. If no remote: commit only (local backup)

Merge strategy: --no-edit (accept remote changes if no conflicts)
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def get_project_root() -> Path:
    """Return the project root directory."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))


def is_git_repo() -> bool:
    """Check if the current directory is a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("Failed to check git repo: %s", e)
        return False


def git_init() -> Tuple[bool, str]:
    """Initialize a git repository if it doesn't exist."""
    if is_git_repo():
        return True, "Git repository already exists."

    root = get_project_root()
    try:
        result = subprocess.run(
            ["git", "init"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False, f"Git init failed: {result.stderr[:200]}"

        logger.info("Initialized git repository at %s", root)
        return True, "Git repository initialized."
    except (subprocess.SubprocessError, OSError) as e:
        logger.error("Failed to initialize git repo: %s", e)
        return False, str(e)


def has_remote_repo() -> bool:
    """Check if a git remote is configured."""
    try:
        result = subprocess.run(
            ["git", "remote"],
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(result.stdout.strip())
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("Failed to check git remote: %s", e)
        return False


def get_current_branch() -> Optional[str]:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("Failed to get current branch: %s", e)
        return None


def run_git_command(args: list, timeout: int = 30) -> Tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error("Git command timed out: git %s", " ".join(args))
        return -1, "", "Command timed out"
    except (subprocess.SubprocessError, OSError) as e:
        logger.error("Git command failed: %s", e)
        return -1, "", str(e)


def git_pull() -> Tuple[bool, str]:
    """Pull from remote. Returns (success, message)."""
    if not has_remote_repo():
        return True, "No remote configured, skipping pull."

    branch = get_current_branch()
    if not branch:
        return False, "Could not determine current branch."

    code, out, err = run_git_command(["pull", "--no-edit"], timeout=60)
    if code == 0:
        return True, "Pull successful."
    if "no changes" in out.lower() or "already up to date" in out.lower():
        return True, "Already up to date."
    if "conflict" in err.lower() or "conflict" in out.lower():
        return False, f"Merge conflict detected: {err[:200]}"
    return False, f"Pull failed: {err[:200]}"


def git_commit(message: str) -> Tuple[bool, str]:
    """Stage and commit changes. Returns (success, message)."""
    # Stage all changes in .claude directory
    claude_dir = get_project_root() / ".claude"
    if not claude_dir.exists():
        return True, "No .claude directory to commit."

    code, out, err = run_git_command(["add", str(claude_dir)])
    if code != 0:
        return False, f"Failed to stage changes: {err[:200]}"

    # Check if there's anything to commit
    code, out, err = run_git_command(["status", "--porcelain", str(claude_dir)])
    if code != 0:
        return False, f"Failed to check status: {err[:200]}"

    if not out.strip():
        return True, "No changes to commit."

    # Commit
    code, out, err = run_git_command(["commit", "-m", message])
    if code != 0:
        if "nothing to commit" in out.lower() or "nothing to commit" in err.lower():
            return True, "No changes to commit."
        return False, f"Commit failed: {err[:200]}"

    return True, "Commit successful."


def git_push() -> Tuple[bool, str]:
    """Push to remote. Returns (success, message)."""
    if not has_remote_repo():
        return True, "No remote configured, changes committed locally only."

    branch = get_current_branch()
    if not branch:
        return False, "Could not determine current branch."

    code, out, err = run_git_command(["push", "origin", branch], timeout=60)
    if code == 0:
        return True, "Push successful."
    if "everything up-to-date" in out.lower():
        return True, "Already up to date."
    return False, f"Push failed: {err[:200]}"


def git_sync(tool_name: str, action: str, details: str = "") -> dict:
    """
    Execute full git sync: init (if needed) → pull → commit → push.

    Called after successful tool operations to backup changes.

    Args:
        tool_name: Name of the calling tool (memory, skill_manage)
        action: The action performed (add, create, edit, etc.)
        details: Additional context for commit message (truncated to 100 chars)

    Returns:
        Dict with sync results for logging/reporting
    """
    # Truncate details to prevent overly long commit messages, add ellipsis if truncated
    if details:
        details = details[:100] + "..." if len(details) > 100 else details
    else:
        details = ""
    results = {
        "tool": tool_name,
        "action": action,
        "sync_enabled": True,
        "init": None,
        "pull": None,
        "commit": None,
        "push": None,
        "success": True,
        "message": "",
    }

    # Step 0: Initialize git repo if not exists
    init_ok, init_msg = git_init()
    results["init"] = {"success": init_ok, "message": init_msg}

    if not init_ok:
        results["success"] = False
        results["message"] = f"Git sync aborted: {init_msg}"
        logger.warning("Git sync failed during init for %s/%s: %s", tool_name, action, init_msg)
        return results

    # Step 1: Pull (if remote exists)
    pull_ok, pull_msg = git_pull()
    results["pull"] = {"success": pull_ok, "message": pull_msg}

    if not pull_ok:
        results["success"] = False
        results["message"] = f"Git sync aborted: {pull_msg}"
        logger.warning("Git sync failed during pull for %s/%s: %s", tool_name, action, pull_msg)
        return results

    # Step 2: Commit
    commit_msg = f"[auto] {tool_name}: {action}"
    if details:
        commit_msg += f" - {details}"

    commit_ok, commit_msg_result = git_commit(commit_msg)
    results["commit"] = {"success": commit_ok, "message": commit_msg_result}

    if not commit_ok:
        results["success"] = False
        results["message"] = f"Git sync aborted: {commit_msg_result}"
        logger.warning("Git sync failed during commit for %s/%s: %s", tool_name, action, commit_msg_result)
        return results

    # Step 3: Push (if remote exists)
    push_ok, push_msg = git_push()
    results["push"] = {"success": push_ok, "message": push_msg}

    if not push_ok:
        results["success"] = False
        results["message"] = f"Git sync partially failed: {push_msg}"
        logger.warning("Git sync failed during push for %s/%s: %s", tool_name, action, push_msg)
        return results

    # All steps successful
    if not has_remote_repo():
        results["message"] = "Changes committed locally (no remote configured)."
    else:
        results["message"] = "Changes synced to remote."

    logger.info("Git sync completed for %s/%s", tool_name, action)
    return results