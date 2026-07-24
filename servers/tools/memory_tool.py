#!/usr/bin/env python3
"""
Memory Tool Module - Persistent Curated Memory

Provides bounded, file-backed memory that persists across sessions. Two stores:
  - MEMORY.md: agent's personal notes and observations (environment facts, project
    conventions, tool quirks, things learned)
  - USER.md: what the agent knows about the user (preferences, communication style,
    expectations, workflow habits)

Both are injected into the system prompt as a frozen snapshot at session start.
Mid-session writes update files on disk immediately (durable) but do NOT change
the system prompt -- this preserves the prefix cache for the entire session.
The snapshot refreshes on the next session start.

Entry delimiter: § (section sign). Entries can be multiline.
Character limits (not tokens) because char counts are model-independent.

Design:
- Single `memory` tool with action parameter: add, replace, remove
- replace/remove use short unique substring matching (not full text or IDs)
- Behavioral guidance lives in the tool schema description
- Frozen snapshot pattern: system prompt is stable, tool responses show live state
"""

import json
import logging
import os
import re
import time
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from file_ops import atomic_write_text, file_lock
from memory_format import (
    char_count as memory_char_count,
    deduplicate_entries,
    join_entries,
    render_block,
    split_entries,
)

from .utils import tool_error, get_home

logger = logging.getLogger(__name__)
_ACTIVE_DATA_HOME: ContextVar[Optional[Path]] = ContextVar(
    "improve_memory_data_home",
    default=None,
)


# ---------------------------------------------------------------------------
# Diagnostic logging + change audit
#
# The MCP server speaks JSON-RPC over stdio, so we cannot log to stdout.
# Everything goes to the active project's shared runtime log directory.
#
# Two sinks:
#   - memory_tool.log       : operational trace (lock waits, reloads, writes)
#   - memory_changes.jsonl  : one line per mutation attempt (the audit trail)
#
# Setup is best-effort: if the log dir is not writable we silently degrade --
# logging must never break the memory tool itself.
# ---------------------------------------------------------------------------

# How long _file_lock waits before giving up. The old code used blocking
# flock() which would hang forever if a peer process died holding the lock or
# if the OS lock got wedged -- this is the most likely cause of the
# "add/replace 卡住" reports. A bounded timeout turns a permanent hang into a
# logged, recoverable error.
LOCK_TIMEOUT_SECONDS = 15.0
LOCK_POLL_INTERVAL = 0.1


def _log_dir() -> Path:
    data_home = _ACTIVE_DATA_HOME.get()
    return (data_home if data_home is not None else get_home()) / "logs"


def _ensure_logger() -> None:
    """Attach a file handler to the module logger (idempotent)."""
    log_dir = _log_dir().resolve()
    configured_dirs = getattr(logger, "_fire_configured_dirs", set())
    if log_dir in configured_dirs:
        return
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "memory_tool.log", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] [pid=%(process)d] %(message)s")
        )
        handler.addFilter(
            lambda _record, expected=log_dir: _log_dir().resolve() == expected
        )
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        configured_dirs.add(log_dir)
        logger._fire_configured_dirs = configured_dirs  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 -- never break the tool over logging
        # No handler, so this goes to the root logger's lastResort handler
        # (stderr). Better than crashing.
        pass


def _preview(text: Optional[str], limit: int = 120) -> str:
    """Compact, single-line preview for log/audit records."""
    if text is None:
        return ""
    compact = " ".join(str(text).split())
    if len(compact) > limit:
        compact = compact[:limit] + "…"
    return compact


def _append_audit(record: Dict[str, Any]) -> None:
    """Append one JSON line to the memory change audit log (best-effort)."""
    try:
        _log_dir().mkdir(parents=True, exist_ok=True)
        record.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
        record.setdefault("pid", os.getpid())
        with open(_log_dir() / "memory_changes.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit log write failed: %s", exc)


# Backward-compatible helper for callers that supply a complete runtime data
# home. Production wiring passes the shared cross-host memory_dir explicitly.
def get_memory_dir(data_home: Optional[Path] = None) -> Path:
    """Return the memories child of a runtime data directory."""
    return (data_home if data_home is not None else get_home()) / "memories"

# ---------------------------------------------------------------------------
# Memory content scanning — lightweight check for injection/exfiltration
# in content that gets injected into the system prompt.
# ---------------------------------------------------------------------------

