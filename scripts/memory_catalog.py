#!/usr/bin/env python3
"""Shared, stdlib-only memory catalog for hooks and MCP adapters."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from file_ops import atomic_write_text, file_lock
from memory_format import (
    MEMORY_CHAR_LIMIT,
    USER_CHAR_LIMIT,
    char_count,
    join_entries,
    new_entry_id,
    parse_entries,
    render_entry,
    unix_timestamp,
)

from memory_upgrade import upgrade_memory_files


Target = Literal["memory", "user"]
SummaryStatus = Literal["current", "unavailable"]
RecallMode = Literal["relevant", "exact", "browse", "get"]

DEFAULT_SUMMARY_CHAR_LIMIT = 800
DEFAULT_RECALL_CHAR_LIMIT = 2400
DEFAULT_RECALL_LIMIT = 5
MIN_RECALL_CHAR_LIMIT = 512
MAX_RECALL_CHAR_LIMIT = 12000
MIN_CONTENT_CHUNK_CHARS = 256
ENTRY_SUMMARY_CHAR_LIMIT = 120
RECEIPT_CONTENT_CHAR_LIMIT = 1200
LOCK_TIMEOUT_SECONDS = 15.0
LOCK_POLL_INTERVAL = 0.1

_MEMORY_THREAT_PATTERNS = (
    (r"ignore\s+(previous|all|above|prior)\s+instructions", "prompt_injection"),
    (r"you\s+are\s+now\s+", "role_hijack"),
    (r"do\s+not\s+tell\s+the\s+user", "deception_hide"),
    (r"system\s+prompt\s+override", "sys_prompt_override"),
    (r"disregard\s+(your|all|any)\s+(instructions|rules|guidelines)", "disregard_rules"),
    (
        r"act\s+as\s+(if|though)\s+you\s+(have\s+no|don't\s+have)\s+"
        r"(restrictions|limits|rules)",
        "bypass_restrictions",
    ),
    (
        r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)",
        "exfil_curl",
    ),
    (
        r"wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)",
        "exfil_wget",
    ),
    (r"cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)", "read_secrets"),
    (
        r"(?:>{1,2}\s*|\btee\s+(?:-a\s+)?)[^\n;|]*authorized_keys",
        "ssh_backdoor",
    ),
    (
        r"\bcat\s+[^\n;|]*(?:\$HOME/\.ssh|~/\.ssh)/"
        r"id_(?:rsa|dsa|ecdsa|ed25519)\b(?!\.pub)",
        "ssh_access",
    ),
)
_INVISIBLE_CHARS = frozenset(
    "\u200b\u200c\u200d\u2060\ufeff\u202a\u202b\u202c\u202d\u202e"
)


class MemoryCatalogError(RuntimeError):
    """Report a catalog failure to hooks and tool adapters."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        committed: bool = False,
        required_max_chars: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.committed = committed
        self.required_max_chars = required_max_chars


@dataclass(frozen=True)
class MemoryChange:
    action: Literal["add", "replace", "remove"]
    target: Target
    content: str | None = None
    entry_id: str | None = None
    old_text: str | None = None
    startup: bool | None = None


@dataclass(frozen=True)
class SummarySnapshot:
    text: str
    status: SummaryStatus
    source_revision: str | None
    reason: str | None = None


@dataclass(frozen=True)
class ApplyResult:
    success: bool
    action: str
    target: Target
    entry_id: str | None
    revision: str
    usage_chars: int
    limit_chars: int
    message: str
    entry: MemoryEntry | None = None
    entry_count: int = 0


@dataclass(frozen=True)
class MemoryEntry:
    entry_id: str
    target: Target
    content: str
    summary: str
    startup: bool = True
    raw: str = field(default="", repr=False, compare=False)
    updated_at: int | None = None


