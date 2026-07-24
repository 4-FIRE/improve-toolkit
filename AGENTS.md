# AGENTS.md

This repository is a dual-host plugin for Codex and Claude Code.

## Commands

```bash
# Hook and path unit tests (stdlib only)
python scripts/run_tests.py

# MCP tool tests (creates servers/.venv and may install dependencies)
python servers/test_tools.py

# End-to-end stdio MCP protocol smoke test
servers/.venv/bin/python servers/test_mcp_protocol.py

# Validate the Codex plugin manifest
python /path/to/plugin-creator/scripts/validate_plugin.py .
```

## Architecture

- `.codex-plugin/plugin.json` and `.mcp.json` configure Codex.
- `.claude-plugin/plugin.json` configures Claude Code.
- `skills/` contains the workflows bundled by both hosts.
- `hooks/hooks.json` is shared by both hosts. Codex discovers it by convention.
- `servers/` contains the local stdio MCP server exposing `memory` and `skill_manage`.
- `scripts/` contains stdlib-only SessionStart hooks and shared runtime path resolution.

Runtime state is project-scoped:

- Claude Code: `.claude/memories`, `.claude/skills`, `.claude/logs`, and `.claude/workbench`.
- Codex: `.codex/improve-toolkit/{memories,logs,workbench}` and `.agents/skills`.

`IMPROVE_PROJECT_DIR`, `IMPROVE_DATA_DIR`, and `IMPROVE_SKILLS_DIR` override the
default paths. `IMPROVE_HOST` selects `claude` or `codex`.

## Versioning

Keep these versions synchronized for releases:

- `.codex-plugin/plugin.json`
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
