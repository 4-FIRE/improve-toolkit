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
- Production MCP environments use the per-user, fingerprinted cache resolved by
  `scripts/venv_cache.py`; repository tests may keep using `servers/.venv`.

Runtime state is project-scoped:

- Shared runtime data: `.improve-toolkit/{memories,logs,workbench}`.
- Claude Code skills: `.claude/skills`.
- Codex skills: `.agents/skills`.

`.improve-toolkit/.gitignore` excludes logs, workbench files, locks, and
temporary writes. Memory Markdown files remain trackable and belong in the
repository.

`IMPROVE_PROJECT_DIR`, `IMPROVE_DATA_DIR`, `IMPROVE_MEMORY_DIR`, and
`IMPROVE_SKILLS_DIR` override the default paths. `IMPROVE_HOST` selects
`claude` or `codex`.

`IMPROVE_CACHE_DIR`, `IMPROVE_VENV_DIR`, and `IMPROVE_PYTHON` override MCP
bootstrap locations. Keep exact dependency pins synchronized between
`servers/requirements.lock` and `servers/pyproject.toml`.

## Versioning

Keep these versions synchronized for releases:

- `.codex-plugin/plugin.json`
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