@dataclass(frozen=True)
class RecallResult:
    success: bool
    entries: tuple[dict[str, object], ...]
    revision: str
    truncated: bool
    quarantined_count: int = 0
    next_offset: int | None = None
    next_content_offset: int | None = None

    @property
    def returned_chars(self) -> int:
        """Count the complete serialized response, including metadata and framing."""
        return len(self.to_json())

    def to_json(self) -> str:
        """Serialize once with a self-consistent character count."""
        payload = {
            "success": self.success,
            "entries": list(self.entries),
            "revision": self.revision,
            "returned_chars": 0,
            "truncated": self.truncated,
            "quarantined_count": self.quarantined_count,
            "next_offset": self.next_offset,
            "next_content_offset": self.next_content_offset,
        }
        while True:
            serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if payload["returned_chars"] == len(serialized):
                return serialized
            payload["returned_chars"] = len(serialized)


def memory_entry_payload(
    entry: MemoryEntry, *, summary_only: bool = False, content_limit: int | None = None,
) -> dict[str, object]:
    """Render a bounded view without rewriting legacy metadata on disk."""
    payload: dict[str, object] = {
        "entry_id": entry.entry_id,
        "target": entry.target,
        "summary": entry.summary[:ENTRY_SUMMARY_CHAR_LIMIT],
        "content_chars": len(entry.content),
    }
    if summary_only:
        payload["detail"] = "summary"
        return payload
    payload.update({
        "content": entry.content if content_limit is None else entry.content[:content_limit],
        "startup": entry.startup,
    })
    if entry.updated_at is not None:
        payload["updated_at"] = entry.updated_at
    if content_limit is not None and len(entry.content) > content_limit:
        payload["content_truncated"] = True
    return payload


def _entry_threat(entry: MemoryEntry) -> str | None:
    """Apply the same limited heuristic to every model-visible text field."""
    fields = (("content", entry.content),)
    for field, text in fields:
        threat = scan_memory_content(text)
        if threat:
            return f"{field} ({threat})"
    return None


def _quarantine_message(threat: str) -> str:
    """Name the field and repair path without echoing the quarantined text."""
    return f"The entry is quarantined: suspicious {threat}. Replace its content or remove the entry."



