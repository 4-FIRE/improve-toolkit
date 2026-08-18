#!/usr/bin/env python3
"""Shared, stdlib-only memory catalog for hooks and MCP adapters."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from file_ops import atomic_write_text, file_lock
from memory_format import (
    MEMORY_CHAR_LIMIT,
    USER_CHAR_LIMIT,
    char_count,
    join_entries,
    split_entries,
)


Target = Literal["memory", "user"]
SummaryStatus = Literal["current", "unavailable"]
StartupPolicy = Literal["always", "auto", "never"]
RecallMode = Literal["relevant", "exact", "browse"]

DEFAULT_SUMMARY_CHAR_LIMIT = 800
DEFAULT_RECALL_CHAR_LIMIT = 2400
DEFAULT_RECALL_LIMIT = 5
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
    (r"authorized_keys", "ssh_backdoor"),
    (r"\$HOME/\.ssh|~/\.ssh", "ssh_access"),
)
_INVISIBLE_CHARS = frozenset(
    "\u200b\u200c\u200d\u2060\ufeff\u202a\u202b\u202c\u202d\u202e"
)


class MemoryCatalogError(RuntimeError):
    """Structured failure crossing the MemoryCatalog Interface."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        committed: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.committed = committed


@dataclass(frozen=True)
class MemoryChange:
    action: Literal["add", "replace", "remove"]
    target: Target
    content: str | None = None
    entry_id: str | None = None
    old_text: str | None = None
    summary: str | None = None
    tags: tuple[str, ...] | None = None
    priority: int | None = None
    startup: StartupPolicy | None = None
    source: str | None = None


@dataclass(frozen=True)
class SummarySnapshot:
    text: str
    status: SummaryStatus
    source_revision: str | None


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


@dataclass(frozen=True)
class MemoryEntry:
    entry_id: str
    target: Target
    content: str
    summary: str
    tags: tuple[str, ...] = ()
    priority: int = 50
    startup: StartupPolicy = "auto"
    source: str | None = None


@dataclass(frozen=True)
class RecallResult:
    success: bool
    entries: tuple[MemoryEntry, ...]
    revision: str
    returned_chars: int
    truncated: bool
    quarantined_count: int = 0


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


def scan_memory_content(content: str) -> str | None:
    """Return a stable threat code when memory content is unsafe to expose."""
    for character in _INVISIBLE_CHARS:
        if character in content:
            return f"invisible_unicode_U+{ord(character):04X}"
    for pattern, threat_code in _MEMORY_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return threat_code
    return None


