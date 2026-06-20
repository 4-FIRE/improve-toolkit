#!/usr/bin/env python3
"""
Debug logger for hooks.
"""

import json
import os
import subprocess
from pathlib import Path
from datetime import datetime


def log_hook_data(hook_name: str, input_data: dict) -> None:
    """Log hook input data. Only keeps today's logs."""
    logs_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".claude" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = logs_dir / f"hook_{hook_name}_{today}.log"
    
    for old_log in logs_dir.glob(f"hook_{hook_name}_*.log"):
        if old_log != log_file:
            try:
                old_log.unlink()
            except OSError:
                pass
    
    if log_file.exists():
        try:
            subprocess.run(['xattr', '-c', str(log_file)], check=False, capture_output=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
    
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*80}\n")
        f.write(f"Time: {datetime.now().isoformat()}\n")
        f.write(f"Hook Event: {hook_name}\n")
        f.write(f"\nInput Data (full):\n")
        f.write(json.dumps(input_data, ensure_ascii=False, indent=2))
        f.write(f"\n\nAll keys in input:\n")
        for key in sorted(input_data.keys()):
            f.write(f"  - {key}\n")
        f.write(f"\nSession ID fields:\n")
        for field in ['sessionId', 'session_id', 'id', 'session']:
            if field in input_data:
                f.write(f"  {field}: {input_data.get(field)}\n")
        f.write(f"\nEnvironment Variables (CLAUDE/SESSION):\n")
        for key, value in sorted(os.environ.items()):
            if 'CLAUDE' in key.upper() or 'SESSION' in key.upper():
                f.write(f"  {key}={value}\n")
        f.write(f"{'='*80}\n")
