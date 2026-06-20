#!/usr/bin/env python3
"""
SessionStart hook handler.
Records session metadata when a session begins.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from session_db import record_session_start
from hook_logger import log_hook_data


def main():
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        input_data = {}
    
    log_hook_data("SessionStart", input_data)
    
    session_id = input_data.get("session_id", "unknown")
    workspace = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    
    transcript_path = input_data.get("transcript_path")
    cwd = input_data.get("cwd", workspace)
    permission_mode = input_data.get("permission_mode")
    agent_type = input_data.get("agent_type")
    
    record_session_start(
        session_id, 
        workspace, 
        input_data,
        transcript_path=transcript_path,
        cwd=cwd,
        permission_mode=permission_mode,
        agent_type=agent_type
    )
    
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": ""
        }
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
