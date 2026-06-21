#!/usr/bin/env python3
"""
UserPromptSubmit hook handler.
Records user prompts when submitted.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from session_db import record_conversation
from hook_logger import log_hook_data, read_hook_input


def main():
    input_data = read_hook_input()

    log_hook_data("UserPromptSubmit", input_data)
    
    session_id = input_data.get("session_id", "unknown")
    prompt = input_data.get("prompt", "")
    
    if prompt:
        metadata = {
            "hook_event": "UserPromptSubmit"
        }
        record_conversation(session_id, "user", prompt, metadata)
    
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": ""
        }
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
