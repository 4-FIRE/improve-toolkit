#!/usr/bin/env python3
"""Resolve host-aware, project-scoped paths for Improve Toolkit."""

from __future__ import annotations

import os
from pathlib import Path


def _path_from_env(name: str) -> Path | None:
    value = os.environ.get(name)
    if not value:
        return None
    return Path(value).expanduser()


def get_host() -> str:
    """Return ``codex`` or ``claude`` for the current plugin host."""
    explicit = os.environ.get("IMPROVE_HOST", "").strip().lower()
    if explicit in {"codex", "claude"}:
        return explicit

    # PLUGIN_ROOT is a Codex-specific extension. Codex also exports the
    # CLAUDE_PLUGIN_ROOT alias, so test the Codex variable first.
    if os.environ.get("PLUGIN_ROOT"):
        return "codex"
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return "claude"
    if os.environ.get("CODEX_HOME"):
        return "codex"
    return "claude"


def get_project_dir() -> Path:
    """Return the project whose session owns the plugin state."""
    return (
        _path_from_env("IMPROVE_PROJECT_DIR")
        or _path_from_env("CLAUDE_PROJECT_DIR")
        or Path.cwd()
    )


def get_data_home(project_dir: Path | str | None = None) -> Path:
    """Return the host-specific root for memories, logs, and workbench files."""
    override = _path_from_env("IMPROVE_DATA_DIR")
    if override is not None:
        return override

    project_dir = Path(project_dir).expanduser() if project_dir is not None else get_project_dir()
    if get_host() == "codex":
        return project_dir / ".codex" / "improve-toolkit"
    return project_dir / ".claude"


def get_skills_dir(project_dir: Path | str | None = None) -> Path:
    """Return the writable skill directory discovered by the active host."""
    override = _path_from_env("IMPROVE_SKILLS_DIR")
    if override is not None:
        return override

    if get_host() == "codex":
        project_dir = Path(project_dir).expanduser() if project_dir is not None else get_project_dir()
        return project_dir / ".agents" / "skills"
    return get_data_home(project_dir) / "skills"