_MEMORY_THREAT_PATTERNS = [
    # Prompt injection
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'you\s+are\s+now\s+', "role_hijack"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'disregard\s+(your|all|any)\s+(instructions|rules|guidelines)', "disregard_rules"),
    (r'act\s+as\s+(if|though)\s+you\s+(have\s+no|don\'t\s+have)\s+(restrictions|limits|rules)', "bypass_restrictions"),
    # Exfiltration via curl/wget with secrets
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_curl"),
    (r'wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_wget"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)', "read_secrets"),
    # Persistence via shell rc
    (r'authorized_keys', "ssh_backdoor"),
    (r'\$HOME/\.ssh|\~/\.ssh', "ssh_access"),
]

# Subset of invisible chars for injection detection
_INVISIBLE_CHARS = {
    '​', '‌', '‍', '⁠', '﻿',
    '‪', '‫', '‬', '‭', '‮',
}


def _scan_memory_content(content: str) -> Optional[str]:
    """Scan memory content for injection/exfil patterns. Returns error string if blocked."""
    # Check invisible unicode
    for char in _INVISIBLE_CHARS:
        if char in content:
            return f"Blocked: content contains invisible unicode character U+{ord(char):04X} (possible injection)."

    # Check threat patterns
    for pattern, pid in _MEMORY_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return f"Blocked: content matches threat pattern '{pid}'. Memory entries are injected into the system prompt and must not contain injection or exfiltration payloads."

    return None


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace for fuzzy matching."""
    return ' '.join(text.split())


def _fuzzy_match_entries(entries: List[str], search_text: str) -> List[Tuple[int, str]]:
    """Find entries matching search_text using fuzzy matching.

    Returns list of (index, entry) tuples.
    """
    search_text = search_text.strip()
    matches = []

    # Strategy 1: Exact match
    for i, entry in enumerate(entries):
        if search_text in entry:
            matches.append((i, entry))

    if matches:
        return matches

    # Strategy 2: Whitespace normalized match
    search_normalized = _normalize_whitespace(search_text)
    for i, entry in enumerate(entries):
        entry_normalized = _normalize_whitespace(entry)
        if search_normalized in entry_normalized:
            matches.append((i, entry))

    return matches


class MemoryStore:
    """
    Bounded curated memory with file persistence. One instance per AIAgent.

    Maintains two parallel states:
      - _system_prompt_snapshot: frozen at load time, used for system prompt injection.
        Never mutated mid-session. Keeps prefix cache stable.
      - memory_entries / user_entries: live state, mutated by tool calls, persisted to disk.
        Tool responses always reflect this live state.
    """

    def __init__(
        self,
        memory_char_limit: int = 2200,
        user_char_limit: int = 1375,
        data_home: Optional[Path] = None,
        memory_dir: Optional[Path] = None,
    ):
        self.memory_entries: List[str] = []
        self.user_entries: List[str] = []
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        self.data_home = Path(data_home) if data_home is not None else get_home()
        self.memory_dir = (
            Path(memory_dir)
            if memory_dir is not None
            else get_memory_dir(self.data_home)
        )
        # Frozen snapshot for system prompt -- set once at load_from_disk()
        self._system_prompt_snapshot: Dict[str, str] = {"memory": "", "user": ""}

    def load_from_disk(self):
        """Load entries from MEMORY.md and USER.md, capture system prompt snapshot."""
        mem_dir = self.memory_dir
        mem_dir.mkdir(parents=True, exist_ok=True)

        self.memory_entries = self._read_file(mem_dir / "MEMORY.md")
        self.user_entries = self._read_file(mem_dir / "USER.md")

        # Deduplicate entries (preserves order, keeps first occurrence)
        self.memory_entries = deduplicate_entries(self.memory_entries)
        self.user_entries = deduplicate_entries(self.user_entries)

        # Capture frozen snapshot for system prompt injection
        self._system_prompt_snapshot = {
            "memory": render_block(
                "memory",
                self.memory_entries,
                limit=self.memory_char_limit,
            ),
            "user": render_block(
                "user",
                self.user_entries,
                limit=self.user_char_limit,
            ),
        }

    @staticmethod
    def _file_lock(path: Path):
        """Return the shared sibling-lock context for a memory mutation."""
        _ensure_logger()
        lock_path = path.with_suffix(path.suffix + ".lock")
        return file_lock(
            lock_path,
            timeout=LOCK_TIMEOUT_SECONDS,
            poll_interval=LOCK_POLL_INTERVAL,
            logger=logger,
            description=f"memory lock {lock_path}",
        )

    def _path_for(self, target: str) -> Path:
        if target == "user":
            return self.memory_dir / "USER.md"
        return self.memory_dir / "MEMORY.md"

    def _reload_target(self, target: str):
        """Re-read entries from disk into in-memory state.

        Called under file lock to get the latest state before mutating.
        """
        fresh = self._read_file(self._path_for(target))
        fresh = deduplicate_entries(fresh)
        self._set_entries(target, fresh)

    def save_to_disk(self, target: str):
        """Persist entries to the appropriate file. Called after every mutation."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._write_file(self._path_for(target), self._entries_for(target))

    def _entries_for(self, target: str) -> List[str]:
        if target == "user":
            return self.user_entries
        return self.memory_entries

    def _set_entries(self, target: str, entries: List[str]):
        if target == "user":
            self.user_entries = entries
        else:
            self.memory_entries = entries

    def _char_count(self, target: str) -> int:
        return memory_char_count(self._entries_for(target))

    def _char_limit(self, target: str) -> int:
        if target == "user":
            return self.user_char_limit
        return self.memory_char_limit

    def add(self, target: str, content: str) -> Dict[str, Any]:
        """Append a new entry. Returns error if it would exceed the char limit."""
        _ensure_logger()
        logger.info("add: target=%s content_len=%d preview=%r", target, len(content or ""), _preview(content))
        content = content.strip()
        if not content:
            logger.info("add: rejected empty content (target=%s)", target)
            _append_audit({"action": "add", "target": target, "result": "empty"})
            return {"success": False, "error": "Content cannot be empty."}

        # Scan for injection/exfiltration before accepting
        scan_error = _scan_memory_content(content)
        if scan_error:
            logger.warning("add: blocked by scan (%s) target=%s preview=%r", scan_error, target, _preview(content))
            _append_audit({"action": "add", "target": target, "result": "blocked", "error": scan_error})
            return {"success": False, "error": scan_error}

        try:
            with self._file_lock(self._path_for(target)):
                logger.debug("add: lock held, reloading target=%s", target)
                # Re-read from disk under lock to pick up writes from other sessions
                self._reload_target(target)

                entries = self._entries_for(target)
                limit = self._char_limit(target)
                logger.debug("add: target=%s current_entries=%d chars=%d/%d",
                             target, len(entries), self._char_count(target), limit)

                # Reject exact duplicates
                if content in entries:
                    logger.info("add: duplicate, no-op (target=%s)", target)
                    _append_audit({"action": "add", "target": target, "result": "duplicate"})
                    return self._success_response(target, "Entry already exists (no duplicate added).")

                # Calculate what the new total would be
                new_entries = entries + [content]
                new_total = memory_char_count(new_entries)

                if new_total > limit:
                    current = self._char_count(target)
                    logger.info("add: over limit (target=%s %d/%d + %d)",
                                target, current, limit, len(content))
                    _append_audit({
                        "action": "add", "target": target, "result": "over_limit",
                        "chars_before": current, "limit": limit, "added_chars": len(content),
                    })
                    return {
                        "success": False,
                        "error": (
                            f"Memory at {current:,}/{limit:,} chars. "
                            f"Adding this entry ({len(content)} chars) would exceed the limit. "
                            f"Replace or remove existing entries first."
                        ),
                        "current_entries": entries,
                        "usage": f"{current:,}/{limit:,}",
                    }

                entries.append(content)
                self._set_entries(target, entries)
                logger.debug("add: persisting target=%s entries=%d", target, len(entries))
                self.save_to_disk(target)
        except TimeoutError as exc:
            logger.error("add: lock timeout (target=%s): %s", target, exc)
            _append_audit({"action": "add", "target": target, "result": "lock_timeout", "error": str(exc)})
            return {"success": False, "error": f"Memory write timed out: {exc}"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("add: unexpected error (target=%s)", target)
            _append_audit({"action": "add", "target": target, "result": "error", "error": str(exc)})
            return {"success": False, "error": f"Memory write failed: {exc}"}

        logger.info("add: OK target=%s entries=%d preview=%r",
                    target, len(self._entries_for(target)), _preview(content))
        _append_audit({
            "action": "add", "target": target, "result": "ok",
            "content_preview": _preview(content), "content_len": len(content),
        })
        return self._success_response(target, "Entry added.")

    def replace(self, target: str, old_text: str, new_content: str) -> Dict[str, Any]:
        """Find entry containing old_text substring, replace it with new_content."""
        _ensure_logger()
        logger.info("replace: target=%s old_text=%r new_len=%d preview=%r",
                    target, _preview(old_text), len(new_content or ""), _preview(new_content))
        old_text = old_text.strip()
        new_content = new_content.strip()
        if not old_text:
            logger.info("replace: rejected empty old_text (target=%s)", target)
            _append_audit({"action": "replace", "target": target, "result": "empty_old"})
            return {"success": False, "error": "old_text cannot be empty."}
        if not new_content:
            logger.info("replace: rejected empty new_content (target=%s)", target)
            _append_audit({"action": "replace", "target": target, "result": "empty_new"})
            return {"success": False, "error": "new_content cannot be empty. Use 'remove' to delete entries."}

        # Scan replacement content for injection/exfiltration
        scan_error = _scan_memory_content(new_content)
        if scan_error:
            logger.warning("replace: blocked by scan (%s) target=%s", scan_error, target)
            _append_audit({"action": "replace", "target": target, "result": "blocked", "error": scan_error})
            return {"success": False, "error": scan_error}

        try:
            with self._file_lock(self._path_for(target)):
                logger.debug("replace: lock held, reloading target=%s", target)
                self._reload_target(target)

                entries = self._entries_for(target)
                matches = _fuzzy_match_entries(entries, old_text)
                logger.debug("replace: target=%s entries=%d matches=%d",
                             target, len(entries), len(matches))

                if not matches:
                    logger.info("replace: no match (target=%s old_text=%r)", target, _preview(old_text))
                    _append_audit({
                        "action": "replace", "target": target, "result": "no_match",
                        "old_text": _preview(old_text),
                    })
                    return {"success": False, "error": f"No entry matched '{old_text}'."}

                if len(matches) > 1:
                    # If all matches are identical (exact duplicates), operate on the first one
                    unique_texts = set(e for _, e in matches)
                    if len(unique_texts) > 1:
                        previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                        logger.info("replace: ambiguous match (%d entries) target=%s", len(matches), target)
                        _append_audit({
                            "action": "replace", "target": target, "result": "ambiguous",
                            "match_count": len(matches),
                        })
                        return {
                            "success": False,
                            "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                            "matches": previews,
                        }
                    # All identical -- safe to replace just the first

                idx = matches[0][0]
                limit = self._char_limit(target)
                before_preview = _preview(entries[idx])

                # Check that replacement doesn't blow the budget
                test_entries = entries.copy()
                test_entries[idx] = new_content
                new_total = memory_char_count(test_entries)

                if new_total > limit:
                    logger.info("replace: over limit (target=%s %d/%d)", target, new_total, limit)
                    _append_audit({
                        "action": "replace", "target": target, "result": "over_limit",
                        "chars_after": new_total, "limit": limit,
                    })
                    return {
                        "success": False,
                        "error": (
                            f"Replacement would put memory at {new_total:,}/{limit:,} chars. "
                            f"Shorten the new content or remove other entries first."
                        ),
                    }

                entries[idx] = new_content
                self._set_entries(target, entries)
                logger.debug("replace: persisting target=%s idx=%d", target, idx)
                self.save_to_disk(target)
        except TimeoutError as exc:
            logger.error("replace: lock timeout (target=%s): %s", target, exc)
            _append_audit({"action": "replace", "target": target, "result": "lock_timeout", "error": str(exc)})
            return {"success": False, "error": f"Memory write timed out: {exc}"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("replace: unexpected error (target=%s)", target)
            _append_audit({"action": "replace", "target": target, "result": "error", "error": str(exc)})
            return {"success": False, "error": f"Memory write failed: {exc}"}

        logger.info("replace: OK target=%s idx=%d before=%r after=%r",
                    target, matches[0][0], before_preview, _preview(new_content))
        _append_audit({
            "action": "replace", "target": target, "result": "ok",
            "old_text": _preview(old_text),
            "before_preview": before_preview,
            "after_preview": _preview(new_content),
        })
        return self._success_response(target, "Entry replaced.")

    def remove(self, target: str, old_text: str) -> Dict[str, Any]:
        """Remove the entry containing old_text substring."""
        _ensure_logger()
        logger.info("remove: target=%s old_text=%r", target, _preview(old_text))
        old_text = old_text.strip()
        if not old_text:
            logger.info("remove: rejected empty old_text (target=%s)", target)
            _append_audit({"action": "remove", "target": target, "result": "empty_old"})
            return {"success": False, "error": "old_text cannot be empty."}

        try:
            with self._file_lock(self._path_for(target)):
                logger.debug("remove: lock held, reloading target=%s", target)
                self._reload_target(target)

                entries = self._entries_for(target)
                matches = _fuzzy_match_entries(entries, old_text)
                logger.debug("remove: target=%s entries=%d matches=%d",
                             target, len(entries), len(matches))

                if not matches:
                    logger.info("remove: no match (target=%s old_text=%r)", target, _preview(old_text))
                    _append_audit({
                        "action": "remove", "target": target, "result": "no_match",
                        "old_text": _preview(old_text),
                    })
                    return {"success": False, "error": f"No entry matched '{old_text}'."}

                if len(matches) > 1:
                    # If all matches are identical (exact duplicates), remove the first one
                    unique_texts = set(e for _, e in matches)
                    if len(unique_texts) > 1:
                        previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                        logger.info("remove: ambiguous match (%d entries) target=%s", len(matches), target)
                        _append_audit({
                            "action": "remove", "target": target, "result": "ambiguous",
                            "match_count": len(matches),
                        })
                        return {
                            "success": False,
                            "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                            "matches": previews,
                        }
                    # All identical -- safe to remove just the first

                idx = matches[0][0]
                removed_preview = _preview(entries[idx])
                entries.pop(idx)
                self._set_entries(target, entries)
                logger.debug("remove: persisting target=%s idx=%d", target, idx)
                self.save_to_disk(target)
        except TimeoutError as exc:
            logger.error("remove: lock timeout (target=%s): %s", target, exc)
            _append_audit({"action": "remove", "target": target, "result": "lock_timeout", "error": str(exc)})
            return {"success": False, "error": f"Memory write timed out: {exc}"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("remove: unexpected error (target=%s)", target)
            _append_audit({"action": "remove", "target": target, "result": "error", "error": str(exc)})
            return {"success": False, "error": f"Memory write failed: {exc}"}

        logger.info("remove: OK target=%s removed=%r", target, removed_preview)
        _append_audit({
            "action": "remove", "target": target, "result": "ok",
            "old_text": _preview(old_text), "removed_preview": removed_preview,
        })
        return self._success_response(target, "Entry removed.")

    def format_for_system_prompt(self, target: str) -> Optional[str]:
        """
        Return the frozen snapshot for system prompt injection.

        This returns the state captured at load_from_disk() time, NOT the live
        state. Mid-session writes do not affect this. This keeps the system
        prompt stable across all turns, preserving the prefix cache.

        Returns None if the snapshot is empty (no entries at load time).
        """
        block = self._system_prompt_snapshot.get(target, "")
        return block if block else None

    # -- Internal helpers --

    def _success_response(self, target: str, message: str = None) -> Dict[str, Any]:
        entries = self._entries_for(target)
        current = self._char_count(target)
        limit = self._char_limit(target)
        pct = min(100, int((current / limit) * 100)) if limit > 0 else 0

        resp = {
            "success": True,
            "target": target,
            "entries": entries,
            "usage": f"{pct}% — {current:,}/{limit:,} chars",
            "entry_count": len(entries),
        }
        if message:
            resp["message"] = message
        return resp

    @staticmethod
    def _read_file(path: Path) -> List[str]:
        """Read a memory file and split into entries.

        No file locking needed: _write_file uses atomic rename, so readers
        always see either the previous complete file or the new complete file.
        """
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, IOError):
            return []

        if not raw.strip():
            return []

        return split_entries(raw)

    @staticmethod
    def _write_file(path: Path, entries: List[str]):
        """Write entries to a memory file using atomic temp-file + rename.

        Previous implementation used open("w") + flock, but "w" truncates the
        file *before* the lock is acquired, creating a race window where
        concurrent readers see an empty file. Atomic rename avoids this:
        readers always see either the old complete file or the new one.
        """
        _ensure_logger()
        content = join_entries(entries)
        t0 = time.monotonic()
        try:
            logger.debug(
                "write: atomic target=%s entries=%d chars=%d",
                path,
                len(entries),
                len(content),
            )
            atomic_write_text(path, content, temp_prefix=".mem_")
            logger.debug(
                "write: atomic replace done target=%s (%.2fs total)",
                path,
                time.monotonic() - t0,
            )
        except (OSError, IOError) as e:
            logger.error("write: FAILED target=%s after %.2fs: %s",
                         path, time.monotonic() - t0, e)
            raise RuntimeError(f"Failed to write memory file {path}: {e}")


def memory_tool(
    action: str,
    target: str = "memory",
    content: str = None,
    old_text: str = None,
    store: Optional[MemoryStore] = None,
) -> str:
    """
    Single entry point for the memory tool. Dispatches to MemoryStore methods.

    Returns JSON string with results.
    """
    if store is None:
        return tool_error("Memory is not available. It may be disabled in config or this environment.", success=False)

    if target not in ("memory", "user"):
        return tool_error(f"Invalid target '{target}'. Use 'memory' or 'user'.", success=False)

    token = _ACTIVE_DATA_HOME.set(store.data_home)
    try:
        _ensure_logger()
        logger.info("dispatch: action=%s target=%s content_len=%s old_text_len=%s",
                    action, target,
                    len(content) if content else 0,
                    len(old_text) if old_text else 0)

        if action == "add":
            if not content:
                return tool_error("Content is required for 'add' action.", success=False)
            result = store.add(target, content)

        elif action == "replace":
            if not old_text:
                return tool_error("old_text is required for 'replace' action.", success=False)
            if not content:
                return tool_error("content is required for 'replace' action.", success=False)
            result = store.replace(target, old_text, content)

        elif action == "remove":
            if not old_text:
                return tool_error("old_text is required for 'remove' action.", success=False)
            result = store.remove(target, old_text)

        else:
            return tool_error(f"Unknown action '{action}'. Use: add, replace, remove", success=False)

        logger.info("dispatch: done action=%s target=%s success=%s",
                    action, target, result.get("success"))
        return json.dumps(result, ensure_ascii=False)
    finally:
        _ACTIVE_DATA_HOME.reset(token)


def check_memory_requirements() -> bool:
    """Memory tool has no external requirements -- always available."""
    return True


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

MEMORY_SCHEMA = {
    "name": "memory",
    "description": (
        "Save durable information to persistent memory that survives across sessions. "
        "Memory is shared by supported tools in the same project and injected into "
        "future turns, so keep it compact and focused on facts "
        "that will still matter later.\n\n"
        "WHEN TO SAVE (do this proactively, don't wait to be asked):\n"
        "- User corrects you or says 'remember this' / 'don't do that again'\n"
        "- User shares a preference, habit, or personal detail (name, role, timezone, coding style)\n"
        "- You discover something about the environment (OS, installed tools, project structure)\n"
        "- You learn a convention, API quirk, or workflow specific to this user's setup\n"
        "- You identify a stable fact that will be useful again in future sessions\n\n"
        "PRIORITY: User preferences and corrections > environment facts > procedural knowledge. "
        "The most valuable memory prevents the user from having to repeat themselves.\n\n"
        "Do NOT save task progress, session outcomes, completed-work logs, or temporary TODO "
        "state to memory.\n"
        "Do not store procedures or step-by-step workflows as memory. You may propose a "
        "skill for a validated, non-obvious, reusable workflow, but write it only after "
        "the user asks or accepts the concrete proposal. Then use writing-great-skills "
        "and the host's native file tools.\n\n"
        "TWO TARGETS:\n"
        "- 'user': who the user is -- name, role, preferences, communication style, pet peeves\n"
        "- 'memory': your notes -- environment facts, project conventions, tool quirks, lessons learned\n\n"
        "ACTIONS: add (new entry), replace (update existing -- old_text identifies it), "
        "remove (delete -- old_text identifies it).\n\n"
        "SKIP: trivial/obvious info, things easily re-discovered, raw data dumps, and temporary task state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove"],
                "description": "The action to perform."
            },
            "target": {
                "type": "string",
                "enum": ["memory", "user"],
                "description": "Which memory store: 'memory' for personal notes, 'user' for user profile."
            },
            "content": {
                "type": "string",
                "description": "The entry content. Required for 'add' and 'replace'."
            },
            "old_text": {
                "type": "string",
                "description": "Short unique substring identifying the entry to replace or remove."
            },
            "project_dir": {
                "type": "string",
                "description": (
                    "Absolute current workspace root. Required when the host is Codex "
                    "so memory stays project-scoped; Claude Code supplies its project "
                    "directory through the environment."
                )
            },
        },
        "required": ["action", "target"],
    },
}
