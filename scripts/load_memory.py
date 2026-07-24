#!/usr/bin/env python3
"""
Load memory files at session start for system prompt injection.
Outputs JSON with additional_context for SessionStart hook.

Based on MemoryStore from memory_tool.py:
- Memory files live in a shared, project-scoped directory across plugin hosts
- Separate char limits: memory (2200), user (1375)
- Frozen snapshot pattern: system prompt is stable across session
"""

import json
import sys
import traceback
from pathlib import Path

from memory_format import (
    deduplicate_entries,
    render_block,
    split_entries,
)
from memory_migration import prepare_memories_dir


def get_memories_dir() -> Path:
    """Return the shared memory directory, migrating legacy files if needed."""
    return prepare_memories_dir()


def read_entries(path: Path) -> list[str]:
    """Read memory file and split into entries."""
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, IOError):
        return []

    if not raw.strip():
        return []

    return split_entries(raw)


def main():
    # Windows defaults stdout to GBK; force UTF-8 when the stream supports it.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

    memories_dir = get_memories_dir()

    memory_path = memories_dir / "MEMORY.md"
    user_path = memories_dir / "USER.md"

    memory_entries = read_entries(memory_path)
    user_entries = read_entries(user_path)

    memory_entries = deduplicate_entries(memory_entries)
    user_entries = deduplicate_entries(user_entries)

    sections = []

    user_block = render_block("user", user_entries)
    if user_block:
        sections.append(user_block)

    memory_block = render_block("memory", memory_entries)
    if memory_block:
        sections.append(memory_block)

    context = "\n\n".join(sections) if sections else ""

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def _empty_output() -> str:
    """Emit a valid (empty) SessionStart payload, used if main() fails."""
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ""}},
        ensure_ascii=False,
    )


if __name__ == "__main__":
    # Self-safe: a hook crash must still return valid SessionStart JSON so the
    # session can start. This replaces the POSIX-only `2>/dev/null || echo`
    # shell fallback that previously lived in hooks.json (which doesn't
    # translate to Windows cmd).
    try:
        main()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        print(_empty_output())
