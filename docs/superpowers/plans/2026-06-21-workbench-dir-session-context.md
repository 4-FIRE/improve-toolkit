# Workbench Dir for `session_context.py` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `/tmp` paths in the `session_context.py` persona prompt with a project-scoped, cross-platform `workbench/` directory, so the injected "Solving with code" guidance works on Windows as well as macOS/Linux.

**Architecture:** Add a `get_workbench_dir()` helper modeled on `load_memory.py`'s `get_home()` (resolve via `$CLAUDE_PROJECT_DIR/.claude/workbench`). Create the dir at session start (idempotent `mkdir`). Interpolate the resolved absolute path into the persona text by replacing a `__WORKBENCH_DIR__` placeholder (avoiding f-string conversion of the large prompt literal). Add a `.gitignore` entry so throwaway files stay out of version control.

**Tech Stack:** Python 3 stdlib only (pathlib, os, json) — matches the existing hook convention. Tests are standalone stdlib scripts run via `python` (no pytest), matching `servers/test_tools.py`.

## Global Constraints

- Standard library only — no third-party imports in hook scripts or their tests.
- Path resolution must use `CLAUDE_PROJECT_DIR` env var with `.` fallback, exactly like `scripts/load_memory.py:24` (`Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".claude"`), extended one level to `workbench/`.
- `stdout` must remain forced to UTF-8 (existing `sys.stdout.reconfigure(encoding="utf-8")` stays) so non-ASCII prompt content prints on Windows.
- Tests run with `python scripts/test_session_context.py` (plain interpreter, no pytest), following `servers/test_tools.py` convention.
- Keep `PERSONA_PROMPT` as a plain triple-quoted literal — do **not** convert it to an f-string (it contains `{}`-bearing markdown). Use placeholder substitution.
- No change to `load_memory.py`, `hooks.json`, the `python -c` inline guidance, or other hooks.

---

## File Structure

- **Modify:** `scripts/session_context.py` — add `get_workbench_dir()`, create the dir, replace three `/tmp` references with a `__WORKBENCH_DIR__` placeholder, and substitute the resolved path into the prompt before emitting JSON.
- **Create:** `scripts/test_session_context.py` — standalone stdlib test that runs the hook as a subprocess against a temp `CLAUDE_PROJECT_DIR` and asserts (a) the resolved workbench path appears in the injected context, (b) the dir was created, (c) the three old `/tmp` references are gone.
- **Modify:** `.gitignore` — add `.claude/workbench/` to the existing `.claude/` ignore block.

---

### Task 1: Add `get_workbench_dir()` helper and create the dir at session start

**Files:**
- Modify: `scripts/session_context.py` (top imports + after the `beijing_time` line)
- Test: `scripts/test_session_context.py`

**Interfaces:**
- Consumes: `CLAUDE_PROJECT_DIR` env var (string path or unset → `.` fallback), same convention as `load_memory.py`.
- Produces: `get_workbench_dir() -> Path` returning `$CLAUDE_PROJECT_DIR/.claude/workbench`. Side effect: the directory is created (parents=True, exist_ok=True) during hook execution.

- [ ] **Step 1: Write the failing test**

Create `scripts/test_session_context.py`:

```python
#!/usr/bin/env python3
"""
Standalone tests for scripts/session_context.py — run with:
    python scripts/test_session_context.py

Stdlib only, no pytest. Runs the hook as a subprocess against a temp
CLAUDE_PROJECT_DIR (mirrors servers/test_tools.py's subprocess style).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "session_context.py"


def run_hook(workdir: Path) -> dict:
    """Run session_context.py with CLAUDE_PROJECT_DIR=workdir, return parsed JSON."""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(workdir)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_workbench_dir_created_and_path_in_context():
    workdir = Path(tempfile.mkdtemp(prefix="sc_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        expected = str((workdir / ".claude" / "workbench").resolve())
        assert expected in context, f"workbench path missing from context; expected {expected!r}"
        assert (workdir / ".claude" / "workbench").is_dir(), "workbench dir was not created"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    test_workbench_dir_created_and_path_in_context()
    print("test_workbench_dir_created_and_path_in_context: PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python scripts/test_session_context.py`
Expected: FAIL — either `KeyError: 'hookSpecificOutput'` is fine to ignore, but the assertion fails because the workbench path is not yet in the context and the dir is not created. The error message will be `AssertionError: workbench dir was not created` (or the path-missing assertion). A clean PASS here means something is wrong.

