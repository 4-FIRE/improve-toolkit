# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## MCP Servers

One MCP server is configured in `.claude-plugin/plugin.json`:

1. **4-fire** (local): Python MCP server exposing memory, skill_manage, session_search, session_history tools

## Commands

```bash
# Run all unit tests (scripts/tests/)
python scripts/run_tests.py

# Run a single test file
python scripts/tests/test_session_db.py
```

## Architecture

### Hook Pipeline

Session lifecycle hooks are defined in `hooks/hooks.json`. Each hook runs via `scripts/run_hook <script.py>` which resolves a Python 3 interpreter. Hook scripts follow a uniform pattern:

1. Read JSON payload from stdin (`hook_logger.read_hook_input`)
2. Process (log, persist, transform)
3. Print JSON result to stdout (consumed by Claude Code)

**Execution order at SessionStart:** `session_context.py` (persona injection) → `load_memory.py` (memory/user profile) → `hook_session_start.py` (DB record).

### Scripts Layer (`scripts/`)

Pure stdlib Python — no virtualenv needed (unlike `servers/`).

| Module | Role |
|---|---|
| `session_db.py` | Central data layer — SQLite CRUD for sessions, conversations, transcripts |
| `session_search.py` | Search/history CLI + MCP tool wrappers over session_db |
| `hook_logger.py` | Shared stdin reader + file logger for all hooks |
| `session_context.py` | Builds persona prompt with workbench path, emits SessionStart context |
| `load_memory.py` | Reads `MEMORY.md`/`USER.md` from `.claude/memories/`, renders prompt blocks |

### Data Flow

```
hooks.json → run_hook → hook script → session_db.py → .claude/sessions/sessions.db
                                                  ↕
                                   session_search.py (query/CLI)
```

All persistent state lives in SQLite at `$CLAUDE_PROJECT_DIR/.claude/sessions/sessions.db`. Memory files live in `.claude/memories/` (MEMORY.md, USER.md), separated by `§` delimiter.

### Plugin Structure

- `.claude-plugin/` — Plugin metadata and MCP server config
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
