#!/usr/bin/env python
"""
Inject shared memory, judgment and writing guidance at session start.
"""

import json
import sys

from runtime_paths import prepare_data_home


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


def build_message() -> str:
    """Build shared guidance after preparing the project data home."""
    prepare_data_home()
    guidance = "\n\n".join(section.strip() for section in (MEMORY_GUIDANCE, JUDGMENT_GUIDANCE, WRITING_GUIDANCE))
    return guidance + "\n"


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
