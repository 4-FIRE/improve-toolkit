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


def test_runtime_data_home_created_without_workbench():
    workdir = Path(tempfile.mkdtemp(prefix="sc_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        data_home = workdir / ".improve-toolkit"
        assert data_home.is_dir()
        assert (data_home / ".gitignore").is_file()
        assert not (data_home / "workbench").exists()
        assert "workbench" not in context.lower()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_code_execution_guidance_removed():
    workdir = Path(tempfile.mkdtemp(prefix="sc_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        removed_phrases = (
            "Coding Agent Persona",
            "Solving with code",
            "Use code instead of mental math",
            "prefer running code",
            "How to run",
            "Process isolation",
            "Working loop",
            "Error handling",
            "Output control",
            "python -c",
            "workbench",
        )
        for phrase in removed_phrases:
            assert phrase.lower() not in context.lower(), f"removed guidance still present: {phrase!r}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_codex_runtime_data_home_created():
    workdir = Path(tempfile.mkdtemp(prefix="sc_codex_test_"))
    try:
        data = run_hook(workdir, host="codex")
        context = data["hookSpecificOutput"]["additionalContext"]
        data_home = workdir / ".improve-toolkit"
        assert data_home.is_dir()
        assert not (data_home / "workbench").exists()
        assert "Claude Code Persona" not in context
        ignore_file = data_home / ".gitignore"
        assert ignore_file.is_file()
        ignore_text = ignore_file.read_text(encoding="utf-8")
        assert "*" in ignore_text
        assert "!.gitignore" not in ignore_text
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_context_exposes_memory_tools_without_global_persona():
    workdir = Path(tempfile.mkdtemp(prefix="sc_memory_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        assert "Improve Toolkit" in context
        assert "`memory_recall`" in context
        assert "`memory`" in context
        assert "<EXTREMELY_IMPORTANT>" not in context
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_hosts_receive_identical_plugin_guidance():
    workdir = Path(tempfile.mkdtemp(prefix="sc_skills_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        codex = run_hook(workdir, host="codex")
        assert context == codex["hookSpecificOutput"]["additionalContext"]
        assert "`improve`" in context
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
    test_runtime_data_home_created_without_workbench,
    test_code_execution_guidance_removed,
    test_codex_runtime_data_home_created,
    test_context_exposes_memory_tools_without_global_persona,
    test_hosts_receive_identical_plugin_guidance,
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
