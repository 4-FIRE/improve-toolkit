#!/usr/bin/env python3
"""Tests for shared Improve Toolkit runtime paths."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime_paths import (
    RUNTIME_GITIGNORE_LOCAL,
    RUNTIME_GITIGNORE_TRACKED,
    get_data_home,
    get_host,
    get_legacy_memories_dirs,
    get_memories_dir,
    get_project_dir,
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


def test_pi_overrides_inherited_host_environment():
    with tempfile.TemporaryDirectory(prefix="rp_pi_") as workdir:
        env = {
            "IMPROVE_HOST": "pi",
            "IMPROVE_PROJECT_DIR": workdir,
            "CLAUDE_PROJECT_DIR": "/other-project",
            "PLUGIN_ROOT": "/codex-plugin",
        }
        with patch.dict(os.environ, env, clear=True):
            assert get_host() == "pi"
            assert get_project_dir() == Path(workdir)
            assert get_memories_dir() == Path(workdir) / ".improve-toolkit" / "memories"


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
    }
    with patch.dict(os.environ, env, clear=True):
        assert get_project_dir() == Path("/project")
        assert get_data_home() == Path("/custom/data")
        assert get_memories_dir() == Path("/custom/data/memories")
        assert get_legacy_memories_dirs() == ()


def test_memory_override():
    env = {
        "IMPROVE_PROJECT_DIR": "/project",
        "IMPROVE_MEMORY_DIR": "/shared/memory",
    }
    with patch.dict(os.environ, env, clear=True):
        assert get_memories_dir() == Path("/shared/memory")
        assert get_legacy_memories_dirs() == ()


def test_prepare_data_home_creates_local_gitignore():
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
        lines = first.splitlines()
        for line in RUNTIME_GITIGNORE_LOCAL:
            assert line in lines
        assert "*" in lines
        assert "!.gitignore" not in lines
        assert "/memories/" not in lines
        assert ".improve-toolkit/" not in lines


def test_prepare_data_home_track_memories_override():
    with tempfile.TemporaryDirectory(prefix="rp_track_") as workdir:
        env = {"IMPROVE_PROJECT_DIR": workdir, "IMPROVE_TRACK_MEMORIES": "1"}
        with patch.dict(os.environ, env, clear=True):
            data_home = prepare_data_home()
            lines = (data_home / ".gitignore").read_text(encoding="utf-8").splitlines()

        assert "*" not in lines
        assert "/workbench/" in lines
        assert "/memories/*.lock" in lines
        for line in RUNTIME_GITIGNORE_TRACKED:
            assert line in lines


def test_prepare_data_home_switches_between_modes():
    with tempfile.TemporaryDirectory(prefix="rp_switch_") as workdir:
        ignore_path = Path(workdir) / ".improve-toolkit" / ".gitignore"

        with patch.dict(os.environ, {"IMPROVE_PROJECT_DIR": workdir}, clear=True):
            prepare_data_home()
            lines = ignore_path.read_text(encoding="utf-8").splitlines()
        assert "*" in lines
        assert "!.gitignore" not in lines

        with patch.dict(
            os.environ,
            {"IMPROVE_PROJECT_DIR": workdir, "IMPROVE_TRACK_MEMORIES": "1"},
            clear=True,
        ):
            prepare_data_home()
            lines = ignore_path.read_text(encoding="utf-8").splitlines()
        assert "*" not in lines
        assert "/workbench/" in lines

        with patch.dict(os.environ, {"IMPROVE_PROJECT_DIR": workdir}, clear=True):
            prepare_data_home()
            lines = ignore_path.read_text(encoding="utf-8").splitlines()
        assert "*" in lines
        assert "/workbench/" not in lines
        assert "!.gitignore" not in lines


def test_repository_runtime_gitignore_matches_generated_rules():
    repository_root = Path(__file__).resolve().parents[2]
    ignore_path = repository_root / ".improve-toolkit" / ".gitignore"
    assert tuple(ignore_path.read_text(encoding="utf-8").splitlines()) == (
        RUNTIME_GITIGNORE_LOCAL
    )


def test_prepare_data_home_config_track_memories_true():
    with tempfile.TemporaryDirectory(prefix="rp_cfg_true_") as workdir:
        data_home = Path(workdir) / ".improve-toolkit"
        data_home.mkdir()
        (data_home / "config.json").write_text('{"track_memories": true}', encoding="utf-8")
        env = {"IMPROVE_PROJECT_DIR": workdir}
        with patch.dict(os.environ, env, clear=True):
            assert prepare_data_home() == data_home
            lines = (data_home / ".gitignore").read_text(encoding="utf-8").splitlines()

        assert "*" not in lines
        assert "/workbench/" in lines
        for line in RUNTIME_GITIGNORE_TRACKED:
            assert line in lines


def test_prepare_data_home_config_default_false():
    with tempfile.TemporaryDirectory(prefix="rp_cfg_false_") as workdir:
        data_home = Path(workdir) / ".improve-toolkit"
        data_home.mkdir()
        env = {"IMPROVE_PROJECT_DIR": workdir}
        with patch.dict(os.environ, env, clear=True):
            # no config
            prepare_data_home()
            assert "*" in (data_home / ".gitignore").read_text(encoding="utf-8").splitlines()

            # explicit false
            (data_home / "config.json").write_text('{"track_memories": false}', encoding="utf-8")
            prepare_data_home()
            assert "*" in (data_home / ".gitignore").read_text(encoding="utf-8").splitlines()

            # missing key
            (data_home / "config.json").write_text('{"other": true}', encoding="utf-8")
            prepare_data_home()
            assert "*" in (data_home / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_prepare_data_home_config_malformed_ignored():
    with tempfile.TemporaryDirectory(prefix="rp_cfg_bad_") as workdir:
        data_home = Path(workdir) / ".improve-toolkit"
        data_home.mkdir()
        (data_home / "config.json").write_text("{not valid json", encoding="utf-8")
        env = {"IMPROVE_PROJECT_DIR": workdir}
        with patch.dict(os.environ, env, clear=True):
            prepare_data_home()
            assert "*" in (data_home / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_prepare_data_home_env_overrides_config():
    with tempfile.TemporaryDirectory(prefix="rp_cfg_env_") as workdir:
        data_home = Path(workdir) / ".improve-toolkit"
        data_home.mkdir()
        (data_home / "config.json").write_text('{"track_memories": true}', encoding="utf-8")

        # falsy env forces local even when config is true
        with patch.dict(
            os.environ,
            {"IMPROVE_PROJECT_DIR": workdir, "IMPROVE_TRACK_MEMORIES": "0"},
            clear=True,
        ):
            prepare_data_home()
            assert "*" in (data_home / ".gitignore").read_text(encoding="utf-8").splitlines()

        # truthy env forces tracked even when config is false
        (data_home / "config.json").write_text('{"track_memories": false}', encoding="utf-8")
        with patch.dict(
            os.environ,
            {"IMPROVE_PROJECT_DIR": workdir, "IMPROVE_TRACK_MEMORIES": "1"},
            clear=True,
        ):
            prepare_data_home()
            assert "*" not in (data_home / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_prepare_data_home_config_switch_back():
    with tempfile.TemporaryDirectory(prefix="rp_cfg_switch_") as workdir:
        data_home = Path(workdir) / ".improve-toolkit"
        ignore_path = data_home / ".gitignore"
        config_path = data_home / "config.json"
        env = {"IMPROVE_PROJECT_DIR": workdir}
        with patch.dict(os.environ, env, clear=True):
            prepare_data_home()
            assert "*" in ignore_path.read_text(encoding="utf-8").splitlines()

            config_path.write_text('{"track_memories": true}', encoding="utf-8")
            prepare_data_home()
            assert "*" not in ignore_path.read_text(encoding="utf-8").splitlines()

            config_path.write_text('{"track_memories": false}', encoding="utf-8")
            prepare_data_home()
            lines = ignore_path.read_text(encoding="utf-8").splitlines()
            assert "*" in lines
            assert "!.gitignore" not in lines


def test_prepare_data_home_creates_default_config():
    with tempfile.TemporaryDirectory(prefix="rp_cfg_default_") as workdir:
        env = {"IMPROVE_PROJECT_DIR": workdir}
        with patch.dict(os.environ, env, clear=True):
            data_home = prepare_data_home()
            config_path = data_home / "config.json"
            assert config_path.is_file()
            assert json.loads(config_path.read_text(encoding="utf-8")) == {
                "track_memories": False
            }
            assert "*" in (data_home / ".gitignore").read_text(encoding="utf-8").splitlines()


ALL_TESTS = [
    test_claude_defaults,
    test_codex_defaults,
    test_pi_overrides_inherited_host_environment,
    test_codex_plugin_root_detection,
    test_path_overrides,
    test_memory_override,
    test_prepare_data_home_creates_local_gitignore,
    test_prepare_data_home_track_memories_override,
    test_prepare_data_home_switches_between_modes,
    test_repository_runtime_gitignore_matches_generated_rules,
    test_prepare_data_home_config_track_memories_true,
    test_prepare_data_home_config_default_false,
    test_prepare_data_home_config_malformed_ignored,
    test_prepare_data_home_env_overrides_config,
    test_prepare_data_home_config_switch_back,
    test_prepare_data_home_creates_default_config,
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
