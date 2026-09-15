# Repository Guidelines

## Project Structure & Module Organization

Improve Toolkit is one plugin shared by Codex and Claude Code. Host metadata
lives in `.codex-plugin/`, `.claude-plugin/`, `.mcp.json`, and
`codex-marketplace/`. Keep shared behavior host-neutral:

- `skills/` contains the bundled `SKILL.md` workflows.
- `hooks/hooks.json` registers the shared `SessionStart` hooks.
- `scripts/` contains standard-library-only hook, path, migration, locking, and
  virtual-environment utilities. Unit tests live in `scripts/tests/`.
- `servers/` contains the stdio MCP server, the `memory` tool, integration
  tests, launchers, and exact dependency pins.

Runtime data belongs to the consuming project under
`.improve-toolkit/{memories,logs,workbench}`. By default the plugin writes a
nested `.gitignore` that ignores the entire runtime directory — including its
own `.gitignore` file — so `.improve-toolkit/` is invisible to git and memory is
local-only, not synced. The ignore file is recreated at every SessionStart.
Projects can opt back into version-controlled memory with
`IMPROVE_TRACK_MEMORIES=1`.

## Build, Test, and Development Commands

```bash
python scripts/run_tests.py
python servers/test_tools.py
servers/.venv/bin/python servers/test_mcp_protocol.py
python /path/to/plugin-creator/scripts/validate_plugin.py .
```

Choose checks for the changed surface: the first command covers shared scripts
and hooks; `test_tools.py` covers MCP memory behavior and creates `servers/.venv`
when needed; the protocol test covers launcher, tool discovery and stdio calls;
the final command checks Codex plugin metadata. Skill prose changes need format
and reference checks, plus a representative trial when behavior changes matter.

Run one unit file directly while iterating, for example
`python scripts/tests/test_runtime_paths.py`.

## Coding Style & Naming Conventions

Target Python 3.10+, use four-space indentation, `snake_case` functions,
`PascalCase` classes, type hints for new public helpers, and `pathlib.Path` for
filesystem work. Keep `scripts/` free of third-party imports; MCP-only
dependencies belong in `servers/requirements.lock` and `servers/pyproject.toml`
with identical exact pins. Maintain POSIX launchers and their `.cmd`
counterparts together. Preserve each JSON file's existing formatting.

## Testing Guidelines

Tests use plain functions named `test_*` with built-in `assert`; no pytest
runner is required. Add behavioral coverage beside related script tests and MCP
integration cases to `servers/test_tools.py`; prose-only edits do not need tests
that assert exact wording. Use temporary directories and patched environments
so tests never mutate real project memory. Run relevant checks and fix failures
caused by the change within the existing task authorization. Once checks pass,
repeat or broaden them only for new changes, failures or unresolved concerns.

## Commit & Pull Request Guidelines

History follows concise Conventional Commit prefixes such as `feat:`, `fix:`,
`refactor:`, `chore:`, and `style:`. Keep commits focused and imperative. Pull
requests should explain behavior changes for both hosts, list commands run,
link relevant issues, and call out migration or compatibility risks.
Screenshots are only useful for visible host UI changes.

## Configuration & Release Notes

Document new `IMPROVE_*` overrides and avoid committing logs, caches, virtual
environments, or secrets. Release version bumps must stay synchronized across
`.codex-plugin/plugin.json` and `.claude-plugin/plugin.json`. `CLAUDE.md` links here; edit this file as the
single contributor-guide source.
