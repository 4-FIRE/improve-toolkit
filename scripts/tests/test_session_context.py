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


def run_hook(workdir: Path, host: str = "claude") -> dict:
    """Run session_context.py for a host and return parsed JSON."""
    env = dict(os.environ)
    for key in (
        "PLUGIN_ROOT",
        "IMPROVE_HOST",
        "IMPROVE_PROJECT_DIR",
        "IMPROVE_DATA_DIR",
        "IMPROVE_MEMORY_DIR",
    ):
        env.pop(key, None)
    if host == "codex":
        env.pop("CLAUDE_PROJECT_DIR", None)
        env["PLUGIN_ROOT"] = str(SCRIPT.parent.parent)
    else:
        env["CLAUDE_PROJECT_DIR"] = str(workdir)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=workdir,
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
        expected = str((workdir / ".improve-toolkit" / "workbench").resolve())
        assert expected in context, f"workbench path missing from context; expected {expected!r}"
        assert (workdir / ".improve-toolkit" / "workbench").is_dir(), "workbench dir was not created"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_no_legacy_tmp_references():
    workdir = Path(tempfile.mkdtemp(prefix="sc_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        # The resolved workbench itself normally lives under the OS temp
        # directory in this test. Remove that valid dynamic path before
        # checking for old hard-coded /tmp guidance.
        workbench = str((workdir / ".improve-toolkit" / "workbench").resolve())
        context = context.replace(workbench, "<WORKBENCH>")
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
        expected = str((workdir / ".improve-toolkit" / "workbench").resolve())
        # The "How to run" guidance should reference the workbench path for
        # both writing the file and executing it.
        assert context.count(expected) >= 2, (
            "workbench path should appear at least twice (write + run); "
            f"got {context.count(expected)} occurrence(s)"
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_codex_workbench_dir_created():
    workdir = Path(tempfile.mkdtemp(prefix="sc_codex_test_"))
    try:
        data = run_hook(workdir, host="codex")
        context = data["hookSpecificOutput"]["additionalContext"]
        expected_dir = workdir / ".improve-toolkit" / "workbench"
        assert str(expected_dir.resolve()) in context
        assert expected_dir.is_dir()
        assert "Claude Code Persona" not in context
        ignore_file = workdir / ".improve-toolkit" / ".gitignore"
        assert ignore_file.is_file()
        ignore_text = ignore_file.read_text(encoding="utf-8")
        assert "*" in ignore_text
        assert "!.gitignore" not in ignore_text
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_memory_policy_uses_one_week_gate_and_schema_source():
    workdir = Path(tempfile.mkdtemp(prefix="sc_memory_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        assert "1 week from now" in context
        assert "3 weeks" not in context
        assert "`memory` tool schema is the source of truth" in context
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_skill_work_uses_authorized_state():
    workdir = Path(tempfile.mkdtemp(prefix="sc_skills_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        assert "load `improve`" in context
        assert "source of truth for candidate and authorization states" in context
        assert "reaches the authorized state" in context
        assert "writing-for-agents" in context
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_import_has_no_runtime_side_effects():
    workdir = Path(tempfile.mkdtemp(prefix="sc_import_test_"))
    try:
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(workdir)
        result = subprocess.run(
            [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(SCRIPT.parent)!r}); import session_context"],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout == ""
        assert not (workdir / ".improve-toolkit").exists()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


ALL_TESTS = [
    test_workbench_dir_created_and_path_in_context,
    test_no_legacy_tmp_references,
    test_workbench_path_appears_in_run_guidance,
    test_codex_workbench_dir_created,
    test_memory_policy_uses_one_week_gate_and_schema_source,
    test_skill_work_uses_authorized_state,
    test_import_has_no_runtime_side_effects,
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
