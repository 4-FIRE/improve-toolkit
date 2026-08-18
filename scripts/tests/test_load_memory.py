#!/usr/bin/env python3
"""Behavior tests for the SessionStart memory-summary adapter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory_catalog import MemoryCatalog, MemoryChange


SCRIPT = Path(__file__).resolve().parent.parent / "load_memory.py"


def run_load_memory(workdir: Path, host: str = "claude") -> dict:
    env = dict(os.environ)
    for key in (
        "PLUGIN_ROOT",
        "IMPROVE_HOST",
        "IMPROVE_PROJECT_DIR",
        "IMPROVE_DATA_DIR",
        "IMPROVE_MEMORY_DIR",
    ):
        env.pop(key, None)
    if host == "codex":
        env.pop("CLAUDE_PROJECT_DIR", None)
        env["PLUGIN_ROOT"] = str(SCRIPT.parent.parent)
    else:
        env["CLAUDE_PROJECT_DIR"] = str(workdir)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def seed_summary(workdir: Path) -> None:
    data_home = workdir / ".improve-toolkit"
    catalog = MemoryCatalog(
        memory_dir=data_home / "memories",
        data_home=data_home,
    )
    catalog.apply(
        MemoryChange(
            action="add",
            target="memory",
            content=(
                "Release versions stay synchronized across plugin manifests.\n"
                "FULL-DETAIL-MUST-STAY-ON-DEMAND"
            ),
        )
    )


def test_main_output_format() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="lm_format_"))
    try:
        data = run_load_memory(workdir)
        assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "additionalContext" in data["hookSpecificOutput"]
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_main_without_memory_is_empty() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="lm_empty_"))
    try:
        data = run_load_memory(workdir)
        assert data["hookSpecificOutput"]["additionalContext"] == ""
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_main_without_summary_never_injects_full_memory() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="lm_summary_missing_"))
    try:
        mem_dir = workdir / ".improve-toolkit" / "memories"
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text(
            "FULL-DETAIL-THAT-MUST-STAY-OUT-OF-SESSIONSTART",
            encoding="utf-8",
        )
        context = run_load_memory(workdir)["hookSpecificOutput"]["additionalContext"]
        assert "FULL-DETAIL" not in context
        assert "memory_recall" in context
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_main_loads_materialized_summary_only() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="lm_summary_"))
    try:
        seed_summary(workdir)
        context = run_load_memory(workdir)["hookSpecificOutput"]["additionalContext"]
        assert "Release versions stay synchronized" in context
        assert "FULL-DETAIL" not in context
        assert "memory_recall" in context
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_legacy_memory_only_prompts_recall_without_loading_body() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="lm_legacy_"))
    try:
        legacy_dir = workdir / ".claude" / "memories"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "MEMORY.md").write_text(
            "LEGACY-FULL-BODY-MUST-STAY-ON-DEMAND",
            encoding="utf-8",
        )
        context = run_load_memory(workdir)["hookSpecificOutput"]["additionalContext"]
        assert "LEGACY-FULL-BODY" not in context
        assert "memory_recall" in context
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_corrupt_summary_fails_closed() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="lm_corrupt_"))
    try:
        seed_summary(workdir)
        summary = workdir / ".improve-toolkit" / "memories" / "SUMMARY.md"
        summary.write_text("STALE OR TAMPERED DETAIL", encoding="utf-8")
        context = run_load_memory(workdir)["hookSpecificOutput"]["additionalContext"]
        assert "STALE OR TAMPERED" not in context
        assert "memory_recall" in context
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_hosts_load_same_shared_summary() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="lm_hosts_"))
    try:
        seed_summary(workdir)
        claude = run_load_memory(workdir, host="claude")["hookSpecificOutput"]["additionalContext"]
        codex = run_load_memory(workdir, host="codex")["hookSpecificOutput"]["additionalContext"]
        assert codex == claude
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


ALL_TESTS = [
    test_main_output_format,
    test_main_without_memory_is_empty,
    test_main_without_summary_never_injects_full_memory,
    test_main_loads_materialized_summary_only,
    test_legacy_memory_only_prompts_recall_without_loading_body,
    test_corrupt_summary_fails_closed,
    test_hosts_load_same_shared_summary,
]


def main() -> None:
    passed = 0
    failed = 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
