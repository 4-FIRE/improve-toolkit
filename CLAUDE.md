# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## MCP Servers

One MCP server is configured in `.claude-plugin/plugin.json`:

1. **4-fire** (local): Python MCP server exposing memory, skill_manage, session_search, session_history tools

## Persona Injection

The assistant persona (direct, technically precise assistant; memory/skill/code conventions; sub-agent guidelines) is **not** defined as an agent file. It is injected as session-start context by `scripts/session_context.py` via the `SessionStart` hook's `additionalContext` field. Edit the `PERSONA_PROMPT` constant there to change it.

## Hooks

Session lifecycle hooks in `hooks/hooks.json`:
- SessionStart: load memory, inject persona/workflow reminder, session-start logging
- SessionEnd: cleanup
- UserPromptSubmit / Stop: logging hooks

## Plugin Structure

- `.claude-plugin/` - Plugin metadata and MCP server config
- `agents/` - Agent definitions (currently empty; persona lives in `scripts/session_context.py`)
- `commands/` - Workflow commands (currently empty)
- `servers/` - Local MCP server implementation
- `scripts/` - Hook scripts and utilities (incl. `session_context.py` persona injection)
- `hooks/hooks.json` - Hook configuration
- `skills/` - Skill definitions
