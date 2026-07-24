#!/usr/bin/env python3
"""Tests for cross-host memory migration."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memory_format import ENTRY_DELIMITER
from memory_migration import prepare_memories_dir


def _write(path: Path, entries: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ENTRY_DELIMITER.join(entries), encoding="utf-8")


def _read(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [
        entry
        for part in path.read_text(encoding="utf-8").split(ENTRY_DELIMITER)
        if (entry := part.strip())
    ]


def test_merges_both_legacy_hosts():
    with tempfile.TemporaryDirectory(prefix="memory_migration_") as workdir:
        project = Path(workdir)
        _write(project / ".claude/memories/MEMORY.md", ["shared", "claude"])
        _write(
            project / ".codex/improve-toolkit/memories/MEMORY.md",
            ["shared", "codex"],
        )
        _write(project / ".claude/memories/USER.md", ["user preference"])

        with patch.dict(
            os.environ,
            {"IMPROVE_PROJECT_DIR": workdir},
            clear=True,
        ):
            memory_dir = prepare_memories_dir()

        assert memory_dir == project / ".improve-toolkit/memories"
        assert _read(memory_dir / "MEMORY.md") == ["shared", "claude", "codex"]
        assert _read(memory_dir / "USER.md") == ["user preference"]
        assert not (project / ".claude/memories/MEMORY.md").exists()
        assert not (
            project / ".codex/improve-toolkit/memories/MEMORY.md"
        ).exists()
        assert not (project / ".claude/memories/USER.md").exists()


def test_existing_shared_file_is_authoritative():
    with tempfile.TemporaryDirectory(prefix="memory_authoritative_") as workdir:
        project = Path(workdir)
        shared_file = project / ".improve-toolkit/memories/MEMORY.md"
        _write(shared_file, [])
        _write(project / ".claude/memories/MEMORY.md", ["removed legacy entry"])

        with patch.dict(
            os.environ,
            {"IMPROVE_PROJECT_DIR": workdir},
            clear=True,
        ):
            prepare_memories_dir()

        assert shared_file.is_file()
        assert _read(shared_file) == []
        assert _read(project / ".claude/memories/MEMORY.md") == [
            "removed legacy entry"
        ]


def test_empty_legacy_file_establishes_shared_authority():
    with tempfile.TemporaryDirectory(prefix="memory_empty_legacy_") as workdir:
        project = Path(workdir)
        legacy_file = project / ".claude/memories/MEMORY.md"
        _write(legacy_file, [])

        with patch.dict(
            os.environ,
            {"IMPROVE_PROJECT_DIR": workdir},
            clear=True,
        ):
            memory_dir = prepare_memories_dir()

        shared_file = memory_dir / "MEMORY.md"
        assert shared_file.is_file()
        assert _read(shared_file) == []
        assert not legacy_file.exists()


def test_existing_shared_file_prunes_only_synchronized_entries():
    with tempfile.TemporaryDirectory(prefix="memory_partial_cleanup_") as workdir:
        project = Path(workdir)
        shared_file = project / ".improve-toolkit/memories/MEMORY.md"
        legacy_file = project / ".claude/memories/MEMORY.md"
        _write(shared_file, ["already synchronized"])
        _write(legacy_file, ["already synchronized", "needs manual resolution"])

        with patch.dict(
            os.environ,
            {"IMPROVE_PROJECT_DIR": workdir},
            clear=True,
        ):
            prepare_memories_dir()

        assert _read(shared_file) == ["already synchronized"]
        assert _read(legacy_file) == ["needs manual resolution"]


def test_unreadable_legacy_file_is_retained():
    with tempfile.TemporaryDirectory(prefix="memory_unreadable_") as workdir:
        project = Path(workdir)
        legacy_file = project / ".claude/memories/MEMORY.md"
        legacy_file.parent.mkdir(parents=True)
        legacy_file.write_bytes(b"\xff")

        with patch.dict(
            os.environ,
            {"IMPROVE_PROJECT_DIR": workdir},
            clear=True,
        ):
            memory_dir = prepare_memories_dir()

        assert legacy_file.read_bytes() == b"\xff"
        assert not (memory_dir / "MEMORY.md").exists()


def test_memory_override_does_not_import_project_defaults():
    with tempfile.TemporaryDirectory(prefix="memory_override_") as workdir:
        project = Path(workdir)
        override = project / "custom-memory"
        _write(project / ".claude/memories/MEMORY.md", ["legacy"])

        with patch.dict(
            os.environ,
            {
                "IMPROVE_PROJECT_DIR": workdir,
                "IMPROVE_MEMORY_DIR": str(override),
            },
            clear=True,
        ):
            assert prepare_memories_dir() == override

        assert not (override / "MEMORY.md").exists()


ALL_TESTS = [
    test_merges_both_legacy_hosts,
    test_existing_shared_file_is_authoritative,
    test_empty_legacy_file_establishes_shared_authority,
    test_existing_shared_file_prunes_only_synchronized_entries,
    test_unreadable_legacy_file_is_retained,
    test_memory_override_does_not_import_project_defaults,
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
