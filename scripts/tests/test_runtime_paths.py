#!/usr/bin/env python3
"""Tests for host-aware Improve Toolkit runtime paths."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime_paths import get_data_home, get_host, get_project_dir, get_skills_dir


def test_claude_defaults():
    with tempfile.TemporaryDirectory(prefix="rp_claude_") as workdir:
        env = {
            "CLAUDE_PROJECT_DIR": workdir,
        }
        with patch.dict(os.environ, env, clear=True):
            project = Path(workdir)
            assert get_host() == "claude"
            assert get_project_dir() == project
            assert get_data_home() == project / ".claude"
            assert get_skills_dir() == project / ".claude" / "skills"


def test_codex_defaults():
    with tempfile.TemporaryDirectory(prefix="rp_codex_") as workdir:
        env = {
            "IMPROVE_HOST": "codex",
            "IMPROVE_PROJECT_DIR": workdir,
        }
        with patch.dict(os.environ, env, clear=True):
            project = Path(workdir)
            assert get_host() == "codex"
            assert get_project_dir() == project
            assert get_data_home() == project / ".codex" / "improve-toolkit"
            assert get_skills_dir() == project / ".agents" / "skills"


def test_codex_plugin_root_detection():
    with tempfile.TemporaryDirectory(prefix="rp_plugin_") as workdir:
        env = {
            "PLUGIN_ROOT": "/plugin",
        }
        with patch.dict(os.environ, env, clear=True):
            original_cwd = Path.cwd()
            try:
                os.chdir(workdir)
                assert get_host() == "codex"
                assert get_project_dir() == Path(workdir)
                assert get_data_home() == Path(workdir) / ".codex" / "improve-toolkit"
            finally:
                os.chdir(original_cwd)


def test_path_overrides():
    env = {
        "IMPROVE_HOST": "codex",
        "IMPROVE_PROJECT_DIR": "/project",
        "IMPROVE_DATA_DIR": "/custom/data",
        "IMPROVE_SKILLS_DIR": "/custom/skills",
    }
    with patch.dict(os.environ, env, clear=True):
        assert get_project_dir() == Path("/project")
        assert get_data_home() == Path("/custom/data")
        assert get_skills_dir() == Path("/custom/skills")


ALL_TESTS = [
    test_claude_defaults,
    test_codex_defaults,
    test_codex_plugin_root_detection,
    test_path_overrides,
]


def main():
    passed = 0
    failed = 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test.__name__}: {exc}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
