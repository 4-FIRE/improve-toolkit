#!/usr/bin/env python3
"""Shared parsing and rendering rules for persistent memory files."""

from __future__ import annotations

from collections.abc import Iterable

ENTRY_DELIMITER = "\n§\n"
MEMORY_CHAR_LIMIT = 24000
USER_CHAR_LIMIT = 8000


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
