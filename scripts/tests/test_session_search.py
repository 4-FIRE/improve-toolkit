#!/usr/bin/env python3
"""
Tests for scripts/session_search.py — run with:
    python scripts/tests/test_session_search.py
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Patch CLAUDE_PROJECT_DIR before importing so get_home() resolves to temp dir.
_workdir = Path(tempfile.mkdtemp(prefix="ss_test_"))
os.environ["CLAUDE_PROJECT_DIR"] = str(_workdir)

from session_search import (
    format_timestamp,
    _format_recent_sessions,
    _summarize_search_results,
    session_search_tool,
    session_history_tool,
)
import session_db


def _setup_db(workdir: Path) -> Path:
    """Initialize a temp DB and return its path."""
    os.environ["CLAUDE_PROJECT_DIR"] = str(workdir)
    db_path = workdir / ".claude" / "sessions" / "sessions.db"
    session_db.init_database(db_path)
    return db_path


# ---------------------------------------------------------------------------
# format_timestamp
# ---------------------------------------------------------------------------

def test_format_timestamp_valid():
    """format_timestamp converts ISO format to readable."""
    result = format_timestamp("2026-06-21T14:30:00")
    assert result == "2026-06-21 14:30:00", f"Got {result}"


def test_format_timestamp_with_timezone():
    """format_timestamp handles timezone info."""
    result = format_timestamp("2026-06-21T14:30:00+08:00")
    # Should not crash; format depends on implementation
    assert isinstance(result, str)
    assert "2026" in result


def test_format_timestamp_invalid():
    """format_timestamp returns original string for invalid input."""
    result = format_timestamp("not-a-date")
    assert result == "not-a-date", f"Got {result}"


def test_format_timestamp_none():
    """format_timestamp returns original for None input."""
    result = format_timestamp(None)
    assert result is None, f"Got {result}"


# ---------------------------------------------------------------------------
# _summarize_search_results
# ---------------------------------------------------------------------------

def test_summarize_search_results_grouping():
    """_summarize_search_results groups results by session_id."""
    results = [
        {"session_id": "s1", "timestamp": "2026-06-21T10:00:00", "role": "user", "content": "hello"},
        {"session_id": "s1", "timestamp": "2026-06-21T10:01:00", "role": "assistant", "content": "hi"},
        {"session_id": "s2", "timestamp": "2026-06-21T11:00:00", "role": "user", "content": "test"},
    ]
    summary = _summarize_search_results(results, limit=5)

    assert summary["total_sessions"] == 2
    assert summary["returned_sessions"] == 2
    assert len(summary["sessions"]) == 2

    # s1 should have 2 matches, s2 should have 1
    s1 = next(s for s in summary["sessions"] if s["session_id"] == "s1")
    s2 = next(s for s in summary["sessions"] if s["session_id"] == "s2")
    assert len(s1["matches"]) == 2
    assert len(s2["matches"]) == 1


def test_summarize_search_results_limit():
    """_summarize_search_results respects limit."""
    results = [
        {"session_id": f"s{i}", "timestamp": f"2026-06-21T{i:02d}:00:00", "role": "user", "content": f"msg {i}"}
        for i in range(5)
    ]
    summary = _summarize_search_results(results, limit=2)
    assert summary["returned_sessions"] == 2
    assert len(summary["sessions"]) == 2


def test_summarize_search_results_empty():
    """_summarize_search_results handles empty results."""
    summary = _summarize_search_results([], limit=5)
    assert summary["total_sessions"] == 0
    assert summary["returned_sessions"] == 0
    assert summary["sessions"] == []


def test_summarize_search_results_content_truncation():
    """_summarize_search_results truncates content to 300 chars."""
    long_content = "x" * 500
    results = [
        {"session_id": "s1", "timestamp": "2026-06-21T10:00:00", "role": "user", "content": long_content},
    ]
    summary = _summarize_search_results(results, limit=5)
    match_content = summary["sessions"][0]["matches"][0]["content"]
    assert len(match_content) <= 300, f"Content not truncated: {len(match_content)}"


# ---------------------------------------------------------------------------
# _format_recent_sessions
# ---------------------------------------------------------------------------

def test_format_recent_sessions_empty():
    """_format_recent_sessions with empty list returns message."""
    result = _format_recent_sessions([])
    assert "No recent sessions" in result, f"Got {result}"


def test_format_recent_sessions_with_data():
    """_format_recent_sessions includes session info."""
    workdir = Path(tempfile.mkdtemp(prefix="ss_fmt_"))
    try:
        _setup_db(workdir)
        session_db.record_session_start("fmt-1", "/workspace")
        session_db.record_conversation("fmt-1", "user", "test prompt")

        sessions = session_db.list_sessions()
        result = _format_recent_sessions(sessions)

        assert "fmt-1" in result
        assert "workspace" in result.lower() or "/workspace" in result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# session_search_tool
# ---------------------------------------------------------------------------

def test_session_search_tool_no_query():
    """session_search_tool with no query returns recent sessions."""
    workdir = Path(tempfile.mkdtemp(prefix="ss_tool_"))
    try:
        _setup_db(workdir)
        session_db.record_session_start("tool-1", "/ws")
        session_db.record_conversation("tool-1", "user", "hello")

        result = session_search_tool()
        assert "tool-1" in result, f"Session not found in output: {result[:200]}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_session_search_tool_with_query():
    """session_search_tool with query searches conversations."""
    workdir = Path(tempfile.mkdtemp(prefix="ss_tool_"))
    try:
        _setup_db(workdir)
        session_db.record_session_start("tool-q", "/ws")
        session_db.record_conversation("tool-q", "user", "pytest rocks")

        result = session_search_tool(query="pytest")
        parsed = json.loads(result)
        assert parsed["total_sessions"] >= 1, f"Expected matches, got {parsed}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_session_search_tool_no_results():
    """session_search_tool with non-matching query returns empty."""
    workdir = Path(tempfile.mkdtemp(prefix="ss_tool_"))
    try:
        _setup_db(workdir)
        session_db.record_session_start("tool-nr", "/ws")
        session_db.record_conversation("tool-nr", "user", "hello world")

        result = session_search_tool(query="zzz_nonexistent_zzz")
        parsed = json.loads(result)
        assert parsed["total_sessions"] == 0, f"Expected 0, got {parsed}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_session_search_tool_role_filter():
    """session_search_tool with role_filter only includes specified roles."""
    workdir = Path(tempfile.mkdtemp(prefix="ss_tool_"))
    try:
        _setup_db(workdir)
        session_db.record_session_start("tool-rf", "/ws")
        session_db.record_conversation("tool-rf", "user", "question")
        session_db.record_conversation("tool-rf", "assistant", "answer")

        result = session_search_tool(query="question OR answer", role_filter="user")
        parsed = json.loads(result)
        # All matches should be from 'user' role
        for session in parsed.get("sessions", []):
            for match in session.get("matches", []):
                assert match["role"] == "user", f"Non-user role found: {match['role']}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_session_search_tool_limit():
    """session_search_tool respects limit parameter."""
    workdir = Path(tempfile.mkdtemp(prefix="ss_tool_"))
    try:
        _setup_db(workdir)
        for i in range(5):
            session_db.record_session_start(f"tool-lim-{i}", "/ws")
            session_db.record_conversation(f"tool-lim-{i}", "user", "shared topic")

        result = session_search_tool(query="shared topic", limit=2)
        parsed = json.loads(result)
        assert parsed["returned_sessions"] <= 2, f"Limit not respected: {parsed['returned_sessions']}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# session_history_tool
# ---------------------------------------------------------------------------

def test_session_history_tool():
    """session_history_tool returns full history for a session."""
    workdir = Path(tempfile.mkdtemp(prefix="ss_hist_"))
    try:
        _setup_db(workdir)
        session_db.record_session_start("hist-1", "/ws")
        session_db.record_conversation("hist-1", "user", "q1")
        session_db.record_conversation("hist-1", "assistant", "a1")

        result = session_history_tool("hist-1")
        parsed = json.loads(result)
        assert parsed["session_id"] == "hist-1"
        assert parsed["message_count"] == 2
        assert len(parsed["history"]) == 2
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_session_history_tool_empty():
    """session_history_tool returns error for unknown session."""
    workdir = Path(tempfile.mkdtemp(prefix="ss_hist_"))
    try:
        _setup_db(workdir)
        result = session_history_tool("nonexistent")
        parsed = json.loads(result)
        assert "error" in parsed
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_format_timestamp_valid,
    test_format_timestamp_with_timezone,
    test_format_timestamp_invalid,
    test_format_timestamp_none,
    test_summarize_search_results_grouping,
    test_summarize_search_results_limit,
    test_summarize_search_results_empty,
    test_summarize_search_results_content_truncation,
    test_format_recent_sessions_empty,
    test_format_recent_sessions_with_data,
    test_session_search_tool_no_query,
    test_session_search_tool_with_query,
    test_session_search_tool_no_results,
    test_session_search_tool_role_filter,
    test_session_search_tool_limit,
    test_session_history_tool,
    test_session_history_tool_empty,
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
