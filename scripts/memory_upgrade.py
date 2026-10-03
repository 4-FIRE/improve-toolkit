#!/usr/bin/env python3
"""Move legacy entry settings into Markdown under the catalog lock."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from file_ops import atomic_write_text
from memory_format import (
    ENTRY_ID_PATTERN, StoredEntry, join_entries, new_entry_id, parse_entries, render_entry, unix_timestamp,
)


BACKUP_FILENAME = ".migration-backup.json"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise OSError(f"Cannot read {path}: {exc}") from exc
    except UnicodeError as exc:
        raise UnicodeError(f"Cannot read {path}: {exc}") from exc


def _matches_missing_id(entry: StoredEntry, record: dict) -> bool:
    """Match a migrated entry after an interrupted write with no legacy ID."""
    content_hash = record.get("content_hash")
    if record.get("id") not in (None, "") or not isinstance(content_hash, str):
        return False
    contents = {entry.content}
    source = record.get("source")
    if isinstance(source, str) and source.strip():
        suffix = "\nSource: " + source.strip()
        contents.update(content[:-len(suffix)] for content in tuple(contents) if content.endswith(suffix))
    return content_hash in {
        hashlib.sha256(text.encode("utf-8")).hexdigest()
        for content in contents for text in (content, content.replace("\r\n", "\n"))
    }


def upgrade_memory_files(memory_dir: Path) -> bool:
    """Back up once, persist missing IDs, and retain unresolved metadata."""
    metadata_path = memory_dir / "METADATA.jsonl"
    originals: dict[str, str | None] = {}
    for name in ("MEMORY.md", "USER.md", "METADATA.jsonl"):
        originals[name] = _read_text(memory_dir / name)
    metadata = originals["METADATA.jsonl"]
    timestamp = unix_timestamp()
    logger = logging.getLogger(__name__)
    records: list[tuple[int, dict]] = []
    unresolved = False
    for line_number, line in enumerate((metadata or "").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            record = None
        if not isinstance(record, dict):
            logger.warning("Retained invalid legacy metadata at %s:%d", metadata_path, line_number)
            unresolved = True
            continue
        records.append((line_number, record))

    parsed = {}
    for target, name in (("user", "USER.md"), ("memory", "MEMORY.md")):
        try:
            parsed[target] = parse_entries(originals[name] or "")
        except ValueError as exc:
            raise ValueError(f"{memory_dir / name}: {exc}") from exc
    used_ids: set[str] = set()
    for target, entries in parsed.items():
        for entry in entries:
            if entry.entry_id:
                if entry.entry_id in used_ids:
                    name = "USER.md" if target == "user" else "MEMORY.md"
                    raise ValueError(f"Duplicate entry id in {memory_dir / name}: {entry.entry_id}")
                used_ids.add(entry.entry_id)
    reserved_ids = used_ids | {
        record["id"] for _, record in records
        if isinstance(record.get("id"), str) and ENTRY_ID_PATTERN.fullmatch(record["id"])
    }
    matched: set[int] = set()
    updated: dict[str, str] = {}
    unresolved_entries: list[str] = []
    unmatched_entries: list[str] = []
    for target, entries in parsed.items():
        blocks: list[str] = []
        rewritten = False
        for entry in entries:
            hashes = tuple(hashlib.sha256(text.encode("utf-8")).hexdigest() for text in (
                entry.content, entry.content.replace("\r\n", "\n"),
            ))
            candidates = [
                (line, record) for line, record in records
                if line not in matched and record.get("target") == target
                and (
                    (record.get("id") == entry.entry_id or _matches_missing_id(entry, record)) if entry.entry_id else
                    record.get("content_hash") in hashes
                )
            ]
            if entry.entry_id:
                # A previous attempt can have committed this file before interruption.
                if len(candidates) == 1:
                    matched.add(candidates[0][0])
                blocks.append(entry.raw)
                continue
            if len(candidates) > 1:
                logger.warning("Retained ambiguous legacy metadata for %s memory", target)
                unresolved = True
                unresolved_entries.append(f"{target} entry {len(blocks) + 1}")
                blocks.append(entry.raw)
                continue
            record = candidates[0][1] if candidates else {}
            if not candidates:
                unmatched_entries.append(f"{target} entry {len(blocks) + 1}")
            entry_id = record.get("id")
            source = record.get("source")
            if candidates and (
                (entry_id not in (None, "") and (
                    not isinstance(entry_id, str) or not ENTRY_ID_PATTERN.fullmatch(entry_id) or entry_id in used_ids
                )) or record.get("startup", "auto") not in ("always", "auto", "never")
                or (source is not None and (
                    not isinstance(source, str) or "§" in source.splitlines()
                    or "<!-- improve-entry" in source
                ))
            ):
                logger.warning("Retained invalid legacy settings at %s:%d", metadata_path, candidates[0][0])
                unresolved = True
                unresolved_entries.append(f"{target} entry {len(blocks) + 1}")
                blocks.append(entry.raw)
                continue
            if not entry_id:
                entry_id = new_entry_id(target, timestamp)
                while entry_id in used_ids or entry_id in reserved_ids:
                    entry_id = new_entry_id(target, timestamp)
            used_ids.add(entry_id)
            content = entry.content
            source = (source or "").strip()
            if source and source not in content:
                content += "\nSource: " + source
            blocks.append(render_entry(content, entry_id, record.get("startup") != "never", updated_at=timestamp))
            rewritten = True
            if candidates:
                matched.add(candidates[0][0])
        name = "USER.md" if target == "user" else "MEMORY.md"
        rendered = join_entries(blocks)
        if rewritten and rendered != originals[name]:
            updated[name] = rendered
    for line, _ in records:
        if line not in matched:
            logger.warning("Retained unmatched legacy metadata at %s:%d", metadata_path, line)
            unresolved = True

    if unresolved and (unresolved_entries or unmatched_entries):
        locations = ", ".join(unresolved_entries + unmatched_entries)
        raise ValueError(
            f"Unresolved legacy settings in {metadata_path} for {locations}. "
            "Repair the metadata before migration; entry IDs and startup settings cannot be confirmed."
        )

    # Validate all proposed files before saving any migration result.
    ids: set[str] = set()
    for name in ("USER.md", "MEMORY.md"):
        for entry in parse_entries(updated.get(name, originals[name]) or ""):
            if entry.entry_id:
                if entry.entry_id in ids:
                    raise ValueError(f"Duplicate entry id in {name}: {entry.entry_id}")
                ids.add(entry.entry_id)
    if not updated and (unresolved or metadata is None):
        return False
    for name, original in originals.items():
        current = _read_text(memory_dir / name)
        if current != original:
            raise OSError(f"Memory files changed during migration: {memory_dir / name}")
    backup = memory_dir / BACKUP_FILENAME
    if not backup.exists():
        atomic_write_text(backup, json.dumps(originals, ensure_ascii=False, indent=2) + "\n")
    else:
        saved = json.loads(_read_text(backup) or "")
        if not isinstance(saved, dict) or set(saved) != set(originals) or any(
            value is not None and not isinstance(value, str) for value in saved.values()
        ):
            raise ValueError(f"Invalid migration backup: {backup}")
    atomic_write_text(memory_dir / ".summary.dirty", "Memory format migration", temp_prefix=".summary_dirty_")
    for name, content in updated.items():
        if _read_text(memory_dir / name) != originals[name]:
            raise OSError(f"Memory file changed during migration: {memory_dir / name}")
        atomic_write_text(memory_dir / name, content, temp_prefix=".migration_")
    if not unresolved:
        if _read_text(metadata_path) != metadata:
            raise OSError(f"Legacy metadata changed during migration: {metadata_path}")
        if metadata is not None:
            metadata_path.unlink()
    return True
