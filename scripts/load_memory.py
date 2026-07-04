#!/usr/bin/env python3
"""
Load memory files at session start for system prompt injection.
Outputs JSON with additional_context for SessionStart hook.

Based on MemoryStore from memory_tool.py:
- Memory files live in .claude/memories/
- Separate char limits: memory (2200), user (1375)
- Frozen snapshot pattern: system prompt is stable across session
"""

import json
import os
import sys
import traceback
from pathlib import Path

# Windows defaults stdout to GBK; force UTF-8 so memory content with non-GBK
# characters (emoji, box-drawing, etc.) prints without UnicodeEncodeError.
sys.stdout.reconfigure(encoding="utf-8")

ENTRY_DELIMITER = "\n§\n"
MEMORY_CHAR_LIMIT = 2200
USER_CHAR_LIMIT = 1375


def get_home() -> Path:
    """Return the project directory ($CLAUDE_PROJECT_DIR/.claude)."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".claude"


def get_memories_dir() -> Path:
    """Return the profile-scoped memories directory."""
    return get_home() / "memories"


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

    entries = [e.strip() for e in raw.split(ENTRY_DELIMITER)]
    return [e for e in entries if e]


def render_block(target: str, entries: list[str]) -> str:
    """Render a system prompt block with header and usage indicator."""
    if not entries:
        return ""

    limit = MEMORY_CHAR_LIMIT if target == "memory" else USER_CHAR_LIMIT
    content = ENTRY_DELIMITER.join(entries)
    current = len(content)
    pct = min(100, int((current / limit) * 100)) if limit > 0 else 0

    if target == "user":
        header = f"USER PROFILE (who the user is) [{pct}% — {current:,}/{limit:,} chars]"
    else:
        header = f"MEMORY (your personal notes) [{pct}% — {current:,}/{limit:,} chars]"

    separator = "═" * 46
    return f"{separator}\n{header}\n{separator}\n{content}"


def main():
    memories_dir = get_memories_dir()

    memory_path = memories_dir / "MEMORY.md"
    user_path = memories_dir / "USER.md"

    memory_entries = read_entries(memory_path)
    user_entries = read_entries(user_path)

    memory_entries = list(dict.fromkeys(memory_entries))
    user_entries = list(dict.fromkeys(user_entries))

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
