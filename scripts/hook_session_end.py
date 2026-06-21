#!/usr/bin/env python3
"""
SessionEnd hook handler.
Records session end time when a session terminates.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
# Windows defaults stdout to the locale codepage (GBK/cp936); ensure_ascii=False
# payloads with non-GBK characters would crash on print. Force UTF-8.
sys.stdout.reconfigure(encoding="utf-8")
from session_db import record_session_end, save_transcript
from hook_logger import log_hook_data, read_hook_input


def main():
    input_data = read_hook_input()

    log_hook_data("SessionEnd", input_data)
    
    session_id = input_data.get("session_id", "unknown")
    transcript_path = input_data.get("transcript_path")
    
    if transcript_path:
        save_transcript(session_id, transcript_path)
    
    record_session_end(session_id, input_data)
    
    output = {}
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