class MemoryCatalog:
    """Deep Module for durable memory, recall, and the SessionStart brief."""

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
            else _env_positive_int(
                "IMPROVE_RECALL_CHAR_LIMIT",
                DEFAULT_RECALL_CHAR_LIMIT,
            )
        )

    def startup_snapshot(self) -> SummarySnapshot:
        """Read only the materialized summary and its small validation state."""
        summary_path = self.memory_dir / "SUMMARY.md"
        state_path = self.memory_dir / ".summary-state.json"
        dirty_path = self.memory_dir / ".summary.dirty"
        if dirty_path.exists() or not summary_path.is_file() or not state_path.is_file():
            return SummarySnapshot("", "unavailable", None)

        try:
            raw = summary_path.read_text(encoding="utf-8")
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return SummarySnapshot("", "unavailable", None)

        if state.get("summary_sha256") != _sha256_text(raw):
            return SummarySnapshot("", "unavailable", None)
        if state.get("source_fingerprint") != self._source_fingerprint():
            return SummarySnapshot("", "unavailable", None)

        lines = raw.splitlines()
        if lines and lines[0].startswith("<!-- improve-summary:"):
            lines = lines[1:]
        text = "\n".join(lines).strip()
        if len(text) > self.summary_char_limit or scan_memory_content(text):
            return SummarySnapshot("", "unavailable", None)
        return SummarySnapshot(text, "current", state.get("source_revision"))

    def recall(
        self,
        *,
        query: str,
        target: Literal["all", "memory", "user"] = "all",
        mode: RecallMode = "relevant",
        limit: int = DEFAULT_RECALL_LIMIT,
        max_chars: int | None = None,
        tags_any: tuple[str, ...] = (),
        min_priority: int | None = None,
    ) -> RecallResult:
        """Return a bounded, deterministically ranked view of live memory."""
        if target not in ("all", "memory", "user"):
            raise MemoryCatalogError("INVALID_REQUEST", f"Invalid target: {target}")
        if mode not in ("relevant", "exact", "browse"):
            raise MemoryCatalogError("INVALID_REQUEST", f"Invalid recall mode: {mode}")
        if mode != "browse" and not query.strip():
            raise MemoryCatalogError("INVALID_REQUEST", "query is required for this recall mode.")
        if limit < 1 or limit > 20:
            raise MemoryCatalogError("INVALID_REQUEST", "limit must be between 1 and 20.")
        active_char_limit = self.recall_char_limit if max_chars is None else max_chars
        if active_char_limit < 1 or active_char_limit > 12000:
            raise MemoryCatalogError(
                "INVALID_REQUEST",
                "max_chars must be between 1 and 12000.",
            )

        targets: tuple[Target, ...] = (
            ("user", "memory") if target == "all" else (target,)
        )
        lock_path = self.memory_dir / ".memory.lock"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        with file_lock(
            lock_path,
            timeout=LOCK_TIMEOUT_SECONDS,
            poll_interval=LOCK_POLL_INTERVAL,
            description=f"memory catalog lock {lock_path}",
        ):
            records = self._reconcile_entries()
            self._write_metadata(records)
            revision = self._revision_for(records)
            self._write_summary(revision, records)

        query_terms = self._search_terms(query)
        requested_tags = {tag.casefold() for tag in tags_any}
        ranked: list[tuple[int, int, int, MemoryEntry]] = []
        quarantined_count = 0
        for order, entry in enumerate(records):
            if entry.target not in targets:
                continue
            if scan_memory_content(entry.content) or scan_memory_content(entry.summary):
                quarantined_count += 1
                continue
            if requested_tags and not requested_tags.intersection(
                tag.casefold() for tag in entry.tags
            ):
                continue
            if min_priority is not None and entry.priority < min_priority:
                continue
            score = self._relevance_score(entry, query, query_terms, mode)
            if mode != "browse" and score <= 0:
                continue
            ranked.append((-score, -entry.priority, order, entry))

        ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3].entry_id))
        selected: list[MemoryEntry] = []
        returned_chars = 0
        for _, _, _, entry in ranked:
            if len(selected) >= limit:
                break
            separator_chars = 1 if selected else 0
            candidate_chars = returned_chars + separator_chars + len(entry.content)
            if candidate_chars > active_char_limit:
                continue
            selected.append(entry)
            returned_chars = candidate_chars

        return RecallResult(
            success=True,
            entries=tuple(selected),
            revision=revision,
            returned_chars=returned_chars,
            truncated=len(selected) < len(ranked),
            quarantined_count=quarantined_count,
        )

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
            records = self._reconcile_entries()
            current_revision = self._revision_for(records)
            if expected_revision is not None and expected_revision != current_revision:
                raise MemoryCatalogError(
                    "REVISION_CONFLICT",
                    "Memory changed after recall; recall again before retrying.",
                    retryable=True,
                )

            target_entries = self._read_entries(change.target)
            selected = self._select_entry(records, change)
            message: str
            changed_id: str | None

            if change.action == "add":
                content = (change.content or "").strip()
                duplicate = next(
                    (
                        entry
                        for entry in records
                        if entry.target == change.target and entry.content == content
                    ),
                    None,
                )
                if duplicate is not None:
                    selected = duplicate
                    message = "Entry already exists."
                else:
                    candidate = [*target_entries, content]
                    self._check_storage_limit(change.target, candidate)
                    target_entries = candidate
                    selected = self._entry_from_change(change, content)
                    records.append(selected)
                    message = "Entry added."
                changed_id = selected.entry_id
            elif change.action == "replace":
                if selected is None:
                    raise MemoryCatalogError("NOT_FOUND", "No entry matched the selector.")
                content = (change.content or "").strip()
                index = target_entries.index(selected.content)
                candidate = list(target_entries)
                candidate[index] = content
                self._check_storage_limit(change.target, candidate)
                target_entries = candidate
                updated = replace(
                    selected,
                    content=content,
                    summary=(
                        self._validated_summary(change.summary)
                        if change.summary is not None
                        else self._summary_cue(content)
                    ),
                    tags=(
                        self._normalized_tags(change.tags)
                        if change.tags is not None
                        else selected.tags
                    ),
                    priority=(
                        change.priority
                        if change.priority is not None
                        else selected.priority
                    ),
                    startup=(
                        change.startup
                        if change.startup is not None
                        else selected.startup
                    ),
                    source=(
                        (change.source or "").strip() or None
                        if change.source is not None
                        else selected.source
                    ),
                )
                records[records.index(selected)] = updated
                selected = updated
                changed_id = updated.entry_id
                message = "Entry replaced."
            else:
                if selected is None:
                    raise MemoryCatalogError("NOT_FOUND", "No entry matched the selector.")
                target_entries.remove(selected.content)
                records.remove(selected)
                changed_id = selected.entry_id
                message = "Entry removed."

            summary_text = self._build_summary(records, strict_always=True)
            dirty_path = self.memory_dir / ".summary.dirty"
            content_committed = False
            try:
                atomic_write_text(dirty_path, current_revision, temp_prefix=".summary_dirty_")
                atomic_write_text(
                    self._path_for(change.target),
                    join_entries(target_entries),
                    temp_prefix=".mem_",
                )
                content_committed = True
                self._write_metadata(records)
                revision = self._revision_for(records)
                self._write_summary(
                    revision,
                    records,
                    summary_text=summary_text,
                    dirty_already=True,
                )
            except OSError as exc:
                raise MemoryCatalogError(
                    "STORAGE_ERROR",
                    f"Memory persistence failed: {exc}",
                    retryable=True,
                    committed=content_committed,
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
        )

    def _validate_change(self, change: MemoryChange) -> None:
        if change.action not in ("add", "replace", "remove"):
            raise MemoryCatalogError("INVALID_REQUEST", f"Invalid action: {change.action}")
        if change.target not in ("memory", "user"):
            raise MemoryCatalogError("INVALID_REQUEST", f"Invalid target: {change.target}")
        if change.action in ("add", "replace"):
            content = (change.content or "").strip()
            if not content:
                raise MemoryCatalogError("INVALID_REQUEST", "Content cannot be empty.")
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
        if change.priority is not None and not 0 <= change.priority <= 100:
            raise MemoryCatalogError("INVALID_REQUEST", "priority must be between 0 and 100.")
        if change.startup is not None and change.startup not in ("always", "auto", "never"):
            raise MemoryCatalogError("INVALID_REQUEST", f"Invalid startup policy: {change.startup}")
        if change.summary is not None:
            self._validated_summary(change.summary)

    def _entry_from_change(self, change: MemoryChange, content: str) -> MemoryEntry:
        return MemoryEntry(
            entry_id=_derived_entry_id(change.target, content),
            target=change.target,
            content=content,
            summary=(
                self._validated_summary(change.summary)
                if change.summary is not None
                else self._summary_cue(content)
            ),
            tags=self._normalized_tags(change.tags or ()),
            priority=change.priority if change.priority is not None else 50,
            startup=change.startup if change.startup is not None else "auto",
            source=(change.source or "").strip() or None,
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

    def _read_entries(self, target: Target) -> list[str]:
        path = self._path_for(target)
        if not path.is_file():
            return []
        try:
            return list(dict.fromkeys(split_entries(path.read_text(encoding="utf-8"))))
        except (OSError, UnicodeError):
            return []

    def _read_metadata(self) -> list[dict[str, object]]:
        path = self.memory_dir / "METADATA.jsonl"
        if not path.is_file():
            return []
        records: list[dict[str, object]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return []
        for line in lines:
            try:
                record = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def _reconcile_entries(self) -> list[MemoryEntry]:
        metadata = self._read_metadata()
        by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        for record in metadata:
            target = record.get("target")
            content_hash = record.get("content_hash")
            if target in ("memory", "user") and isinstance(content_hash, str):
                by_key.setdefault((target, content_hash), []).append(record)

        reconciled: list[MemoryEntry] = []
        used_ids: set[str] = set()
        for target in ("user", "memory"):
            for content in self._read_entries(target):
                candidates = by_key.get((target, _content_hash(content)), [])
                record = next(
                    (
                        candidate
                        for candidate in candidates
                        if isinstance(candidate.get("id"), str)
                        and candidate["id"] not in used_ids
                    ),
                    None,
                )
                entry_id = (
                    str(record["id"])
                    if record is not None
                    else _derived_entry_id(target, content)
                )
                if entry_id in used_ids:
                    entry_id = _derived_entry_id(target, content + f"\0{len(used_ids)}")
                used_ids.add(entry_id)
                summary = (
                    str(record.get("summary", "")).strip()
                    if record is not None
                    else ""
                ) or self._summary_cue(content)
                tags_value = record.get("tags", []) if record is not None else []
                tags = self._normalized_tags(
                    tuple(str(tag) for tag in tags_value)
                    if isinstance(tags_value, list)
                    else ()
                )
                priority_value = record.get("priority", 50) if record is not None else 50
                priority = priority_value if isinstance(priority_value, int) else 50
                priority = min(100, max(0, priority))
                startup_value = record.get("startup", "auto") if record is not None else "auto"
                startup: StartupPolicy = (
                    startup_value
                    if startup_value in ("always", "auto", "never")
                    else "auto"
                )
                source_value = record.get("source") if record is not None else None
                source = str(source_value).strip() if source_value else None
                reconciled.append(
                    MemoryEntry(
                        entry_id=entry_id,
                        target=target,
                        content=content,
                        summary=summary,
                        tags=tags,
                        priority=priority,
                        startup=startup,
                        source=source,
                    )
                )
        return reconciled

    @staticmethod
    def _metadata_record(entry: MemoryEntry) -> dict[str, object]:
        return {
            "id": entry.entry_id,
            "target": entry.target,
            "content_hash": _content_hash(entry.content),
            "summary": entry.summary,
            "tags": list(entry.tags),
            "priority": entry.priority,
            "startup": entry.startup,
            "source": entry.source,
        }

    def _serialize_metadata(self, records: list[MemoryEntry]) -> str:
        return "\n".join(
            json.dumps(
                self._metadata_record(entry),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for entry in records
        )

    def _write_metadata(self, records: list[MemoryEntry]) -> None:
        serialized = self._serialize_metadata(records)
        atomic_write_text(
            self.memory_dir / "METADATA.jsonl",
            serialized + ("\n" if serialized else ""),
            temp_prefix=".metadata_",
        )

    def _revision_for(self, records: list[MemoryEntry]) -> str:
        memory = join_entries(self._read_entries("memory"))
        user = join_entries(self._read_entries("user"))
        metadata = self._serialize_metadata(records)
        return _sha256_text(
            f"memory\0{memory}\0user\0{user}\0metadata\0{metadata}"
        )

    def _source_fingerprint(self) -> dict[str, list[int] | None]:
        result: dict[str, list[int] | None] = {}
        for name in ("MEMORY.md", "USER.md", "METADATA.jsonl"):
            path = self.memory_dir / name
            try:
                stat = path.stat()
            except OSError:
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
    def _summary_cue(content: str, limit: int = 120) -> str:
        first_line = " ".join(content.splitlines()[0].split())
        return first_line if len(first_line) <= limit else first_line[: limit - 1] + "…"

    @staticmethod
    def _validated_summary(summary: str) -> str:
        normalized = " ".join(summary.split())
        if not normalized:
            raise MemoryCatalogError("INVALID_REQUEST", "summary cannot be empty.")
        if len(normalized) > 160:
            raise MemoryCatalogError("INVALID_REQUEST", "summary cannot exceed 160 characters.")
        threat = scan_memory_content(normalized)
        if threat:
            raise MemoryCatalogError("UNSAFE_CONTENT", f"Unsafe memory summary: {threat}")
        return normalized

    @staticmethod
    def _normalized_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
        normalized = []
        for tag in tags:
            value = " ".join(str(tag).split()).casefold()
            if value and value not in normalized:
                normalized.append(value)
        return tuple(normalized[:12])

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
        haystack = " ".join((entry.summary, entry.content, *entry.tags)).casefold()
        normalized_query = " ".join(query.casefold().split())
        if mode == "exact":
            return 100 if normalized_query in " ".join(haystack.split()) else 0
        phrase_bonus = 20 if normalized_query in " ".join(haystack.split()) else 0
        overlap = len(query_terms & cls._search_terms(haystack))
        return phrase_bonus + overlap

    def _build_summary(
        self,
        records: list[MemoryEntry],
        *,
        strict_always: bool = False,
    ) -> str:
        safe_records = [
            entry
            for entry in records
            if entry.startup != "never"
            and not scan_memory_content(entry.content)
            and not scan_memory_content(entry.summary)
        ]
        if not safe_records:
            return ""
        safe_records.sort(
            key=lambda entry: (
                0 if entry.startup == "always" else 1,
                0 if entry.target == "user" else 1,
                -entry.priority,
                entry.entry_id,
            )
        )

        header = "MEMORY BRIEF"
        footer = "Use memory_recall with the current task for relevant details."
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
                if strict_always and entry.startup == "always":
                    raise MemoryCatalogError(
                        "SUMMARY_LIMIT_EXCEEDED",
                        "startup=always entries exceed the SessionStart summary budget.",
                    )
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
    ) -> None:
        dirty_path = self.memory_dir / ".summary.dirty"
        if not dirty_already:
            atomic_write_text(dirty_path, source_revision, temp_prefix=".summary_dirty_")
        if summary_text is None:
            summary_text = self._build_summary(records)
        serialized = (
            f"<!-- improve-summary:v2 source-revision={source_revision} -->\n"
            f"{summary_text}\n"
        )
        atomic_write_text(
            self.memory_dir / "SUMMARY.md",
            serialized,
            temp_prefix=".summary_",
        )
        state = {
            "source_revision": source_revision,
            "source_fingerprint": self._source_fingerprint(),
            "summary_sha256": _sha256_text(serialized),
        }
        atomic_write_text(
            self.memory_dir / ".summary-state.json",
            json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
            temp_prefix=".summary_state_",
        )
        dirty_path.unlink(missing_ok=True)
