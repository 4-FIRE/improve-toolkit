#!/usr/bin/env python3
"""
Stop hook handler.
Records assistant responses when a turn completes.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from session_db import record_conversation
from hook_logger import log_hook_data, read_hook_input


def main():
    input_data = read_hook_input()

    log_hook_data("Stop", input_data)
    
    session_id = input_data.get("session_id", "unknown")
    
    response_text = input_data.get("last_assistant_message", "")
    
    if response_text:
        metadata = {
            "hook_event": "Stop"
        }
        record_conversation(session_id, "assistant", response_text, metadata)
    
    output = {}
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
