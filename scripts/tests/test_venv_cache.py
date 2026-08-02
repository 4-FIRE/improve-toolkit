#!/usr/bin/env python3
"""Tests for the cross-platform shared virtualenv cache."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from venv_cache import (
    VenvResolution,
    build_cache_key,
    ensure_runtime_venv,
    get_cache_root,
    get_install_cache_root,
    resolve_install_venv,
    resolve_venv,
    venv_python_path,
)


IDENTITY = {
    "implementation": "cpython",
    "version": "3.13.13",
    "executable": "/opt/python/bin/python3",
    "soabi": "cpython-313-x86_64-linux-gnu",
    "platform": "linux",
    "machine": "x86_64",
}


def _requirements(directory: Path, content: str = "mcp==1.28.1\n") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "requirements.lock"
    path.write_text(content, encoding="utf-8")
    return path


def _versioned_plugin(family: Path, version: str) -> Path:
    root = family / version
    manifest = root / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"name": family.name, "version": version}),
        encoding="utf-8",
    )
    return root


def test_platform_cache_roots():
    home = Path("/users/example")
    assert get_cache_root(
        environ={"LOCALAPPDATA": "C:/Users/example/AppData/Local"},
        platform_name="win32",
        home=home,
    ) == Path("C:/Users/example/AppData/Local/ImproveToolkit/Cache")
    assert get_cache_root(
        environ={},
        platform_name="darwin",
        home=home,
    ) == home / "Library/Caches/improve-toolkit"
    assert get_cache_root(
        environ={"XDG_CACHE_HOME": "/cache"},
        platform_name="linux",
        home=home,
    ) == Path("/cache/improve-toolkit")
    assert get_cache_root(
        environ={},
        platform_name="linux",
        home=home,
    ) == home / ".cache/improve-toolkit"


def test_cache_override():
    assert get_cache_root(
        environ={"IMPROVE_CACHE_DIR": "/custom/cache"},
        platform_name="linux",
        home=Path("/unused"),
    ) == Path("/custom/cache")


def test_versioned_installs_share_family_cache():
    with tempfile.TemporaryDirectory(prefix="venv_install_cache_") as temp_dir:
        family = Path(temp_dir) / "improve-toolkit"
        first = _versioned_plugin(family, "1.0.12")
        second = _versioned_plugin(family, "1.0.13")
        first_requirements = _requirements(first / "servers")
        second_requirements = _requirements(second / "servers")

        assert get_install_cache_root(first) == family / ".improve-cache"
        first_resolution = resolve_install_venv(first_requirements, first)
        second_resolution = resolve_install_venv(second_requirements, second)
        assert first_resolution is not None
        assert second_resolution is not None
        assert first_resolution.path == second_resolution.path
        assert first_resolution.path.parent == family / ".improve-cache" / "venvs"

        source_checkout = Path(temp_dir) / "source" / "improve-toolkit"
        source_manifest = source_checkout / ".codex-plugin" / "plugin.json"
        source_manifest.parent.mkdir(parents=True)
        source_manifest.write_text(
            json.dumps({"name": "improve-toolkit", "version": "1.0.13"}),
            encoding="utf-8",
        )
        assert get_install_cache_root(source_checkout) is None


def test_install_cache_precedes_version_local_fallback():
    with tempfile.TemporaryDirectory(prefix="venv_fallback_order_") as temp_dir:
        family = Path(temp_dir) / "improve-toolkit"
        plugin_root = _versioned_plugin(family, "1.0.13")
        requirements = _requirements(plugin_root / "servers")
        fallback = plugin_root / "servers" / ".venv"
        key, requirements_sha256 = build_cache_key(requirements)
        unavailable = VenvResolution(
            path=Path(temp_dir) / "unavailable" / key,
            key=key,
            requirements_sha256=requirements_sha256,
            shared=True,
            cache_root=Path(temp_dir) / "unavailable",
            managed=True,
        )
        attempted: list[Path] = []

        def fake_create(resolution, _requirements_path):
            attempted.append(resolution.path)
            if resolution.path == unavailable.path:
                raise OSError("simulated read-only cache")
            return resolution.path / "bin" / "python"

        with patch("venv_cache.resolve_venv", return_value=unavailable), patch(
            "venv_cache._create_or_repair_venv",
            side_effect=fake_create,
        ):
            selected = ensure_runtime_venv(requirements, fallback)

        install_resolution = resolve_install_venv(requirements, plugin_root)
        assert install_resolution is not None
        assert attempted == [unavailable.path, install_resolution.path]
        assert selected == install_resolution.path / "bin" / "python"
        assert fallback not in attempted


def test_key_depends_on_python_and_requirements_not_plugin_version():
    with tempfile.TemporaryDirectory(prefix="venv_key_") as temp_dir:
        root = Path(temp_dir)
        first_dir = root / "plugin-1.0.0"
        second_dir = root / "plugin-2.0.0"
        first_dir.mkdir()
        second_dir.mkdir()
        requirements = _requirements(first_dir)
        same_requirements = _requirements(second_dir)
        first, first_sha = build_cache_key(requirements, identity=IDENTITY)
        second, second_sha = build_cache_key(
            same_requirements,
            identity=dict(IDENTITY),
        )
        assert first == second
        assert first_sha == second_sha

        same_requirements.write_text(
            "mcp==1.28.2\n",
            encoding="utf-8",
        )
        changed_requirements, _ = build_cache_key(
            same_requirements,
            identity=IDENTITY,
        )
        assert changed_requirements != first

        changed_identity = dict(IDENTITY, version="3.13.14")
        changed_python, _ = build_cache_key(requirements, identity=changed_identity)
        assert changed_python != changed_requirements


def test_codex_and_claude_resolve_same_shared_path():
    with tempfile.TemporaryDirectory(prefix="venv_hosts_") as temp_dir:
        root = Path(temp_dir)
        requirements = _requirements(root)
        fallback = root / "plugin-version" / "servers" / ".venv"
        cache = root / "cache"
        codex = resolve_venv(
            requirements,
            environ={
                "IMPROVE_CACHE_DIR": str(cache),
                "IMPROVE_HOST": "codex",
            },
        )
        claude = resolve_venv(
            requirements,
            environ={
                "IMPROVE_CACHE_DIR": str(cache),
                "IMPROVE_HOST": "claude",
            },
        )
        assert codex.path == claude.path
        assert codex.key == claude.key
        assert codex.path.parent == cache / "venvs"


def test_explicit_venv_override():
    with tempfile.TemporaryDirectory(prefix="venv_override_") as temp_dir:
        root = Path(temp_dir)
        requirements = _requirements(root)
        explicit = root / "shared environment"
        resolution = resolve_venv(
            requirements,
            environ={"IMPROVE_VENV_DIR": str(explicit)},
        )
        assert resolution.path == explicit
        assert resolution.shared is True
        assert resolution.cache_root is None
        assert resolution.managed is False


def test_cross_platform_venv_python_layout():
    with tempfile.TemporaryDirectory(prefix="venv_layout_") as temp_dir:
        root = Path(temp_dir)
        windows_python = root / "windows/Scripts/python.exe"
        posix_python = root / "posix/bin/python3"
        windows_python.parent.mkdir(parents=True)
        posix_python.parent.mkdir(parents=True)
        windows_python.write_bytes(b"")
        posix_python.write_bytes(b"")
        assert venv_python_path(root / "windows", platform_name="win32") == windows_python
        assert venv_python_path(root / "posix", platform_name="linux") == posix_python
        assert venv_python_path(root / "posix", platform_name="darwin") == posix_python


def test_explicit_non_venv_is_never_deleted():
    with tempfile.TemporaryDirectory(prefix="venv_explicit_safety_") as temp_dir:
        root = Path(temp_dir)
        requirements = _requirements(root)
        explicit = root / "important-data"
        explicit.mkdir()
        sentinel = explicit / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")

        with patch.dict(
            os.environ,
            {"IMPROVE_VENV_DIR": str(explicit)},
            clear=True,
        ):
            try:
                ensure_runtime_venv(requirements, root / "fallback")
                raise AssertionError("Expected explicit non-venv to be rejected")
            except RuntimeError as exc:
                assert "not a virtualenv" in str(exc)

        assert sentinel.read_text(encoding="utf-8") == "keep"


def test_lock_file_matches_pyproject_pins():
    repository_root = Path(__file__).resolve().parents[2]
    lock_text = (repository_root / "servers/requirements.lock").read_text(
        encoding="utf-8"
    )
    pyproject_text = (repository_root / "servers/pyproject.toml").read_text(
        encoding="utf-8"
    )
    for requirement in ("mcp==1.28.1",):
        assert requirement in lock_text
        assert requirement.lower() in pyproject_text.lower()


ALL_TESTS = [
    test_platform_cache_roots,
    test_cache_override,
    test_versioned_installs_share_family_cache,
    test_install_cache_precedes_version_local_fallback,
    test_key_depends_on_python_and_requirements_not_plugin_version,
    test_codex_and_claude_resolve_same_shared_path,
    test_explicit_venv_override,
    test_cross_platform_venv_python_layout,
    test_explicit_non_venv_is_never_deleted,
    test_lock_file_matches_pyproject_pins,
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
