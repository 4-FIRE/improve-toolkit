#!/usr/bin/env python3
"""
Debug logger for hooks.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

from runtime_paths import get_data_home


def read_hook_input() -> dict:
    """Read and parse the hook JSON payload from stdin.

    On Windows, ``sys.stdin`` uses the system ANSI codepage with the
    ``surrogateescape`` error handler. Bytes that are not representable in
    that codepage (e.g. raw UTF-8 byte 0x80) get decoded into lone
    surrogates such as ``\\udc80``. Those surrogates survive ``json.load``
    and later crash UTF-8 encoding when writing logs or inserting into
    SQLite (``UnicodeEncodeError: surrogates not allowed``).

    Reading raw bytes and decoding as UTF-8 with ``errors='replace'`` keeps
    the parsed data encodable everywhere downstream.
    """
    try:
        raw = sys.stdin.buffer.read()
        text = raw.decode("utf-8", errors="replace")
        return json.loads(text)
    except (json.JSONDecodeError, ValueError, AttributeError, UnicodeError):
        return {}


def log_hook_data(hook_name: str, input_data: dict) -> None:
    """Log hook input data. Only keeps today's logs."""
    logs_dir = get_data_home() / "logs"
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
    
    # errors='replace' guards against lone surrogates slipping in from
    # os.environ values (also decoded with surrogateescape on Windows).
    with open(log_file, 'a', encoding='utf-8', errors='replace') as f:
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
        safe_environment_keys = {
            "PLUGIN_ROOT",
            "PLUGIN_DATA",
            "CLAUDE_PLUGIN_ROOT",
            "CLAUDE_PROJECT_DIR",
            "CLAUDE_SESSION_ID",
            "CODEX_HOME",
            "CODEX_THREAD_ID",
            "IMPROVE_HOST",
            "IMPROVE_PROJECT_DIR",
            "IMPROVE_DATA_DIR",
            "IMPROVE_SKILLS_DIR",
            "SESSION_ID",
        }
        f.write(f"\nEnvironment Variables (plugin paths and session metadata):\n")
        for key, value in sorted(os.environ.items()):
            upper_key = key.upper()
            if upper_key in safe_environment_keys:
                f.write(f"  {key}={value}\n")
        f.write(f"{'='*80}\n")
