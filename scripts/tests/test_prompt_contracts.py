#!/usr/bin/env python3
"""Cross-file contract tests for memory and skill-authoring prompts."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IMPROVE_SKILL = ROOT / "skills" / "improve" / "SKILL.md"
SKILL_CANDIDATES = ROOT / "skills" / "improve" / "SKILL-CANDIDATES.md"
SESSION_CONTEXT = ROOT / "scripts" / "session_context.py"
MEMORY_TOOL = ROOT / "servers" / "tools" / "memory_tool.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_durability_gate_has_one_source() -> None:
    sources = {
        "session_context": read(SESSION_CONTEXT),
        "improve": read(IMPROVE_SKILL),
        "skill_candidates": read(SKILL_CANDIDATES),
        "memory_tool": read(MEMORY_TOOL),
    }
    pattern = re.compile(r"(?:1|3) weeks?|[一三]周")
    matches = {
        name: pattern.findall(content)
        for name, content in sources.items()
        if pattern.search(content)
    }
    assert matches == {"session_context": ["1 week"]}, matches


def test_improve_discloses_skill_candidate_branch() -> None:
    skill = read(IMPROVE_SKILL)
    assert "[`SKILL-CANDIDATES.md`](SKILL-CANDIDATES.md)" in skill
    assert "`memory` 工具 schema 是保存触发、条目格式、target 和 action 的唯一事实源" in skill
    for classification in ("`add`", "`replace`", "`remove`", "`no-op`", "`reject`"):
        assert classification in skill
    assert SKILL_CANDIDATES.is_file()


def test_recall_contract_is_shared_by_session_and_curation() -> None:
    session = read(SESSION_CONTEXT)
    skill = read(IMPROVE_SKILL)

    assert "Call `memory_recall`" in session
    assert "current sources and explicit user corrections take priority" in session
    assert "调用 `memory_recall`" in skill
    assert "`entry_id` 与 `revision`" in skill
    assert "`REVISION_CONFLICT`" in skill


def test_skill_candidate_policy_is_exhaustive() -> None:
    policy = read(SKILL_CANDIDATES)
    assert "候选必须同时满足四项" in policy
    assert "至少满足以下三项" not in policy
    for state in ("## Candidate", "## Proposal", "## Authorized", "## Implemented"):
        assert state in policy
    assert "用户主动要求一项范围明确的技能创建、修改、移动或删除" in policy
    assert "用户接受具体 proposal" in policy


ALL_TESTS = [
    test_durability_gate_has_one_source,
    test_improve_discloses_skill_candidate_branch,
    test_recall_contract_is_shared_by_session_and_curation,
    test_skill_candidate_policy_is_exhaustive,
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
        sys.exit(1)


if __name__ == "__main__":
    main()
