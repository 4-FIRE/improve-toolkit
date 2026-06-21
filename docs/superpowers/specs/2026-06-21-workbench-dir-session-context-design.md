# Cross-platform workbench dir for `session_context.py`

**Date:** 2026-06-21
**Topic:** Replace hardcoded `/tmp` paths in the persona prompt with a project-scoped, cross-platform directory.

## Problem

`scripts/session_context.py` injects a `PERSONA_PROMPT` that instructs the assistant to run throwaway code by writing to `/tmp/<task>.py`. `/tmp` is a POSIX-only convention; Windows has no such path, so the injected guidance is wrong (or non-functional) outside macOS/Linux.

The repo already solved an analogous problem in `scripts/load_memory.py`, which resolves the project home via `Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".claude"` instead of hardcoding an absolute path. `session_context.py` should adopt the same pattern.

## Affected references

All `/tmp` occurrences live **inside the `PERSONA_PROMPT` string** — they are instructions to the assistant, not code that `session_context.py` itself executes. Three references:

1. `Write to /tmp/<task>.py, then python /tmp/<task>.py` (under "How to run")
2. `JSON files in /tmp for structured or nested data` (under "Process isolation")
3. `Prefer overwriting the same temp file for the same task` (under "Process isolation")

## Design

### Location

A new project-scoped directory under the project's `.claude/`, named **`workbench/`** — chosen to echo the "Solving with code" section heading of the persona. Full path:

```
$CLAUDE_PROJECT_DIR/.claude/workbench/
```

This mirrors `load_memory.py`'s `get_home()` pattern (env var with `.` fallback, then `.claude`), extended one level to `workbench/`.

### Path resolution helper

Add to `session_context.py`:

```python
import os
from pathlib import Path

def get_workbench_dir() -> Path:
    """Return the project-scoped dir for throwaway code-execution files."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".claude" / "workbench"
```

Resolve to an absolute path at injection time so the assistant receives a concrete, writable path regardless of the hook's cwd:

```python
workbench = str(get_workbench_dir().resolve())
```

### Placeholder substitution

`PERSONA_PROMPT` is a large triple-quoted literal. Rather than convert it to an f-string (which would require escaping every `{}`), use a placeholder token replaced after the fact — matching how the existing code already interpolates `beijing_time` into `MESSAGE`:

```python
prompt = PERSONA_PROMPT.replace("__WORKBENCH_DIR__", workbench)
```

### Rewritten references

| Current | New |
|---|---|
| `Write to /tmp/<task>.py, then python /tmp/<task>.py` | `Write to __WORKBENCH_DIR__/<task>.py, then python __WORKBENCH_DIR__/<task>.py` |
| `JSON files in /tmp for structured or nested data` | `JSON files in __WORKBENCH_DIR__/ for structured or nested data` |
| `Prefer overwriting the same temp file for the same task` | `Prefer overwriting the same workbench file for the same task` |

The `python -c` inline-oneliner guidance (no `/tmp`) is unchanged.

### Directory creation (side effect at session start)

Create the dir in the hook so the path exists even if the assistant writes via shell redirection rather than the Write tool:

```python
get_workbench_dir().mkdir(parents=True, exist_ok=True)
```

Idempotent and cheap. `load_memory.py` does not do this because it only reads; we are introducing a write location, so we ensure it exists. Decision: include the `mkdir` (user-approved).

### `.gitignore` entry

Add `.claude/workbench/` to `.gitignore` alongside the existing `.claude/` ignores so throwaway files never enter version control.

### Path separator note

On Windows, `resolve()` yields backslash separators (e.g. `C:\…\project\.claude\workbench`). The template keeps a forward slash between the directory and `<task>.py`. Both `python` and the Write tool accept mixed separators on Windows, so this works cross-platform with no extra handling. Documented; no code change.

## Out of scope

- No change to `load_memory.py` or other hooks.
- No change to the `python -c` inline guidance.
- No migration of any existing files from `/tmp` to `workbench/`.
- No env-var override for the workbench location (decided against in favor of a single deterministic project-scoped path).
