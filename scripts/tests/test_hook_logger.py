#!/usr/bin/env python3
"""
Tests for scripts/hook_logger.py — run with:
    python scripts/tests/test_hook_logger.py
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

# Allow importing from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hook_logger import read_hook_input, log_hook_data


# ---------------------------------------------------------------------------
# read_hook_input
# ---------------------------------------------------------------------------

def test_read_hook_input_normal_json():
    """Normal JSON on stdin is parsed correctly."""
    payload = {"session_id": "abc-123", "prompt": "hello"}
    raw = json.dumps(payload).encode("utf-8")

    mock_stdin = MagicMock()
    mock_stdin.buffer.read.return_value = raw

    with patch("hook_logger.sys") as mock_sys:
        mock_sys.stdin = mock_stdin
        # Re-import to pick up the mock — but simpler: call the function
        # with a direct stdin replacement
        pass

    # Direct approach: patch sys.stdin.buffer
    import hook_logger
    original_stdin = hook_logger.sys.stdin
    mock_stdin = MagicMock()
    mock_stdin.buffer.read.return_value = raw
    hook_logger.sys.stdin = mock_stdin
    try:
        result = read_hook_input()
        assert result == payload, f"Expected {payload}, got {result}"
    finally:
        hook_logger.sys.stdin = original_stdin


def test_read_hook_input_empty_stdin():
    """Empty stdin returns empty dict."""
    import hook_logger
    original_stdin = hook_logger.sys.stdin
    mock_stdin = MagicMock()
    mock_stdin.buffer.read.return_value = b""
    hook_logger.sys.stdin = mock_stdin
    try:
        result = read_hook_input()
        assert result == {}, f"Expected empty dict, got {result}"
    finally:
        hook_logger.sys.stdin = original_stdin


def test_read_hook_input_malformed_json():
    """Malformed JSON returns empty dict, no exception."""
    import hook_logger
    original_stdin = hook_logger.sys.stdin
    mock_stdin = MagicMock()
    mock_stdin.buffer.read.return_value = b"{bad json"
    hook_logger.sys.stdin = mock_stdin
    try:
        result = read_hook_input()
        assert result == {}, f"Expected empty dict, got {result}"
    finally:
        hook_logger.sys.stdin = original_stdin


def test_read_hook_input_surrogate_bytes():
    """Bytes that would produce lone surrogates are handled gracefully."""
    # 0x80 is invalid as a standalone UTF-8 byte; with errors='replace'
    # it becomes the replacement character, not a surrogate.
    import hook_logger
    original_stdin = hook_logger.sys.stdin
    mock_stdin = MagicMock()
    # A valid JSON string containing the replacement character
    mock_stdin.buffer.read.return_value = b'{"key": "\x80"}'
    hook_logger.sys.stdin = mock_stdin
    try:
        result = read_hook_input()
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "key" in result
    finally:
        hook_logger.sys.stdin = original_stdin


def test_read_hook_input_attribute_error():
    """If stdin.buffer is missing (e.g. non-standard env), returns {}."""
    import hook_logger
    original_stdin = hook_logger.sys.stdin
    mock_stdin = MagicMock()
    mock_stdin.buffer.read.side_effect = AttributeError("no buffer")
    hook_logger.sys.stdin = mock_stdin
    try:
        result = read_hook_input()
        assert result == {}, f"Expected empty dict, got {result}"
    finally:
        hook_logger.sys.stdin = original_stdin


# ---------------------------------------------------------------------------
# log_hook_data
# ---------------------------------------------------------------------------

def test_log_hook_data_creates_file():
    """log_hook_data creates a log file with today's date."""
    workdir = Path(tempfile.mkdtemp(prefix="hl_test_"))
    try:
        env_patch = {"CLAUDE_PROJECT_DIR": str(workdir)}
        with patch.dict(os.environ, env_patch, clear=False):
            log_hook_data("TestHook", {"foo": "bar"})

        logs_dir = workdir / ".improve-toolkit" / "logs"
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = logs_dir / f"hook_TestHook_{today}.log"

        assert log_file.exists(), f"Log file not created: {log_file}"
        content = log_file.read_text(encoding="utf-8")
        assert "TestHook" in content
        assert "foo" in content
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_log_hook_data_cleans_old_logs():
    """Old log files (different date) are removed."""
    workdir = Path(tempfile.mkdtemp(prefix="hl_test_"))
    try:
        logs_dir = workdir / ".improve-toolkit" / "logs"
        logs_dir.mkdir(parents=True)

        # Create an old log file
        old_log = logs_dir / "hook_CleanHook_2020-01-01.log"
        old_log.write_text("old data")

        env_patch = {"CLAUDE_PROJECT_DIR": str(workdir)}
        with patch.dict(os.environ, env_patch, clear=False):
            log_hook_data("CleanHook", {"new": "data"})

        assert not old_log.exists(), "Old log file should have been deleted"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_log_hook_data_preserves_todays_log():
    """Today's log file is NOT deleted (appended to)."""
    workdir = Path(tempfile.mkdtemp(prefix="hl_test_"))
    try:
        env_patch = {"CLAUDE_PROJECT_DIR": str(workdir)}
        with patch.dict(os.environ, env_patch, clear=False):
            log_hook_data("AppendHook", {"first": "write"})
            log_hook_data("AppendHook", {"second": "write"})

        logs_dir = workdir / ".improve-toolkit" / "logs"
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = logs_dir / f"hook_AppendHook_{today}.log"

        content = log_file.read_text(encoding="utf-8")
        assert "first" in content
        assert "second" in content
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_log_hook_data_excludes_secret_environment_values():
    """Hook diagnostics log known paths, but not API keys or session tokens."""
    workdir = Path(tempfile.mkdtemp(prefix="hl_test_"))
    try:
        env = {
            "CLAUDE_PROJECT_DIR": str(workdir),
            "CODEX_API_KEY": "codex-secret",
            "AWS_SESSION_TOKEN": "aws-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            log_hook_data("SafeEnvHook", {})

        today = datetime.now().strftime("%Y-%m-%d")
        log_file = (
            workdir / ".improve-toolkit" / "logs" / f"hook_SafeEnvHook_{today}.log"
        )
        content = log_file.read_text(encoding="utf-8")
        assert f"CLAUDE_PROJECT_DIR={workdir}" in content
        assert "codex-secret" not in content
        assert "aws-secret" not in content
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_read_hook_input_normal_json,
    test_read_hook_input_empty_stdin,
    test_read_hook_input_malformed_json,
    test_read_hook_input_surrogate_bytes,
    test_read_hook_input_attribute_error,
    test_log_hook_data_creates_file,
    test_log_hook_data_cleans_old_logs,
    test_log_hook_data_preserves_todays_log,
    test_log_hook_data_excludes_secret_environment_values,
]


def main():
    passed = 0
    failed = 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
