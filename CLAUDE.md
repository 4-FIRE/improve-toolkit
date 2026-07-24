# CLAUDE.md

This file provides guidance to Claude Code when working with this dual-host
Codex and Claude Code plugin. Codex uses `AGENTS.md`.

## MCP Servers

One MCP server is configured in `.claude-plugin/plugin.json`:

1. **improve** (local): Python MCP server exposing persistent memory

## Commands

```bash
# Run all unit tests (scripts/tests/)
python scripts/run_tests.py

# Run a single test file
python scripts/tests/test_load_memory.py
```

## Architecture

### Hook Pipeline

Session lifecycle hooks are defined in `hooks/hooks.json`. Each hook runs via
`scripts/run_hook <script.py>`, which resolves a Python 3 interpreter. SessionStart
hooks prepare their project-scoped state and print JSON context to stdout for the
host to consume.

At SessionStart, `session_context.py` injects general working guidance and
`load_memory.py` injects the memory/user profile snapshot.

### Scripts Layer (`scripts/`)

Pure stdlib Python — no virtualenv needed (unlike `servers/`).

| Module | Role |
|---|---|
| `runtime_paths.py` | Resolves project-scoped shared runtime paths |
| `file_ops.py` | Cross-platform advisory locks and atomic text writes |
| `memory_format.py` | Shared memory parsing, limits, serialization, and prompt rendering |
| `memory_migration.py` | Merges legacy host memory into the shared store |
| `venv_cache.py` | Resolves and prepares the cross-host MCP virtualenv cache |
| `session_context.py` | Builds the shared agent prompt with workbench path, emits SessionStart context |
| `load_memory.py` | Reads shared `MEMORY.md`/`USER.md` files and renders prompt blocks |

### Data Flow

```
hooks.json → run_hook → hook script → session_context.py (persona) → load_memory.py (memories)
```

Both hosts read and write `.improve-toolkit/memories/`. On first use, legacy
files from `.claude/memories/` and `.codex/improve-toolkit/memories/` are
deduplicated into the shared store. `MEMORY.md` and `USER.md` use `§` as the
entry delimiter. Verified synchronized entries are pruned from legacy files;
only unreadable, unverifiable, or unmatched entries remain for manual
resolution.

Logs and workbench files are also shared under `.improve-toolkit/`.
`prepare_data_home()` maintains `.improve-toolkit/.gitignore` so runtime noise
stays untracked while memory Markdown files remain repository content. Do not
replace this with a rule that ignores the whole `.improve-toolkit/` directory.

### Plugin Structure

- `.claude-plugin/` — Plugin metadata and MCP server config
- `.codex-plugin/` and `.mcp.json` — Codex plugin metadata and MCP config
- `servers/` — MCP server, exact bootstrap dependency pins, and development `.venv`
- `scripts/` — Hook scripts and utilities (stdlib only, no venv)
- `scripts/tests/` — Unit tests (stdlib, run individually or via `run_tests.py`)
- `hooks/hooks.json` — Hook configuration
- `skills/` — Skill definitions
- `agents/` — Agent definitions (currently empty)
- `commands/` — Workflow commands (currently empty)

### Versioning

The plugin version lives in **three** files that must be kept in sync:

- `.codex-plugin/plugin.json` → `version`
- `.claude-plugin/plugin.json` → `version`
- `.claude-plugin/marketplace.json` → `plugins[].version`

When bumping the version, update all three and commit together.
