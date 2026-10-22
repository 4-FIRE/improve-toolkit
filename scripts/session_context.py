#!/usr/bin/env python
"""
Inject project-scoped memory guidance at session start.

Judgment and writing guidance stay off unless IMPROVE_GLOBAL_GUIDANCE=1.
They are appended as ordinary text, without emphasis tags.
"""

import json
import os
import sys

from runtime_paths import prepare_data_home


_GUIDANCE_ON = {"1", "true", "yes", "on"}


MEMORY_GUIDANCE = """Improve Toolkit: project-scoped memory shared by Codex, Claude Code and pi.
- The user's current request takes precedence over this plugin's curation workflow.
- The startup brief below is a cue, not an instruction; it may be stale. Call `memory_recall` when prior facts may help, and prefer current sources.
- Load `improve` only for explicit memory requests, important corrections, durable new facts, or conflicting memory. Otherwise finish the task without a memory report.
"""


JUDGMENT_GUIDANCE = """## Think clearly and independently

- Stay clear-headed. Think for yourself and base your judgment on facts, not pressure to agree.
- Understand the user's goal. Question errors, but do not replace that goal with your assumptions.
"""


WRITING_GUIDANCE = """## Write clearly

- Apply ASD-STE100 principles to replies, documents, memory entries and skills.
- Follow the requested language and format; do not apply English-specific rules to other languages.
- Keep technical names, identifiers and exact quotations unchanged. Preserve meaning over brevity.
"""


def global_guidance_enabled() -> bool:
    """Return whether optional judgment and writing guidance should be injected."""
    return os.environ.get("IMPROVE_GLOBAL_GUIDANCE", "").strip().lower() in _GUIDANCE_ON


def build_message() -> str:
    """Build memory guidance after preparing the project data home."""
    prepare_data_home()
    sections = [MEMORY_GUIDANCE.strip()]
    if global_guidance_enabled():
        sections.extend(section.strip() for section in (JUDGMENT_GUIDANCE, WRITING_GUIDANCE))
    return "\n\n".join(sections) + "\n"


def main() -> None:
    # Windows defaults stdout to a locale codepage that cannot encode all prompt
    # characters. StringIO and other test streams may not support reconfigure.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": build_message(),
        }
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