def _sha256_text(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _derived_entry_id(target: Target, content: str) -> str:
    digest = hashlib.sha256(f"{target}\0{content}".encode("utf-8")).hexdigest()[:12]
    return ("u:" if target == "user" else "m:") + digest


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _env_recall_char_limit() -> int:
    try:
        configured = _env_positive_int("IMPROVE_RECALL_CHAR_LIMIT", DEFAULT_RECALL_CHAR_LIMIT)
    except ValueError as exc:
        raise MemoryCatalogError("INVALID_CONFIGURATION", str(exc)) from exc
    return min(MAX_RECALL_CHAR_LIMIT, max(MIN_RECALL_CHAR_LIMIT, configured))


def scan_memory_content(content: str) -> str | None:
    """Flag known suspicious text patterns; this is not a semantic safety check."""
    for character in _INVISIBLE_CHARS:
        if character in content:
            return f"invisible_unicode_U+{ord(character):04X}"
    for pattern, threat_code in _MEMORY_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return threat_code
    return None


class MemoryCatalog:
    """Store durable memory and provide recall and the startup brief."""

    def __init__(
        self,
        *,
        memory_dir: Path,
        data_home: Path,
        memory_char_limit: int | None = None,
        user_char_limit: int | None = None,
        summary_char_limit: int | None = None,
        recall_char_limit: int | None = None,
    ) -> None:
        self.memory_dir = Path(memory_dir)
        self.data_home = Path(data_home)
        self.memory_char_limit = (
            memory_char_limit
            if memory_char_limit is not None
            else _env_positive_int("IMPROVE_MEMORY_CHAR_LIMIT", MEMORY_CHAR_LIMIT)
        )
        self.user_char_limit = (
            user_char_limit
            if user_char_limit is not None
            else _env_positive_int("IMPROVE_USER_CHAR_LIMIT", USER_CHAR_LIMIT)
        )
        self.summary_char_limit = (
            summary_char_limit
            if summary_char_limit is not None
            else _env_positive_int(
                "IMPROVE_STARTUP_SUMMARY_LIMIT",
                DEFAULT_SUMMARY_CHAR_LIMIT,
            )
        )
        self.recall_char_limit = (
            recall_char_limit
            if recall_char_limit is not None
            else _env_recall_char_limit()
        )

    def startup_snapshot(self) -> SummarySnapshot:
        """Read only the materialized summary and its small validation state."""
        summary_path = self.memory_dir / "SUMMARY.md"
        state_path = self.memory_dir / ".summary-state.json"
        dirty_path = self.memory_dir / ".summary.dirty"
        if dirty_path.exists():
            return SummarySnapshot("", "unavailable", None, "Summary rebuild is pending.")
        if not summary_path.is_file() or not state_path.is_file():
            return SummarySnapshot("", "unavailable", None, "Summary files are missing.")

        try:
            raw = summary_path.read_text(encoding="utf-8")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            fingerprint = self._source_fingerprint()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return SummarySnapshot("", "unavailable", None, f"Cannot validate summary: {exc}")

        if not isinstance(state, dict):
            return SummarySnapshot("", "unavailable", None, "Summary state must be a JSON object.")
        if state.get("format_version") != 4:
            return SummarySnapshot("", "unavailable", None, "Summary format changed.")
        if state.get("summary_sha256") != _sha256_text(raw):
            return SummarySnapshot("", "unavailable", None, "Summary content changed.")
        if state.get("source_fingerprint") != fingerprint:
            return SummarySnapshot("", "unavailable", None, "Memory files changed.")

        lines = raw.splitlines()
        if lines and lines[0].startswith("<!-- improve-summary:"):
            lines = lines[1:]
        text = "\n".join(lines).strip()
        if len(text) > self.summary_char_limit:
            return SummarySnapshot("", "unavailable", None, "Summary exceeds the startup limit.")
        if scan_memory_content(text):
            return SummarySnapshot("", "unavailable", None, "Summary failed content checks.")
        return SummarySnapshot(text, "current", state.get("source_revision"))

    def ensure_startup_snapshot(self) -> SummarySnapshot:
        """Use a valid summary, or rebuild it under the shared memory lock."""
        snapshot = self.startup_snapshot()
        if snapshot.status == "current":
            return snapshot

        lock_path = self.memory_dir / ".memory.lock"
        with file_lock(
            lock_path, timeout=LOCK_TIMEOUT_SECONDS, poll_interval=LOCK_POLL_INTERVAL,
            description=f"memory catalog lock {lock_path}",
        ):
            snapshot = self.startup_snapshot()
            if snapshot.status == "current":
                return snapshot
            logging.getLogger(__name__).warning("Rebuilding memory summary: %s", snapshot.reason)
            self._upgrade_legacy()
            fingerprint = self._source_fingerprint()
            records = self._reconcile_entries()
            revision = self._revision_for(records)
            if fingerprint != self._source_fingerprint():
                raise MemoryCatalogError(
                    "STORAGE_ERROR", "Memory files changed during summary rebuild.", retryable=True,
                )
            self._write_summary(revision, records, source_fingerprint=fingerprint)
            snapshot = self.startup_snapshot()
            if snapshot.status != "current":
                raise MemoryCatalogError(
                    "STORAGE_ERROR", f"Rebuilt summary is unavailable: {snapshot.reason}", retryable=True,
                )
            return snapshot

    def recall(
        self,
        *,
        query: str = "",
        target: Literal["all", "memory", "user"] = "all",
        mode: RecallMode = "relevant",
        limit: int = DEFAULT_RECALL_LIMIT,
        max_chars: int | None = None,
        entry_id: str | None = None,
        offset: int = 0,
        content_offset: int = 0,
        expected_revision: str | None = None,
    ) -> RecallResult:
        """Search, browse a complete index, or read one entry in bounded pages."""
        if target not in ("all", "memory", "user"):
            raise MemoryCatalogError("INVALID_REQUEST", f"Invalid target: {target}")
        if mode not in ("relevant", "exact", "browse", "get"):
            raise MemoryCatalogError("INVALID_REQUEST", f"Invalid recall mode: {mode}")
        if not isinstance(query, str) or (mode in ("relevant", "exact") and not query.strip()):
            raise MemoryCatalogError("INVALID_REQUEST", "query is required for keyword search.")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise MemoryCatalogError("INVALID_REQUEST", "limit must be between 1 and 20.")
        active_char_limit = self.recall_char_limit if max_chars is None else max_chars
        if (
            type(active_char_limit) is not int
            or not MIN_RECALL_CHAR_LIMIT <= active_char_limit <= MAX_RECALL_CHAR_LIMIT
        ):
            raise MemoryCatalogError(
                "INVALID_REQUEST",
                f"max_chars must be between {MIN_RECALL_CHAR_LIMIT} and {MAX_RECALL_CHAR_LIMIT}.",
            )
        if any(type(value) is not int or value < 0 for value in (offset, content_offset)):
            raise MemoryCatalogError("INVALID_REQUEST", "Offsets must be non-negative integers.")
        if mode == "get":
            if not isinstance(entry_id, str) or not entry_id:
                raise MemoryCatalogError("INVALID_REQUEST", "entry_id is required for mode=get.")
            if query or offset:
                raise MemoryCatalogError("INVALID_REQUEST", "mode=get does not accept query, filters or offset.")
        elif entry_id is not None or content_offset:
            raise MemoryCatalogError("INVALID_REQUEST", "entry_id and content_offset require mode=get.")
        if mode == "browse" and query:
            raise MemoryCatalogError("INVALID_REQUEST", "mode=browse lists summaries; omit query.")
        if (offset or content_offset) and not expected_revision:
            raise MemoryCatalogError(
                "INVALID_REQUEST", "Continuation requires expected_revision from the previous page.",
            )

        targets: tuple[Target, ...] = (
            ("user", "memory") if target == "all" else (target,)
        )
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.memory_dir / ".memory.lock"
        with file_lock(
            lock_path, timeout=LOCK_TIMEOUT_SECONDS, poll_interval=LOCK_POLL_INTERVAL,
            description=f"memory catalog lock {lock_path}",
        ):
            self._upgrade_legacy()
            fingerprint = self._source_fingerprint()
            records = self._reconcile_entries()
            revision = self._revision_for(records)
            if fingerprint != self._source_fingerprint():
                raise MemoryCatalogError("REVISION_CONFLICT", "Memory files changed during recall.", retryable=True)
            if expected_revision is not None and expected_revision != revision:
                raise MemoryCatalogError(
                    "REVISION_CONFLICT", "Memory changed; restart the lookup from its first page.",
                    retryable=True,
                )
            if self.startup_snapshot().status != "current":
                self._write_summary(revision, records, source_fingerprint=fingerprint)
                if self.startup_snapshot().status != "current":
                    raise MemoryCatalogError("STORAGE_ERROR", "Memory files changed during summary rebuild.", retryable=True)

        scoped = [entry for entry in records if entry.target in targets]
        quarantined_count = sum(bool(_entry_threat(entry)) for entry in scoped)
        if mode == "get":
            entry = next((entry for entry in scoped if entry.entry_id == entry_id), None)
            if entry is None:
                raise MemoryCatalogError("NOT_FOUND", "No entry matched entry_id in this target.")
            threat = _entry_threat(entry)
            if threat:
                raise MemoryCatalogError("UNSAFE_CONTENT", _quarantine_message(threat))
            return self._entry_page(
                entry, revision, content_offset, active_char_limit, quarantined_count,
            )

        query_terms = self._search_terms(query)
        ranked: list[tuple[int, int, MemoryEntry]] = []
        for order, entry in enumerate(scoped):
            if _entry_threat(entry):
                continue
            score = self._relevance_score(entry, query, query_terms, mode)
            if mode != "browse" and score <= 0:
                continue
            ranked.append((-score, order, entry))
        ranked.sort(key=lambda item: (item[0], item[1]))
        if offset > len(ranked):
            raise MemoryCatalogError("INVALID_REQUEST", "offset exceeds the matching entry count.")

        selected: list[dict[str, object]] = []
        position = offset

        def page(items: list[dict[str, object]], end: int) -> RecallResult:
            return RecallResult(
                success=True, entries=tuple(items), revision=revision,
                truncated=end < len(ranked),
                quarantined_count=quarantined_count,
                next_offset=end if end < len(ranked) else None,
            )

        for _, _, entry in ranked[offset:]:
            if len(selected) >= limit:
                break
            view = memory_entry_payload(entry, summary_only=mode == "browse")
            candidate = page([*selected, view], position + 1)
            if candidate.returned_chars > active_char_limit:
                if selected:
                    break
                if mode != "browse":
                    # Search always returns content; the first long hit is a useful
                    # prefix, with independent continuations for its body and ranking.
                    return self._entry_page(
                        entry, revision, 0, active_char_limit, quarantined_count,
                        next_offset=position + 1 if position + 1 < len(ranked) else None,
                    )
                raise MemoryCatalogError(
                    "BUDGET_TOO_SMALL",
                    f"Increase max_chars to at least {candidate.returned_chars} for this summary.",
                    required_max_chars=candidate.returned_chars,
                )
            selected.append(view)
            position += 1
        return page(selected, position)

    @staticmethod
    def _entry_page(
        entry: MemoryEntry, revision: str, offset: int, max_chars: int, quarantined_count: int,
        *, next_offset: int | None = None,
    ) -> RecallResult:
        """Read contiguous content chunks without dropping a long entry."""
        if offset > len(entry.content):
            raise MemoryCatalogError("INVALID_REQUEST", "content_offset exceeds entry length.")
        base = memory_entry_payload(entry)

        def page(end: int) -> RecallResult:
            partial = offset > 0 or end < len(entry.content)
            view = {
                **base, "content": entry.content[offset:end],
                "content_offset": offset, "content_truncated": partial,
            }
            return RecallResult(
                success=True, entries=(view,), revision=revision,
                truncated=partial or next_offset is not None, quarantined_count=quarantined_count,
                next_offset=next_offset,
                next_content_offset=end if end < len(entry.content) else None,
            )

        # Measure JSON escaping as well as text. Binary search finds a fitting
        # contiguous prefix; even control characters cannot exceed the budget.
        # The final page has different framing (null offset / false flag), so
        # test it separately before searching the monotonic partial-page range.
        complete = page(len(entry.content))
        if complete.returned_chars <= max_chars:
            return complete
        low = min(offset + MIN_CONTENT_CHUNK_CHARS, len(entry.content))
        high = len(entry.content) - 1
        minimum = page(low)
        if minimum.returned_chars > max_chars:
            raise MemoryCatalogError(
                "BUDGET_TOO_SMALL",
                f"Increase max_chars to at least {minimum.returned_chars} for this entry's "
                f"metadata and {low - offset} content characters.",
                required_max_chars=minimum.returned_chars,
            )
        while low < high:
            middle = (low + high + 1) // 2
            if page(middle).returned_chars <= max_chars:
                low = middle
            else:
                high = middle - 1
        return page(low)

    def apply(
        self,
        change: MemoryChange,
        *,
        expected_revision: str | None = None,
    ) -> ApplyResult:
        """Apply one durable change and atomically refresh derived projections."""
        self._validate_change(change)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.memory_dir / ".memory.lock"
        with file_lock(
            lock_path,
            timeout=LOCK_TIMEOUT_SECONDS,
            poll_interval=LOCK_POLL_INTERVAL,
            description=f"memory catalog lock {lock_path}",
        ):
            self._upgrade_legacy()
            fingerprint = self._source_fingerprint()
            records = self._reconcile_entries()
            current_revision = self._revision_for(records)
            if expected_revision is not None and expected_revision != current_revision:
                raise MemoryCatalogError(
                    "REVISION_CONFLICT",
                    "Memory changed after recall; recall again before retrying.",
                    retryable=True,
                )

            selected = self._select_entry(records, change)
            if change.action == "add":
                content = change.content.strip()
                selected = next((entry for entry in records
                                 if entry.target == change.target and entry.content == content), None)
                if selected is None:
                    selected = self._entry_from_change(change, content)
                    while any(entry.entry_id == selected.entry_id for entry in records):
                        selected = self._entry_from_change(change, content)
                    records.append(selected)
                    message = "Entry added."
                else:
                    message = "Entry already exists."
            elif change.action == "replace":
                if selected is None:
                    raise MemoryCatalogError("NOT_FOUND", "No entry matched the selector.")
                updated = replace(
                    selected, content=change.content.strip(),
                    summary=self._summary_cue(change.content.strip()),
                    startup=change.startup if change.startup is not None else selected.startup,
                    updated_at=unix_timestamp(),
                    raw="",
                )
                records[records.index(selected)] = updated
                selected = updated
                message = "Entry replaced."
            else:
                if selected is None:
                    raise MemoryCatalogError("NOT_FOUND", "No entry matched the selector.")
                records.remove(selected)
                message = "Entry removed."
            changed_id = selected.entry_id
            target_entries = [entry.content for entry in records if entry.target == change.target]
            if change.action != "remove" and message != "Entry already exists.":
                self._check_storage_limit(change.target, target_entries)
            summary_text = self._build_summary(records)
            if fingerprint != self._source_fingerprint():
                raise MemoryCatalogError("REVISION_CONFLICT", "Memory files changed during the write.", retryable=True)
            content_committed = False
            try:
                atomic_write_text(self.memory_dir / ".summary.dirty", current_revision, temp_prefix=".summary_dirty_")
                blocks = [
                    entry.raw if entry.raw and entry is not selected else render_entry(
                        entry.content, entry.entry_id, entry.startup, updated_at=entry.updated_at,
                    ) for entry in records if entry.target == change.target
                ]
                atomic_write_text(self._path_for(change.target), join_entries(blocks), temp_prefix=".mem_")
                content_committed = True
                persisted = self._source_fingerprint()
                other_name = "USER.md" if change.target == "memory" else "MEMORY.md"
                if persisted[other_name] != fingerprint[other_name] or self._read_source(change.target) != join_entries(blocks):
                    raise MemoryCatalogError("REVISION_CONFLICT", "Memory files changed during persistence.", retryable=True, committed=True)
                revision = self._revision_for(records)
                self._write_summary(
                    revision, records, summary_text=summary_text, dirty_already=True,
                    source_fingerprint=persisted,
                )
                if self.startup_snapshot().status != "current":
                    raise MemoryCatalogError("STORAGE_ERROR", "Saved summary is unavailable.", retryable=True, committed=True)
            except MemoryCatalogError as exc:
                exc.committed = content_committed or exc.committed
                raise
            except OSError as exc:
                raise MemoryCatalogError(
                    "STORAGE_ERROR", f"Memory persistence failed: {exc}",
                    retryable=True, committed=content_committed,
                ) from exc

        return ApplyResult(
            success=True,
            action=change.action,
            target=change.target,
            entry_id=changed_id,
            revision=revision,
            usage_chars=char_count(target_entries),
            limit_chars=self._char_limit(change.target),
            message=message,
            entry=selected if change.action != "remove" else None,
            entry_count=len(target_entries),
        )

    def _validate_change(self, change: MemoryChange) -> None:
        if change.action not in ("add", "replace", "remove"):
            raise MemoryCatalogError("INVALID_REQUEST", f"Invalid action: {change.action}")
        if change.target not in ("memory", "user"):
            raise MemoryCatalogError("INVALID_REQUEST", f"Invalid target: {change.target}")
        if change.action in ("add", "replace"):
            if not isinstance(change.content, str):
                raise MemoryCatalogError("INVALID_REQUEST", "content must be a string.")
            content = change.content.strip()
            if not content:
                raise MemoryCatalogError("INVALID_REQUEST", "Content cannot be empty.")
            if "§" in content.splitlines() or "<!-- improve-entry" in content:
                raise MemoryCatalogError("INVALID_REQUEST", "Pass one entry body without entry markers or delimiters.")
            threat = scan_memory_content(content)
            if threat:
                readable_threat = threat.replace("invisible_unicode", "invisible unicode")
                raise MemoryCatalogError(
                    "UNSAFE_CONTENT",
                    f"Unsafe memory content: {readable_threat}",
                )
        if change.action in ("replace", "remove") and not (
            change.entry_id or (change.old_text or "").strip()
        ):
            raise MemoryCatalogError(
                "INVALID_REQUEST",
                "entry_id or old_text is required.",
            )
        if change.startup is not None and type(change.startup) is not bool:
            raise MemoryCatalogError("INVALID_REQUEST", "startup must be a boolean.")

    def _entry_from_change(self, change: MemoryChange, content: str) -> MemoryEntry:
        timestamp = unix_timestamp()
        return MemoryEntry(
            entry_id=new_entry_id(change.target, timestamp),
            target=change.target, content=content, summary=self._summary_cue(content),
            startup=change.startup if change.startup is not None else True,
            updated_at=timestamp,
        )

    def _select_entry(
        self,
        records: list[MemoryEntry],
        change: MemoryChange,
    ) -> MemoryEntry | None:
        if change.action == "add":
            return None
        if change.entry_id:
            match = next(
                (
                    entry
                    for entry in records
                    if entry.entry_id == change.entry_id and entry.target == change.target
                ),
                None,
            )
            return match

        old_text = " ".join((change.old_text or "").split())
        matches = [
            entry
            for entry in records
            if entry.target == change.target
            and old_text in " ".join(entry.content.split())
        ]
        if len(matches) > 1:
            raise MemoryCatalogError(
                "AMBIGUOUS_SELECTOR",
                "Multiple entries matched old_text; recall and use entry_id.",
            )
        return matches[0] if matches else None

    def _path_for(self, target: Target) -> Path:
        return self.memory_dir / ("USER.md" if target == "user" else "MEMORY.md")

    def _read_source(self, target: Target) -> str:
        path = self._path_for(target)
        try:
            return path.read_bytes().decode("utf-8")
        except FileNotFoundError:
            return ""
        except (OSError, UnicodeError) as exc:
            raise MemoryCatalogError("STORAGE_ERROR", f"Cannot read {path}: {exc}") from exc

    def _read_entries(self, target: Target) -> list[str]:
        return [entry.content for entry in parse_entries(self._read_source(target))]

    def _upgrade_legacy(self) -> None:
        has_metadata = (self.memory_dir / "METADATA.jsonl").exists()
        try:
            upgrade_memory_files(self.memory_dir)
        except (OSError, UnicodeError, ValueError) as exc:
            code = "MIGRATION_ERROR" if has_metadata else (
                "INVALID_FORMAT" if isinstance(exc, ValueError) else "STORAGE_ERROR"
            )
            raise MemoryCatalogError(code, f"Cannot migrate memory in {self.memory_dir}: {exc}", retryable=isinstance(exc, OSError)) from exc

    def _reconcile_entries(self) -> list[MemoryEntry]:
        records: list[MemoryEntry] = []
        used_ids: set[str] = set()
        parsed = {}
        reserved_ids: set[str] = set()
        for target in ("user", "memory"):
            try:
                entries = parse_entries(self._read_source(target))
            except ValueError as exc:
                raise MemoryCatalogError("INVALID_FORMAT", f"{self._path_for(target)}: {exc}") from exc
            parsed[target] = entries
            for index, entry in enumerate(entries, 1):
                if entry.entry_id:
                    if entry.entry_id in reserved_ids:
                        raise MemoryCatalogError("INVALID_FORMAT", f"{self._path_for(target)} entry {index}: duplicate id {entry.entry_id}.")
                    reserved_ids.add(entry.entry_id)
        for target, entries in parsed.items():
            for entry in entries:
                entry_id = entry.entry_id or _derived_entry_id(target, entry.content)
                suffix = 1
                base_id = entry_id
                while entry_id in used_ids or (entry.entry_id is None and entry_id in reserved_ids):
                    entry_id = f"{base_id}-{suffix}"
                    suffix += 1
                used_ids.add(entry_id)
                records.append(MemoryEntry(
                    entry_id, target, entry.content, self._summary_cue(entry.content), entry.startup, entry.raw, entry.updated_at,
                ))
        return records

    def _revision_for(self, records: list[MemoryEntry]) -> str:
        return _sha256_text(json.dumps(
            [[entry.target, entry.entry_id, entry.content, entry.startup, entry.updated_at] for entry in sorted(records, key=lambda item: 0 if item.target == "user" else 1)],
            ensure_ascii=False, separators=(",", ":"),
        ))

    def _source_fingerprint(self) -> dict[str, list[int] | None]:
        result: dict[str, list[int] | None] = {}
        for name in ("MEMORY.md", "USER.md", "METADATA.jsonl"):
            path = self.memory_dir / name
            try:
                stat = path.stat()
            except FileNotFoundError:
                if name != "METADATA.jsonl":
                    result[name] = None
            else:
                result[name] = [stat.st_size, stat.st_mtime_ns]
        return result

    def _char_limit(self, target: Target) -> int:
        return self.user_char_limit if target == "user" else self.memory_char_limit

    def _check_storage_limit(self, target: Target, entries: list[str]) -> None:
        if char_count(entries) > self._char_limit(target):
            raise MemoryCatalogError(
                "LIMIT_EXCEEDED",
                f"The change would exceed the limit for {target} memory.",
            )

    @staticmethod
    def _summary_cue(content: str, limit: int = ENTRY_SUMMARY_CHAR_LIMIT) -> str:
        first_line = " ".join(content.splitlines()[0].split())
        return first_line if len(first_line) <= limit else first_line[: limit - 1] + "…"

    @staticmethod
    def _search_terms(text: str) -> set[str]:
        normalized = text.casefold()
        words = set(re.findall(r"[a-z0-9_][a-z0-9_.+-]*", normalized))
        cjk_runs = re.findall(r"[\u3400-\u9fff]+", normalized)
        for run in cjk_runs:
            if len(run) == 1:
                words.add(run)
            else:
                words.update(run[index : index + 2] for index in range(len(run) - 1))
        return words

    @classmethod
    def _relevance_score(
        cls,
        entry: MemoryEntry,
        query: str,
        query_terms: set[str],
        mode: RecallMode,
    ) -> int:
        if mode == "browse":
            return 1
        haystack = entry.content.casefold()
        normalized_query = " ".join(query.casefold().split())
        if mode == "exact":
            return 100 if normalized_query in " ".join(haystack.split()) else 0
        phrase_bonus = 20 if normalized_query in " ".join(haystack.split()) else 0
        overlap = len(query_terms & cls._search_terms(haystack))
        return phrase_bonus + overlap

    def _build_summary(
        self,
        records: list[MemoryEntry],
    ) -> str:
        safe_records = [
            entry
            for entry in records
            if entry.startup
            and not _entry_threat(entry)
        ]
        if not safe_records:
            return ""
        safe_records.sort(key=lambda entry: 0 if entry.target == "user" else 1)

        header = "MEMORY BRIEF"
        footer = "If these cues matter to the task, use memory_recall for details."
        lines = [header]
        omitted = 0
        for index, entry in enumerate(safe_records):
            cue = f"- [{entry.target}] {entry.summary}"
            remaining = len(safe_records) - index - 1
            suffix = (
                f"\n{remaining} more entr{'y' if remaining == 1 else 'ies'} omitted."
                if remaining
                else ""
            )
            candidate = "\n".join([*lines, cue]) + suffix + "\n" + footer
            if len(candidate) > self.summary_char_limit:
                omitted = len(safe_records) - index
                break
            lines.append(cue)

        if omitted:
            lines.append(f"{omitted} more entr{'y' if omitted == 1 else 'ies'} omitted.")
        lines.append(footer)
        text = "\n".join(lines)
        if len(text) > self.summary_char_limit:
            text = text[: self.summary_char_limit - 1] + "…"
        return text

    def _write_summary(
        self,
        source_revision: str,
        records: list[MemoryEntry],
        *,
        summary_text: str | None = None,
        dirty_already: bool = False,
        source_fingerprint: dict[str, list[int] | None] | None = None,
    ) -> None:
        dirty_path = self.memory_dir / ".summary.dirty"
        if not dirty_already:
            atomic_write_text(dirty_path, source_revision, temp_prefix=".summary_dirty_")
        if summary_text is None:
            summary_text = self._build_summary(records)
        serialized = (
            f"<!-- improve-summary:v4 source-revision={source_revision} -->\n"
            f"{summary_text}\n"
        )
        atomic_write_text(
            self.memory_dir / "SUMMARY.md",
            serialized,
            temp_prefix=".summary_",
        )
        state = {
            "format_version": 4,
            "source_revision": source_revision,
            "source_fingerprint": (
                source_fingerprint if source_fingerprint is not None else self._source_fingerprint()
            ),
            "summary_sha256": _sha256_text(serialized),
        }
        atomic_write_text(
            self.memory_dir / ".summary-state.json",
            json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
            temp_prefix=".summary_state_",
        )
        dirty_path.unlink(missing_ok=True)
