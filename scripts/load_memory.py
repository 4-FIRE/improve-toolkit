#!/usr/bin/env python3
"""Load the bounded memory brief at SessionStart."""

import json
import sys
import traceback
from pathlib import Path

from memory_catalog import MemoryCatalog
from runtime_paths import (
    get_data_home,
    get_legacy_memories_dirs,
    get_memories_dir as resolve_memories_dir,
)


UNAVAILABLE_BRIEF = (
    "MEMORY BRIEF unavailable. If prior context matters to the task, "
    "use memory_recall for relevant details."
)


def get_memories_dir() -> Path:
    """Return the shared memory directory without reading full memory files."""
    return resolve_memories_dir()


def main():
    # Windows defaults stdout to GBK; force UTF-8 when the stream supports it.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

    memories_dir = get_memories_dir()
    catalog = MemoryCatalog(
        memory_dir=memories_dir,
        data_home=get_data_home(),
    )
    snapshot = catalog.startup_snapshot()
    has_memory_state = any(
        (memories_dir / name).exists()
        for name in (
            "MEMORY.md",
            "USER.md",
            "SUMMARY.md",
            ".summary.dirty",
            ".summary-state.json",
        )
    ) or any(
        (legacy_dir / name).is_file()
        for legacy_dir in get_legacy_memories_dirs()
        for name in ("MEMORY.md", "USER.md")
    )
    context = (
        snapshot.text
        if snapshot.status == "current"
        else UNAVAILABLE_BRIEF if has_memory_state else ""
    )

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
