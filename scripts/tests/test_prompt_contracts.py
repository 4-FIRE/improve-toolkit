#!/usr/bin/env python3
"""Check resource links, skill structure, and tool references."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IMPROVE_SKILL = ROOT / "skills" / "improve" / "SKILL.md"
SKILL_CANDIDATES = ROOT / "skills" / "improve" / "SKILL-CANDIDATES.md"
SESSION_CONTEXT = ROOT / "scripts" / "session_context.py"
MEMORY_TOOL = ROOT / "servers" / "memory" / "tools.py"
TOOL_PERMISSION_PREFIX = "mcp__plugin_improve-toolkit_improve__"
DEFAULT_SESSION_CONTEXT_CHAR_LIMIT = 800


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AssertionError(f"{path} is missing frontmatter")
    raw = text.split("---", 2)[1]
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        assert separator, (path, line)
        fields[key.strip()] = value.strip()
    return fields


def _exposed_tool_names() -> set[str]:
    module = ast.parse(MEMORY_TOOL.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in module.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Constant) and key.value == "name":
                names.add(ast.literal_eval(value))
    return names


def test_skill_resource_links_resolve() -> None:
    for path in (ROOT / "skills").rglob("*.md"):
        links = re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8"))
        for link in links:
            if "://" in link or link.startswith("#"):
                continue
            if "<" in link or link.startswith("./src/"):
                continue
            assert (path.parent / link.split("#")[0]).is_file(), (path, link)


def test_skill_frontmatter_matches_directory_and_invocation_policy() -> None:
    for skill_dir in sorted(path for path in (ROOT / "skills").iterdir() if path.is_dir()):
        skill = skill_dir / "SKILL.md"
        meta = _frontmatter(skill)
        assert meta.get("name") == skill_dir.name, skill
        assert meta.get("description"), skill
        disabled = meta.get("disable-model-invocation", "").lower() == "true"
        policy_path = skill_dir / "agents" / "openai.yaml"
        assert policy_path.is_file(), policy_path
        match = re.search(
            r"(?m)^\s*allow_implicit_invocation:\s*(\S+)",
            policy_path.read_text(encoding="utf-8"),
        )
        implicit_denied = bool(match and match.group(1).lower() == "false")
        assert disabled == implicit_denied, skill_dir.name


def test_prompt_tool_references_match_exposed_schemas() -> None:
    names = _exposed_tool_names()
    for path in (SESSION_CONTEXT, IMPROVE_SKILL, MEMORY_TOOL):
        mentioned = set(re.findall(r"`(memory(?:_recall)?)`", path.read_text(encoding="utf-8")))
        assert mentioned <= names, path


def test_claude_settings_permit_only_real_memory_tools() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    configured = {
        item[len(TOOL_PERMISSION_PREFIX):]
        for item in settings["permissions"]["allow"]
        if item.startswith(TOOL_PERMISSION_PREFIX)
    }
    assert configured == _exposed_tool_names()


def test_package_declares_node_engine() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["engines"]["node"] == ">=22.18"


def test_default_session_context_fits_budget() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="prompt_contract_session_"))
    env = dict(os.environ)
    for key in (
        "PLUGIN_ROOT",
        "IMPROVE_HOST",
        "IMPROVE_PROJECT_DIR",
        "IMPROVE_DATA_DIR",
        "IMPROVE_MEMORY_DIR",
        "IMPROVE_GLOBAL_GUIDANCE",
    ):
        env.pop(key, None)
    env["CLAUDE_PROJECT_DIR"] = str(workdir)
    try:
        result = subprocess.run(
            [sys.executable, str(SESSION_CONTEXT)],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert len(context) <= DEFAULT_SESSION_CONTEXT_CHAR_LIMIT
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_referenced_skills_are_available() -> None:
    for path in (SESSION_CONTEXT, IMPROVE_SKILL, SKILL_CANDIDATES, MEMORY_TOOL):
        referenced = re.findall(r"`(improve)`", path.read_text(encoding="utf-8"))
        for name in referenced:
            assert (ROOT / "skills" / name / "SKILL.md").is_file(), (path, name)
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    for prompt in manifest["interface"]["defaultPrompt"]:
        for name in re.findall(r"\$([a-z][a-z0-9-]*)", prompt):
            assert (ROOT / "skills" / name / "SKILL.md").is_file(), name


ALL_TESTS = [
    test_skill_resource_links_resolve,
    test_skill_frontmatter_matches_directory_and_invocation_policy,
    test_prompt_tool_references_match_exposed_schemas,
    test_claude_settings_permit_only_real_memory_tools,
    test_package_declares_node_engine,
    test_default_session_context_fits_budget,
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
