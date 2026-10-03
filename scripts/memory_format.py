#!/usr/bin/env python3
"""Shared parsing and rendering rules for persistent memory files."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import re
import time
from uuid import uuid4

ENTRY_DELIMITER = "\n§\n"
MEMORY_CHAR_LIMIT = 24000
USER_CHAR_LIMIT = 8000

ENTRY_MARKER = "<!-- improve-entry:v1 "
ENTRY_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,95}\Z")


@dataclass(frozen=True)
class StoredEntry:
    """One editable block, including its original formatting."""

    content: str
    entry_id: str | None = None
    startup: bool = True
    raw: str = ""
    updated_at: int | None = None


def unix_timestamp() -> int:
    """Return seconds since the Unix epoch."""
    return int(time.time())


def new_entry_id(target: str, timestamp: int) -> str:
    """Include ID creation time and a random suffix for concurrent entries."""
    return ("u:" if target == "user" else "m:") + f"{timestamp}:{uuid4().hex[:12]}"


def parse_entries(raw: str) -> list[StoredEntry]:
    """Read plain entries and v1 markers. Reject invalid or unknown markers."""
    entries: list[StoredEntry] = []
    for index, block in enumerate(re.split(r"\r?\n§\r?\n", raw), 1):
        text = block.strip()
        if not text:
            continue
        if not text.startswith("<!-- improve-entry"):
            entries.append(StoredEntry(content=text, raw=block))
            continue
        header, _, content = text.partition("\n")
        header = header.rstrip("\r")
        if not header.startswith(ENTRY_MARKER) or not header.endswith(" -->"):
            raise ValueError(f"Entry {index}: invalid or unsupported entry marker.")
        try:
            settings = json.loads(header[len(ENTRY_MARKER):-4])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Entry {index}: invalid marker JSON.") from exc
        if not isinstance(settings, dict) or set(settings) - {"id", "startup", "updated_at"}:
            raise ValueError(f"Entry {index}: use only id, startup and updated_at in the marker.")
        entry_id = settings.get("id")
        if not isinstance(entry_id, str) or not ENTRY_ID_PATTERN.fullmatch(entry_id):
            raise ValueError(f"Entry {index}: invalid or missing id.")
        startup = settings.get("startup", True)
        if type(startup) is not bool:
            raise ValueError(f"Entry {index}: startup must be a boolean.")
        updated_at = settings.get("updated_at")
        if "updated_at" in settings and (type(updated_at) is not int or updated_at < 0):
            raise ValueError(f"Entry {index}: updated_at must be a non-negative Unix timestamp in seconds.")
        content = content.strip()
        if not content:
            raise ValueError(f"Entry {index}: content is empty.")
        entries.append(StoredEntry(content, entry_id, startup, block, updated_at))
    return entries


def render_entry(content: str, entry_id: str, startup: bool = True, *, updated_at: int | None = None) -> str:
    """Write the fixed ID, known update time and non-default startup setting."""
    settings: dict[str, str | bool | int] = {"id": entry_id}
    if updated_at is not None:
        settings["updated_at"] = updated_at
    if not startup:
        settings["startup"] = False
    header = ENTRY_MARKER + json.dumps(settings, ensure_ascii=False, separators=(",", ":")) + " -->"
    return header + "\n" + content


def split_entries(raw: str) -> list[str]:
    """Parse serialized memory text into non-empty, trimmed entries."""
    return [entry for part in raw.split(ENTRY_DELIMITER) if (entry := part.strip())]


def join_entries(entries: Iterable[str]) -> str:
    """Serialize memory entries using the shared delimiter."""
    return ENTRY_DELIMITER.join(entries)


def deduplicate_entries(entries: Iterable[str]) -> list[str]:
    """Remove duplicate entries while preserving the first occurrence."""
    return list(dict.fromkeys(entries))


def char_limit(target: str) -> int:
    """Return the default character budget for a memory target."""
    return USER_CHAR_LIMIT if target == "user" else MEMORY_CHAR_LIMIT


def char_count(entries: Iterable[str]) -> int:
    """Return the serialized character count for entries."""
    return len(join_entries(entries))


def render_block(
    target: str,
    entries: list[str],
    *,
    limit: int | None = None,
) -> str:
    """Render one memory target as a SessionStart prompt block."""
    if not entries:
        return ""

    active_limit = char_limit(target) if limit is None else limit
    content = join_entries(entries)
    current = len(content)
    pct = min(100, int((current / active_limit) * 100)) if active_limit > 0 else 0

    if target == "user":
        header = (
            f"USER PROFILE (who the user is) "
            f"[{pct}% — {current:,}/{active_limit:,} chars]"
        )
    else:
        header = (
            f"MEMORY (your personal notes) "
            f"[{pct}% — {current:,}/{active_limit:,} chars]"
        )

    separator = "═" * 46
    return f"{separator}\n{header}\n{separator}\n{content}"
