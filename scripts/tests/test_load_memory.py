#!/usr/bin/env python3
"""
Tests for scripts/load_memory.py — run with:
    python scripts/tests/test_load_memory.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from load_memory import (
    ENTRY_DELIMITER,
    MEMORY_CHAR_LIMIT,
    USER_CHAR_LIMIT,
    read_entries,
    render_block,
)

SCRIPT = Path(__file__).resolve().parent.parent / "load_memory.py"


# ---------------------------------------------------------------------------
# read_entries
# ---------------------------------------------------------------------------

def test_read_entries_normal():
    """read_entries splits a file by ENTRY_DELIMITER."""
    workdir = Path(tempfile.mkdtemp(prefix="lm_test_"))
    try:
        f = workdir / "test.md"
        f.write_text(f"entry one{ENTRY_DELIMITER}entry two{ENTRY_DELIMITER}entry three")
        entries = read_entries(f)
        assert entries == ["entry one", "entry two", "entry three"], f"Got {entries}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_read_entries_nonexistent():
    """read_entries returns [] for a missing file."""
    result = read_entries(Path("/nonexistent/path/MEMORY.md"))
    assert result == [], f"Expected [], got {result}"


def test_read_entries_empty_file():
    """read_entries returns [] for an empty file."""
    workdir = Path(tempfile.mkdtemp(prefix="lm_test_"))
    try:
        f = workdir / "empty.md"
        f.write_text("")
        assert read_entries(f) == []
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_read_entries_whitespace_only():
    """read_entries returns [] for a whitespace-only file."""
    workdir = Path(tempfile.mkdtemp(prefix="lm_test_"))
    try:
        f = workdir / "blank.md"
        f.write_text("   \n\n  \t  ")
        assert read_entries(f) == []
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_read_entries_preserves_duplicates():
    """read_entries returns all entries including duplicates (dedup is in main)."""
    workdir = Path(tempfile.mkdtemp(prefix="lm_test_"))
    try:
        f = workdir / "dup.md"
        f.write_text(f"alpha{ENTRY_DELIMITER}beta{ENTRY_DELIMITER}alpha{ENTRY_DELIMITER}gamma")
        entries = read_entries(f)
        assert entries == ["alpha", "beta", "alpha", "gamma"], f"Got {entries}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_read_entries_strips_whitespace():
    """read_entries strips leading/trailing whitespace from each entry."""
    workdir = Path(tempfile.mkdtemp(prefix="lm_test_"))
    try:
        f = workdir / "ws.md"
        f.write_text(f"  entry A  {ENTRY_DELIMITER}  entry B  ")
        entries = read_entries(f)
        assert entries == ["entry A", "entry B"], f"Got {entries}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# render_block
# ---------------------------------------------------------------------------

def test_render_block_memory():
    """render_block('memory', ...) includes MEMORY header."""
    entries = ["fact one", "fact two"]
    result = render_block("memory", entries)
    assert "MEMORY" in result, f"Missing MEMORY header: {result[:100]}"
    assert "fact one" in result
    assert "fact two" in result


def test_render_block_user():
    """render_block('user', ...) includes USER PROFILE header."""
    entries = ["user is a dev"]
    result = render_block("user", entries)
    assert "USER PROFILE" in result, f"Missing USER PROFILE header: {result[:100]}"
    assert "user is a dev" in result


def test_render_block_empty_entries():
    """render_block returns '' for empty entries."""
    assert render_block("memory", []) == ""
    assert render_block("user", []) == ""


def test_render_block_percentage():
    """render_block shows correct percentage usage."""
    # Create entries that fill ~50% of memory limit
    entry = "x" * (MEMORY_CHAR_LIMIT // 2)
    result = render_block("memory", [entry])
    assert "50%" in result, f"Expected ~50% in header, got: {result[:200]}"


def test_render_block_over_limit():
    """render_block caps percentage at 100%."""
    entry = "x" * (MEMORY_CHAR_LIMIT * 2)
    result = render_block("memory", [entry])
    assert "100%" in result, f"Expected 100% in header, got: {result[:200]}"


def test_render_block_separator():
    """render_block uses ═ separator lines."""
    result = render_block("memory", ["test"])
    assert "═" * 46 in result, f"Missing separator line"


# ---------------------------------------------------------------------------
# main (subprocess)
# ---------------------------------------------------------------------------

def run_load_memory(workdir: Path) -> dict:
    """Run load_memory.py as subprocess, return parsed JSON."""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(workdir)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_main_output_format():
    """main() outputs valid JSON with hookSpecificOutput."""
    workdir = Path(tempfile.mkdtemp(prefix="lm_test_"))
    try:
        data = run_load_memory(workdir)
        assert "hookSpecificOutput" in data
        assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "additionalContext" in data["hookSpecificOutput"]
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_main_no_memory_files():
    """main() with no memory files outputs empty additionalContext."""
    workdir = Path(tempfile.mkdtemp(prefix="lm_test_"))
    try:
        data = run_load_memory(workdir)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert ctx == "", f"Expected empty context, got: {ctx[:200]}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_main_with_memory_file():
    """main() includes memory content when MEMORY.md exists."""
    workdir = Path(tempfile.mkdtemp(prefix="lm_test_"))
    try:
        mem_dir = workdir / ".claude" / "memories"
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text("project uses pytest")

        data = run_load_memory(workdir)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "project uses pytest" in ctx, f"Memory content missing: {ctx[:200]}"
        assert "MEMORY" in ctx
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_main_with_user_file():
    """main() includes user content when USER.md exists."""
    workdir = Path(tempfile.mkdtemp(prefix="lm_test_"))
    try:
        mem_dir = workdir / ".claude" / "memories"
        mem_dir.mkdir(parents=True)
        (mem_dir / "USER.md").write_text("senior engineer")

        data = run_load_memory(workdir)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "senior engineer" in ctx
        assert "USER PROFILE" in ctx
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_main_with_both_files():
    """main() includes both user and memory sections."""
    workdir = Path(tempfile.mkdtemp(prefix="lm_test_"))
    try:
        mem_dir = workdir / ".claude" / "memories"
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text("fact A")
        (mem_dir / "USER.md").write_text("person B")

        data = run_load_memory(workdir)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "fact A" in ctx
        assert "person B" in ctx
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_read_entries_normal,
    test_read_entries_nonexistent,
    test_read_entries_empty_file,
    test_read_entries_whitespace_only,
    test_read_entries_preserves_duplicates,
    test_read_entries_strips_whitespace,
    test_render_block_memory,
    test_render_block_user,
    test_render_block_empty_entries,
    test_render_block_percentage,
    test_render_block_over_limit,
    test_render_block_separator,
    test_main_output_format,
    test_main_no_memory_files,
    test_main_with_memory_file,
    test_main_with_user_file,
    test_main_with_both_files,
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
