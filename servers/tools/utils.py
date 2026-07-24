#!/usr/bin/env python3
"""
Utility functions for MCP tools.
"""

import json
from pathlib import Path

from runtime_paths import prepare_data_home


def get_home() -> Path:
    """Return the prepared shared Improve Toolkit data directory."""
    return prepare_data_home()


def tool_error(message: str, success: bool = False) -> str:
    """Return a JSON error response."""
    return json.dumps({"success": success, "error": message}, ensure_ascii=False)
