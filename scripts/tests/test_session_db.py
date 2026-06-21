#!/usr/bin/env python3
"""
Tests for scripts/session_db.py — run with:
    python scripts/tests/test_session_db.py
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Patch CLAUDE_PROJECT_DIR before importing session_db so get_home() resolves
# to our temp directory.
_workdir = Path(tempfile.mkdtemp(prefix="sdb_test_"))
os.environ["CLAUDE_PROJECT_DIR"] = str(_workdir)

import session_db


def _fresh_db() -> Path:
    """Create a fresh temp workdir and point session_db at it."""
    workdir = Path(tempfile.mkdtemp(prefix="sdb_test_"))
    os.environ["CLAUDE_PROJECT_DIR"] = str(workdir)
    db_path = workdir / ".claude" / "sessions" / "sessions.db"
    return db_path


def _cleanup(workdir: Path):
    shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# init_database
# ---------------------------------------------------------------------------

def test_init_database_creates_tables():
    """init_database creates sessions, conversations, transcripts tables."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]  # .claude is 2 levels up from sessions.db
    try:
        session_db.init_database(db_path)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        for t in ("sessions", "conversations", "transcripts"):
            assert t in tables, f"Table '{t}' not found; got {tables}"
    finally:
        _cleanup(workdir)


def test_init_database_creates_indexes():
    """init_database creates expected indexes."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall()}
        conn.close()

        expected = [
            "idx_conversations_session_id",
            "idx_conversations_timestamp",
            "idx_conversations_content",
            "idx_transcripts_session_id",
        ]
        for idx in expected:
            assert idx in indexes, f"Index '{idx}' not found; got {indexes}"
    finally:
        _cleanup(workdir)


def test_init_database_idempotent():
    """Calling init_database twice does not fail."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.init_database(db_path)  # second call
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "sessions" in tables
    finally:
        _cleanup(workdir)


# ---------------------------------------------------------------------------
# record_session_start / record_session_end
# ---------------------------------------------------------------------------

def test_record_session_start():
    """record_session_start inserts a session row."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start(
            "sess-001", "/workspace",
            metadata={"key": "val"},
            transcript_path="/tmp/t.jsonl",
            cwd="/workspace",
            permission_mode="auto",
            agent_type="main",
        )

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT id, workspace, status, permission_mode, agent_type FROM sessions WHERE id = 'sess-001'")
        row = cursor.fetchone()
        conn.close()

        assert row is not None, "Session row not found"
        assert row[0] == "sess-001"
        assert row[1] == "/workspace"
        assert row[2] == "active"
        assert row[3] == "auto"
        assert row[4] == "main"
    finally:
        _cleanup(workdir)


def test_record_session_start_replace():
    """record_session_start with existing id replaces the row."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-r", "/old")
        session_db.record_session_start("sess-r", "/new")

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT workspace FROM sessions WHERE id = 'sess-r'")
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "/new", f"Expected '/new', got {row[0]}"
    finally:
        _cleanup(workdir)


def test_record_session_end():
    """record_session_end updates end_time and status."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-end", "/ws")
        session_db.record_session_end("sess-end", {"done": True})

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT end_time, status, metadata FROM sessions WHERE id = 'sess-end'")
        row = cursor.fetchone()
        conn.close()

        assert row[0] is not None, "end_time should be set"
        assert row[1] == "completed", f"Expected 'completed', got {row[1]}"
        meta = json.loads(row[2])
        assert meta["done"] is True
    finally:
        _cleanup(workdir)


# ---------------------------------------------------------------------------
# record_conversation
# ---------------------------------------------------------------------------

def test_record_conversation():
    """record_conversation inserts a conversation row."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-conv", "/ws")
        session_db.record_conversation("sess-conv", "user", "hello", {"tag": "t"})

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT role, content, metadata FROM conversations WHERE session_id = 'sess-conv'")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][0] == "user"
        assert rows[0][1] == "hello"
        meta = json.loads(rows[0][2])
        assert meta["tag"] == "t"
    finally:
        _cleanup(workdir)


