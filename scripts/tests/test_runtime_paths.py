#!/usr/bin/env python3
"""Tests for shared Improve Toolkit runtime paths."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime_paths import (
    RUNTIME_GITIGNORE_LINES,
    get_data_home,
    get_host,
    get_legacy_memories_dirs,
    get_memories_dir,
    get_project_dir,
    get_skills_dir,
    prepare_data_home,
)


def test_claude_defaults():
    with tempfile.TemporaryDirectory(prefix="rp_claude_") as workdir:
        env = {
            "CLAUDE_PROJECT_DIR": workdir,
        }
        with patch.dict(os.environ, env, clear=True):
            project = Path(workdir)
            assert get_host() == "claude"
            assert get_project_dir() == project
            assert get_data_home() == project / ".improve-toolkit"
            assert get_memories_dir() == project / ".improve-toolkit" / "memories"
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
            assert get_data_home() == project / ".improve-toolkit"
            assert get_memories_dir() == project / ".improve-toolkit" / "memories"
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
                assert get_data_home() == Path(workdir) / ".improve-toolkit"
                assert get_memories_dir() == Path(workdir) / ".improve-toolkit" / "memories"
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
        assert get_memories_dir() == Path("/custom/data/memories")
        assert get_legacy_memories_dirs() == ()
        assert get_skills_dir() == Path("/custom/skills")


def test_memory_override():
    env = {
        "IMPROVE_PROJECT_DIR": "/project",
        "IMPROVE_MEMORY_DIR": "/shared/memory",
    }
    with patch.dict(os.environ, env, clear=True):
        assert get_memories_dir() == Path("/shared/memory")
        assert get_legacy_memories_dirs() == ()


def test_prepare_data_home_creates_narrow_gitignore():
    with tempfile.TemporaryDirectory(prefix="rp_prepare_") as workdir:
        env = {"IMPROVE_PROJECT_DIR": workdir}
        data_home = Path(workdir) / ".improve-toolkit"
        data_home.mkdir()
        ignore_path = data_home / ".gitignore"
        ignore_path.write_text("# user rule\n/custom/\n", encoding="utf-8")

        with patch.dict(os.environ, env, clear=True):
            assert prepare_data_home() == data_home
            first = ignore_path.read_text(encoding="utf-8")
            prepare_data_home()
            second = ignore_path.read_text(encoding="utf-8")

        assert first == second
        assert "# user rule" in first
        assert "/custom/" in first
        for line in RUNTIME_GITIGNORE_LINES:
            assert line in first.splitlines()
        assert "/memories/" not in first.splitlines()
        assert ".improve-toolkit/" not in first.splitlines()


def test_repository_runtime_gitignore_matches_generated_rules():
    repository_root = Path(__file__).resolve().parents[2]
    ignore_path = repository_root / ".improve-toolkit" / ".gitignore"
    assert tuple(ignore_path.read_text(encoding="utf-8").splitlines()) == (
        RUNTIME_GITIGNORE_LINES
    )


ALL_TESTS = [
    test_claude_defaults,
    test_codex_defaults,
    test_codex_plugin_root_detection,
    test_path_overrides,
    test_memory_override,
    test_prepare_data_home_creates_narrow_gitignore,
    test_repository_runtime_gitignore_matches_generated_rules,
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
