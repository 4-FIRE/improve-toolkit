#!/usr/bin/env python3
"""
Utility functions for MCP tools.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any

from runtime_paths import get_data_home, get_skills_dir


def get_home() -> Path:
    """Return the host-aware Improve Toolkit data directory."""
    return get_data_home()


def atomic_replace(src: Path, dst: Path) -> None:
    """
    Atomically replace dst with src using os.replace().
    Works on both Unix and Windows.
    """
    os.replace(src, dst)


def tool_error(message: str, success: bool = False) -> str:
    """Return a JSON error response."""
    return json.dumps({"success": success, "error": message}, ensure_ascii=False)