def test_record_conversation_multiple():
    """Multiple conversations can be recorded for the same session."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-multi", "/ws")
        session_db.record_conversation("sess-multi", "user", "q1")
        session_db.record_conversation("sess-multi", "assistant", "a1")
        session_db.record_conversation("sess-multi", "user", "q2")

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM conversations WHERE session_id = 'sess-multi'")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 3, f"Expected 3, got {count}"
    finally:
        _cleanup(workdir)


# ---------------------------------------------------------------------------
# search_conversations
# ---------------------------------------------------------------------------

def test_search_conversations_basic():
    """search_conversations finds matching content."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-search", "/ws")
        session_db.record_conversation("sess-search", "user", "pytest is great")
        session_db.record_conversation("sess-search", "assistant", "yes it is")

        results = session_db.search_conversations("pytest")
        assert len(results) >= 1, f"Expected at least 1 result, got {len(results)}"
        assert any("pytest" in r["content"] for r in results)
    finally:
        _cleanup(workdir)


def test_search_conversations_by_session():
    """search_conversations with session_id filters to that session."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-a", "/ws")
        session_db.record_conversation("sess-a", "user", "alpha topic")
        session_db.record_session_start("sess-b", "/ws")
        session_db.record_conversation("sess-b", "user", "alpha topic too")

        results = session_db.search_conversations("alpha", session_id="sess-a")
        assert all(r["session_id"] == "sess-a" for r in results), \
            f"Expected only sess-a results, got {[r['session_id'] for r in results]}"
    finally:
        _cleanup(workdir)


def test_search_conversations_no_match():
    """search_conversations returns empty list when nothing matches."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-nomatch", "/ws")
        session_db.record_conversation("sess-nomatch", "user", "hello world")

        results = session_db.search_conversations("zzz_nonexistent_zzz")
        assert results == [], f"Expected empty, got {results}"
    finally:
        _cleanup(workdir)


def test_search_conversations_limit_offset():
    """search_conversations respects limit and offset."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-pag", "/ws")
        for i in range(5):
            session_db.record_conversation("sess-pag", "user", f"item {i}")

        r1 = session_db.search_conversations("item", limit=2, offset=0)
        r2 = session_db.search_conversations("item", limit=2, offset=2)
        assert len(r1) == 2
        assert len(r2) == 2
        # Ensure different pages return different results
        ids1 = {r["id"] for r in r1}
        ids2 = {r["id"] for r in r2}
        assert ids1.isdisjoint(ids2), "Pages should not overlap"
    finally:
        _cleanup(workdir)


# ---------------------------------------------------------------------------
# get_session_history
# ---------------------------------------------------------------------------

def test_get_session_history():
    """get_session_history returns messages in chronological order."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-hist", "/ws")
        session_db.record_conversation("sess-hist", "user", "first")
        session_db.record_conversation("sess-hist", "assistant", "second")
        session_db.record_conversation("sess-hist", "user", "third")

        history = session_db.get_session_history("sess-hist")
        assert len(history) == 3
        assert history[0]["content"] == "first"
        assert history[1]["content"] == "second"
        assert history[2]["content"] == "third"
    finally:
        _cleanup(workdir)


def test_get_session_history_empty():
    """get_session_history returns empty list for unknown session."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        history = session_db.get_session_history("nonexistent")
        assert history == [], f"Expected empty, got {history}"
    finally:
        _cleanup(workdir)


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

def test_list_sessions():
    """list_sessions returns all sessions."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-l1", "/ws1")
        session_db.record_session_start("sess-l2", "/ws2")

        sessions = session_db.list_sessions()
        ids = {s["id"] for s in sessions}
        assert "sess-l1" in ids
        assert "sess-l2" in ids
    finally:
        _cleanup(workdir)


def test_list_sessions_filter_by_status():
    """list_sessions with status filter returns only matching sessions."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-active", "/ws")
        session_db.record_session_start("sess-done", "/ws")
        session_db.record_session_end("sess-done")

        active = session_db.list_sessions(status="active")
        completed = session_db.list_sessions(status="completed")

        active_ids = {s["id"] for s in active}
        completed_ids = {s["id"] for s in completed}

        assert "sess-active" in active_ids
        assert "sess-done" in completed_ids
        assert "sess-active" not in completed_ids
    finally:
        _cleanup(workdir)


def test_list_sessions_limit():
    """list_sessions respects limit."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        for i in range(5):
            session_db.record_session_start(f"sess-lim-{i}", "/ws")

        sessions = session_db.list_sessions(limit=3)
        assert len(sessions) <= 3, f"Expected <= 3, got {len(sessions)}"
    finally:
        _cleanup(workdir)


