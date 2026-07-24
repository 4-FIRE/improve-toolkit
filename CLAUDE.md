# CLAUDE.md

This file provides guidance to Claude Code when working with this dual-host
Codex and Claude Code plugin. Codex uses `AGENTS.md`.

## MCP Servers

One MCP server is configured in `.claude-plugin/plugin.json`:

1. **improve** (local): Python MCP server exposing memory, skill_manage tools

## Commands

```bash
# Run all unit tests (scripts/tests/)
python scripts/run_tests.py

# Run a single test file
python scripts/tests/test_load_memory.py
```

## Architecture

### Hook Pipeline

Session lifecycle hooks are defined in `hooks/hooks.json`. Each hook runs via `scripts/run_hook <script.py>` which resolves a Python 3 interpreter. Hook scripts follow a uniform pattern:

1. Read JSON payload from stdin (`hook_logger.read_hook_input`)
2. Process (log, persist, transform)
3. Print JSON result to stdout (consumed by Claude Code)

At SessionStart, `session_context.py` injects general working guidance and
`load_memory.py` injects the memory/user profile snapshot.

### Scripts Layer (`scripts/`)

Pure stdlib Python — no virtualenv needed (unlike `servers/`).

| Module | Role |
|---|---|
| `hook_logger.py` | Shared stdin reader + file logger for all hooks |
| `runtime_paths.py` | Resolves project paths for Codex and Claude Code |
| `session_context.py` | Builds the shared agent prompt with workbench path, emits SessionStart context |
| `load_memory.py` | Reads host-specific `MEMORY.md`/`USER.md` files and renders prompt blocks |

### Data Flow

```
hooks.json → run_hook → hook script → session_context.py (persona) → load_memory.py (memories)
```

Claude memory files live in `.claude/memories/`; Codex memory files live in
`.codex/improve-toolkit/memories/`. `MEMORY.md` and `USER.md` use `§` as the
entry delimiter.

### Plugin Structure

- `.claude-plugin/` — Plugin metadata and MCP server config
- `.codex-plugin/` and `.mcp.json` — Codex plugin metadata and MCP config
- `servers/` — MCP server (has its own `.venv`, `pyproject.toml`)
- `scripts/` — Hook scripts and utilities (stdlib only, no venv)
- `scripts/tests/` — Unit tests (stdlib, run individually or via `run_tests.py`)
- `hooks/hooks.json` — Hook configuration
- `skills/` — Skill definitions
- `agents/` — Agent definitions (currently empty)
- `commands/` — Workflow commands (currently empty)

### Versioning

The plugin version lives in **two** files that must be kept in sync — forgetting one leaves the marketplace listing stale:

- `.claude-plugin/plugin.json` → `version`
- `.claude-plugin/marketplace.json` → `plugins[].version`

When bumping the version, update both and commit together.
