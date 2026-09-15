#!/usr/bin/env python3
"""Check prompt references, not a model's behavior from exact prose matches."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IMPROVE_SKILL = ROOT / "skills" / "improve" / "SKILL.md"
SKILL_CANDIDATES = ROOT / "skills" / "improve" / "SKILL-CANDIDATES.md"
SESSION_CONTEXT = ROOT / "scripts" / "session_context.py"
MEMORY_TOOL = ROOT / "servers" / "memory" / "tools.py"


def test_skill_resource_links_resolve() -> None:
    for path in (ROOT / "skills").rglob("*.md"):
        links = re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8"))
        for link in links:
            if "://" in link or link.startswith("#"):
                continue
            if "<" in link or link.startswith("./src/"):
                continue
            assert (path.parent / link.split("#")[0]).is_file(), (path, link)


def test_prompt_tool_references_match_exposed_schemas() -> None:
    module = ast.parse(MEMORY_TOOL.read_text(encoding="utf-8"))
    names = set()
    for node in module.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Constant) and key.value == "name":
                names.add(ast.literal_eval(value))
    for path in (SESSION_CONTEXT, IMPROVE_SKILL):
        mentioned = set(re.findall(r"`(memory(?:_recall)?)`", path.read_text(encoding="utf-8")))
        assert mentioned == names


def test_referenced_skills_are_available() -> None:
    for path in (SESSION_CONTEXT, IMPROVE_SKILL, SKILL_CANDIDATES):
        referenced = re.findall(r"`(improve)`", path.read_text(encoding="utf-8"))
        for name in referenced:
            assert (ROOT / "skills" / name / "SKILL.md").is_file(), name
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    for prompt in manifest["interface"]["defaultPrompt"]:
        for name in re.findall(r"\$([a-z][a-z0-9-]*)", prompt):
            assert (ROOT / "skills" / name / "SKILL.md").is_file(), name


ALL_TESTS = [
    test_skill_resource_links_resolve,
    test_prompt_tool_references_match_exposed_schemas,
    test_referenced_skills_are_available,
]


def main() -> None:
    failed = 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"  PASS  {test.__name__}")
        except Exception as exc:
            print(f"  FAIL  {test.__name__}: {exc}")
            failed += 1
    print(f"\n{len(ALL_TESTS) - failed} passed, {failed} failed, {len(ALL_TESTS)} total")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
