#!/usr/bin/env python3
"""Resolve and initialize the shared cross-host memory store."""

from __future__ import annotations

import sys
from pathlib import Path

from file_ops import atomic_write_text, file_lock
from memory_format import (
    deduplicate_entries,
    join_entries,
    split_entries,
)
from runtime_paths import (
    get_data_home,
    get_legacy_memories_dirs,
    get_memories_dir,
    prepare_data_home,
)

LOCK_TIMEOUT_SECONDS = 15.0
LOCK_POLL_INTERVAL = 0.1
MEMORY_FILENAMES = ("MEMORY.md", "USER.md")


def _read_entries(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # The legacy file may disappear between is_file() and read_text().
        return []
    return split_entries(raw)


def _write_entries(path: Path, entries: list[str]) -> None:
    atomic_write_text(
        path,
        join_entries(entries),
        temp_prefix=".migration_",
    )


def _warn_retained(path: Path, reason: BaseException | str) -> None:
    print(
        f"improve: retained unresolved legacy memory {path}: {reason}",
        file=sys.stderr,
    )


def _file_lock(path: Path):
    """Use the same sibling lock-file protocol as MemoryStore mutations."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    return file_lock(
        lock_path,
        timeout=LOCK_TIMEOUT_SECONDS,
        poll_interval=LOCK_POLL_INTERVAL,
        description=f"memory migration lock {lock_path}",
    )


def _prune_synchronized_legacy(path: Path, synchronized: set[str]) -> None:
    """Remove verified entries from one legacy file, retaining unresolved data."""
    if not path.is_file():
        return

    try:
        with _file_lock(path):
            legacy_entries = _read_entries(path)
            remaining = [entry for entry in legacy_entries if entry not in synchronized]

            if not legacy_entries:
                path.unlink(missing_ok=True)
            elif len(remaining) == len(legacy_entries):
                return
            elif remaining:
                _write_entries(path, remaining)
            else:
                path.unlink(missing_ok=True)
    except (OSError, UnicodeError) as exc:
        _warn_retained(path, exc)


def prepare_memories_dir(project_dir: Path | str | None = None) -> Path:
    """Return shared memory, migrating and pruning legacy files if needed.

    The shared file is authoritative once present. Legacy entries verified in
    the shared file are removed from the old host file; entries missing from the
    shared file, unreadable files, and cleanup failures are retained for manual
    resolution instead of being re-imported and potentially resurrecting a
    deliberate deletion.
    """
    shared_dir = get_memories_dir(project_dir)
    if shared_dir == get_data_home(project_dir) / "memories":
        prepare_data_home(project_dir)
    legacy_dirs = get_legacy_memories_dirs(project_dir)
    if not legacy_dirs:
        return shared_dir

    for filename in MEMORY_FILENAMES:
        destination = shared_dir / filename
        legacy_paths = [legacy_dir / filename for legacy_dir in legacy_dirs]
        if not any(path.is_file() for path in legacy_paths):
            continue

        with _file_lock(destination):
            if not destination.exists():
                readable_sources: list[tuple[Path, list[str]]] = []
                for path in legacy_paths:
                    if not path.is_file():
                        continue
                    try:
                        readable_sources.append((path, _read_entries(path)))
                    except (OSError, UnicodeError) as exc:
                        _warn_retained(path, exc)

                if not readable_sources:
                    continue

                entries: list[str] = []
                for _path, source_entries in readable_sources:
                    entries.extend(source_entries)
                _write_entries(destination, deduplicate_entries(entries))

            try:
                synchronized = set(_read_entries(destination))
            except (OSError, UnicodeError) as exc:
                _warn_retained(destination, f"shared file could not be verified: {exc}")
                continue

            for path in legacy_paths:
                _prune_synchronized_legacy(path, synchronized)

    return shared_dir