# ---------------------------------------------------------------------------
# save_transcript / get_transcript
# ---------------------------------------------------------------------------

def test_save_and_get_transcript():
    """save_transcript writes lines, get_transcript reads them back."""
    workdir = Path(tempfile.mkdtemp(prefix="sdb_tr_"))
    try:
        os.environ["CLAUDE_PROJECT_DIR"] = str(workdir)
        db_path = workdir / ".claude" / "sessions" / "sessions.db"
        session_db.init_database(db_path)
        session_db.record_session_start("sess-tr", "/ws")

        # Create a transcript file
        tr_file = workdir / "transcript.jsonl"
        lines = [
            json.dumps({"type": "user", "timestamp": "2026-01-01T00:00:00", "message": {"content": "hi"}}),
            json.dumps({"type": "assistant", "timestamp": "2026-01-01T00:00:01", "message": {"content": "hello"}}),
        ]
        tr_file.write_text("\n".join(lines) + "\n")

        session_db.save_transcript("sess-tr", str(tr_file))
        transcript = session_db.get_transcript("sess-tr")

        assert len(transcript) == 2, f"Expected 2 lines, got {len(transcript)}"
        assert transcript[0]["line_number"] == 1
        assert transcript[1]["line_number"] == 2
        # line_data should be parsed JSON
        assert isinstance(transcript[0]["line_data"], dict)
        assert transcript[0]["line_data"]["type"] == "user"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_save_transcript_empty_path():
    """save_transcript with empty path does nothing (no crash)."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-empty-tr", "/ws")
        session_db.save_transcript("sess-empty-tr", "")

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM transcripts WHERE session_id = 'sess-empty-tr'")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 0, f"Expected 0 transcripts, got {count}"
    finally:
        _cleanup(workdir)


def test_save_transcript_nonexistent_file():
    """save_transcript with nonexistent file does nothing (no crash)."""
    db_path = _fresh_db()
    workdir = db_path.parents[2]
    try:
        session_db.init_database(db_path)
        session_db.record_session_start("sess-no-tr", "/ws")
        session_db.save_transcript("sess-no-tr", "/nonexistent/path.jsonl")

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM transcripts WHERE session_id = 'sess-no-tr'")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 0, f"Expected 0 transcripts, got {count}"
    finally:
        _cleanup(workdir)


def test_save_transcript_replaces_existing():
    """save_transcript deletes old transcript data before inserting new."""
    workdir = Path(tempfile.mkdtemp(prefix="sdb_trrepl_"))
    try:
        os.environ["CLAUDE_PROJECT_DIR"] = str(workdir)
        db_path = workdir / ".claude" / "sessions" / "sessions.db"
        session_db.init_database(db_path)
        session_db.record_session_start("sess-repl", "/ws")

        # First save
        tr1 = workdir / "tr1.jsonl"
        tr1.write_text('{"type":"user","timestamp":"2026-01-01"}\n')
        session_db.save_transcript("sess-repl", str(tr1))

        # Second save
        tr2 = workdir / "tr2.jsonl"
        tr2.write_text('{"type":"assistant","timestamp":"2026-01-02"}\n{"type":"user","timestamp":"2026-01-03"}\n')
        session_db.save_transcript("sess-repl", str(tr2))

        transcript = session_db.get_transcript("sess-repl")
        assert len(transcript) == 2, f"Expected 2 (replaced), got {len(transcript)}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_init_database_creates_tables,
    test_init_database_creates_indexes,
    test_init_database_idempotent,
    test_record_session_start,
    test_record_session_start_replace,
    test_record_session_end,
    test_record_conversation,
    test_record_conversation_multiple,
    test_search_conversations_basic,
    test_search_conversations_by_session,
    test_search_conversations_no_match,
    test_search_conversations_limit_offset,
    test_get_session_history,
    test_get_session_history_empty,
    test_list_sessions,
    test_list_sessions_filter_by_status,
    test_list_sessions_limit,
    test_save_and_get_transcript,
    test_save_transcript_empty_path,
    test_save_transcript_nonexistent_file,
    test_save_transcript_replaces_existing,
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
