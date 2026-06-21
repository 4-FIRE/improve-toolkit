#!/usr/bin/env python3
"""
Tests for scripts/session_context.py — run with:
    python scripts/tests/test_session_context.py

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

SCRIPT = Path(__file__).resolve().parent.parent / "session_context.py"


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


def test_no_legacy_tmp_references():
    workdir = Path(tempfile.mkdtemp(prefix="sc_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        # The three former /tmp references must be gone.
        for legacy in ("/tmp/<task>.py", "JSON files in /tmp", "python /tmp/"):
            assert legacy not in context, f"legacy /tmp reference still present: {legacy!r}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_workbench_path_appears_in_run_guidance():
    workdir = Path(tempfile.mkdtemp(prefix="sc_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        expected = str((workdir / ".claude" / "workbench").resolve())
        # The "How to run" guidance should reference the workbench path for
        # both writing the file and executing it.
        assert context.count(expected) >= 2, (
            "workbench path should appear at least twice (write + run); "
            f"got {context.count(expected)} occurrence(s)"
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


ALL_TESTS = [
    test_workbench_dir_created_and_path_in_context,
    test_no_legacy_tmp_references,
    test_workbench_path_appears_in_run_guidance,
]


def main():
    passed = 0
    failed = 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
