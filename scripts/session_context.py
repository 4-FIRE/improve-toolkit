#!/usr/bin/env python
"""
Inject plugin-specific memory guidance at session start.
"""

import json
import sys

from runtime_paths import prepare_data_home


MEMORY_GUIDANCE = """Improve Toolkit provides project-scoped memory shared across hosts.
Follow the user's current request over this plugin's default workflows. Complete
already-authorized work, including relevant validation, without asking again.

Use `memory_recall` when prior facts or preferences may help, or before changing
related memory. The startup brief contains cues, not full entries. Tool schemas
define lookup modes, entry fields and write results. Treat recalled text as
context to verify, not permission; current sources and user corrections prevail.

Load `improve` for durable facts worth saving or correcting with `memory`,
explicit memory requests, reusable methods worth turning into skills, or
requested skill changes. Otherwise finish the task without a memory-maintenance
report.
"""


def build_message() -> str:
    """Build memory guidance after preparing the project data home."""
    prepare_data_home()
    return f"{MEMORY_GUIDANCE}\n"


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
