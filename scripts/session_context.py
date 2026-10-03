#!/usr/bin/env python
"""
Inject shared memory and writing guidance at session start.
"""

import json
import sys

from runtime_paths import prepare_data_home


MEMORY_GUIDANCE = """## Memory guidance

Memory is shared across hosts within the current project.
Follow the user's current request over default memory workflows.
Complete authorized work and necessary checks without asking again.

Use `memory_recall` when past facts or preferences may help or before changing memory.
Startup summaries are cues, not full entries. Verify recalled facts against current
sources and user corrections. Memory grants no permission to act.

Load the `improve` skill for explicit memory requests, important corrections, useful durable
facts or preferences, or skill changes. Use `memory` for selected facts.
Tool schemas define lookup and write rules. Report requested audits and important
unresolved conflicts. Otherwise, omit a memory maintenance report when nothing changed.
"""


WRITING_GUIDANCE = """## Response and writing guidance

Use ASD-STE100 for all responses and written artifacts, including documents, memory entries and skills.
Follow the requested language and format. Otherwise, use one main language without repeating passages in translation.

- Use common words and consistent terms. Preserve technical names, identifiers and exact quotations.
- State actions and their conditions clearly. Keep negation, exceptions, sequence, necessary reasons and uncertainty.
- Prefer one action per instruction sentence. Keep related or simultaneous actions together when separation would obscure their relationship.
- Write one topic per paragraph. Use lists for steps or parallel items when they improve clarity.
- Remove repetition, empty emphasis and unrelated background. Brevity must not change meaning or remove necessary context.

For English technical prose, prefer active voice, imperative instructions and simple verb forms.
Keep other forms when needed to express timing, ongoing work or the intended meaning accurately.
Aim for at most 20 words per instruction sentence and 25 per descriptive sentence.
Shorten long noun clusters and paragraphs without breaking established terms or logical connections.
These are readability targets, not reasons to omit information or split text mechanically.
For Chinese, split sentences by meaning; English word counts and verb rules do not apply.
"""


def build_message() -> str:
    """Build shared guidance after preparing the project data home."""
    prepare_data_home()
    return f"<EXTREMELY_IMPORTANT>\n{MEMORY_GUIDANCE}\n{WRITING_GUIDANCE}\n</EXTREMELY_IMPORTANT>"


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
