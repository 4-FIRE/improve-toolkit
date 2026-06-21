#!/usr/bin/env python3
"""
Standalone tests for scripts/session_context.py — run with:
    python scripts/test_session_context.py

Stdlib only, no pytest. Runs the hook as a subprocess against a temp
CLAUDE_PROJECT_DIR (mirrors servers/test_tools.py's subprocess style).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "session_context.py"


def run_hook(workdir: Path) -> dict:
    """Run session_context.py with CLAUDE_PROJECT_DIR=workdir, return parsed JSON."""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(workdir)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_workbench_dir_created_and_path_in_context():
    workdir = Path(tempfile.mkdtemp(prefix="sc_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        expected = str((workdir / ".claude" / "workbench").resolve())
        assert expected in context, f"workbench path missing from context; expected {expected!r}"
        assert (workdir / ".claude" / "workbench").is_dir(), "workbench dir was not created"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    test_workbench_dir_created_and_path_in_context()
    print("test_workbench_dir_created_and_path_in_context: PASS")