- [ ] **Step 3: Add the `get_workbench_dir()` helper and dir creation**

In `scripts/session_context.py`, add `os` and `Path` to the imports. The current top of the file is:

```python
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
```

Change to:

```python
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
```

Then, immediately after the `beijing_time = now.strftime(...)` line (and before `PERSONA_PROMPT = """`), add the helper and the dir-creation call:

```python
def get_workbench_dir() -> Path:
    """Return the project-scoped dir for throwaway code-execution files.

    Mirrors load_memory.py's get_home(): resolve via CLAUDE_PROJECT_DIR
    (with '.' fallback so the hook works even when the env var is unset),
    then .claude/workbench. Created at session start so the path is
    writable even if the assistant writes via shell redirection.
    """
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".claude" / "workbench"


get_workbench_dir().mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run test to verify it still fails on the path-in-context assertion**

Run: `python scripts/test_session_context.py`
Expected: still FAIL, but now on the `expected in context` assertion (the dir is created, but the path is not yet referenced in the persona text). The `is_dir()` assertion now passes. This confirms the helper works; the path-injection comes in Task 2.

- [ ] **Step 5: Commit**

```bash
git add scripts/session_context.py scripts/test_session_context.py
git commit -m "feat(hooks): add project-scoped workbench dir helper to session_context"
```

---

### Task 2: Replace `/tmp` references with the `__WORKBENCH_DIR__` placeholder and substitute the resolved path

**Files:**
- Modify: `scripts/session_context.py` (the three `/tmp` references inside `PERSONA_PROMPT`, and the `MESSAGE` assembly)
- Test: `scripts/test_session_context.py` (add two tests)

**Interfaces:**
- Consumes: `get_workbench_dir()` from Task 1.
- Produces: the final hook JSON whose `additionalContext` contains the resolved workbench path (e.g. `/abs/project/.claude/workbench`) in place of every former `/tmp` reference, and contains none of the old literal `/tmp` references.

- [ ] **Step 1: Write the failing tests**

Append these two tests to `scripts/test_session_context.py` (above the `if __name__ == "__main__":` block):

```python
def test_no_legacy_tmp_references():
    workdir = Path(tempfile.mkdtemp(prefix="sc_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        # The three former /tmp references must be gone.
        for legacy in ("/tmp/<task>.py", "JSON files in /tmp", "python /tmp/"):
            assert legacy not in context, f"legacy /tmp reference still present: {legacy!r}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_workbench_path_appears_in_run_guidance():
    workdir = Path(tempfile.mkdtemp(prefix="sc_test_"))
    try:
        data = run_hook(workdir)
        context = data["hookSpecificOutput"]["additionalContext"]
        expected = str((workdir / ".claude" / "workbench").resolve())
        # The "How to run" guidance should reference the workbench path for
        # both writing the file and executing it.
        assert context.count(expected) >= 2, (
            "workbench path should appear at least twice (write + run); "
            f"got {context.count(expected)} occurrence(s)"
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
```

Update the `__main__` block to call all three tests:

```python
if __name__ == "__main__":
    test_workbench_dir_created_and_path_in_context()
    print("test_workbench_dir_created_and_path_in_context: PASS")
    test_no_legacy_tmp_references()
    print("test_no_legacy_tmp_references: PASS")
    test_workbench_path_appears_in_run_guidance()
    print("test_workbench_path_appears_in_run_guidance: PASS")
```

- [ ] **Step 2: Run tests to verify the two new ones fail**

Run: `python scripts/test_session_context.py`
Expected: the first test (Task 1) PASSes; the two new tests FAIL — `test_workbench_path_appears_in_run_guidance` fails on the `count >= 2` assertion (path not yet injected), and `test_no_legacy_tmp_references` fails because `/tmp/<task>.py` etc. are still present.

- [ ] **Step 3: Replace the three `/tmp` references in `PERSONA_PROMPT` with the placeholder**

Find this line inside `PERSONA_PROMPT` (under "### How to run"):

```
- **Anything else**: `Write` to `/tmp/<task>.py`, then `python /tmp/<task>.py`.
```

Replace with:

```
- **Anything else**: `Write` to `__WORKBENCH_DIR__/<task>.py`, then `python __WORKBENCH_DIR__/<task>.py`.
```

Find this line under "### Process isolation":

```
- **JSON files in /tmp** for structured or nested data (more reliable than parsing stdout).
```

Replace with:

```
- **JSON files in __WORKBENCH_DIR__/** for structured or nested data (more reliable than parsing stdout).
```

Find this line under "### Process isolation":

```
- Prefer overwriting the same temp file for the same task rather than creating new files.
```

Replace with:

```
- Prefer overwriting the same workbench file for the same task rather than creating new files.
```

- [ ] **Step 4: Substitute the resolved path into the prompt before emitting JSON**

The current end of the file is:

```python
MESSAGE = f"{PERSONA_PROMPT}\n\n" f"🕐 北京时间: {beijing_time}\n\n"

output = {
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": MESSAGE,
    }
}
print(json.dumps(output, ensure_ascii=False))
```

Replace with:

```python
# Interpolate the concrete, resolved workbench path into the persona text.
# Placeholder substitution (not an f-string) because PERSONA_PROMPT contains
# markdown with braces that would otherwise need escaping.
_prompt = PERSONA_PROMPT.replace("__WORKBENCH_DIR__", str(get_workbench_dir().resolve()))

MESSAGE = f"{_prompt}\n\n" f"🕐 北京时间: {beijing_time}\n\n"

output = {
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": MESSAGE,
    }
}
print(json.dumps(output, ensure_ascii=False))
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `python scripts/test_session_context.py`
Expected: all three tests PASS, printing three `PASS` lines.

- [ ] **Step 6: Manually verify the hook output looks right**

Run: `CLAUDE_PROJECT_DIR="$PWD" python scripts/session_context.py | python -m json.tool`
Expected: valid JSON; the `additionalContext` contains the resolved path `$PWD/.claude/workbench` in the "How to run" and "Process isolation" sections, and contains no `/tmp/<task>` reference. Confirm the `🕐 北京时间:` line is present and intact.

- [ ] **Step 7: Commit**

```bash
git add scripts/session_context.py scripts/test_session_context.py
git commit -m "feat(hooks): inject cross-platform workbench path into persona prompt"
```

---

### Task 3: Ignore `.claude/workbench/` in version control

**Files:**
- Modify: `.gitignore` (the existing `.claude/` ignore block near the end of the file)

**Interfaces:**
- Consumes: none.
- Produces: throwaway code-execution files written to `.claude/workbench/` are excluded from git.

- [ ] **Step 1: Add the ignore entry**

The end of `.gitignore` currently has:

```
.claude/sessions/
.claude/logs/
.claude/skills/
```

Add `.claude/workbench/` so it reads:

```
.claude/sessions/
.claude/logs/
.claude/skills/
.claude/workbench/
```

- [ ] **Step 2: Verify it is ignored**

Run: `git check-ignore -v .claude/workbench/throwaway.py`
Expected: prints a line showing `.gitignore:N:.claude/workbench/` matched (exit code 0). No output / exit code 1 means the rule did not match — fix before committing.

- [ ] **Step 3: Confirm no tracked files would be affected**

Run: `git status --porcelain`
Expected: clean working tree (the only changes so far are already committed in Tasks 1–2; the `.gitignore` edit itself shows as modified). Specifically, no `.claude/workbench/` files appear as tracked or staged.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore .claude/workbench throwaway code dir"
```

---

## Self-Review

**1. Spec coverage:**
- Path resolution helper mirroring `load_memory.py` → Task 1, Step 3. ✓
- Resolve to absolute path at injection time → Task 2, Step 4 (`str(get_workbench_dir().resolve())`). ✓
- Placeholder substitution (not f-string) → Task 2, Steps 3–4. ✓
- Three `/tmp` references rewritten → Task 2, Step 3 (all three enumerated). ✓
- `mkdir` at session start → Task 1, Step 3. ✓
- `.gitignore` entry → Task 3. ✓
- Path-separator note → no code change per spec; covered by the cross-platform assertion in tests (resolved path appears regardless of separator). ✓
- No change to `load_memory.py`, `hooks.json`, `python -c` guidance, or other hooks → respected; only `session_context.py`, the new test, and `.gitignore` are touched. ✓

**2. Placeholder scan:** No TBD/TODO/"add appropriate" language. Every code step shows the exact code. ✓

**3. Type consistency:** `get_workbench_dir() -> Path` defined in Task 1, used in Task 1 (Step 3, `mkdir`) and Task 2 (Step 4, `.resolve()`). Signature consistent across both. ✓ The placeholder token `__WORKBENCH_DIR__` is identical in Task 2 Steps 3 and 4. ✓
