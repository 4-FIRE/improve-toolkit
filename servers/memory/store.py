#!/usr/bin/env python3
"""Project memory views, diagnostic logging and the change audit."""

import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from memory_format import parse_entries
from memory_catalog import MemoryCatalog, MemoryCatalogError

from .utils import get_home

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

class MemoryStore:
    """Hold the project paths, limits and body views used by MCP adapters."""

    def __init__(
        self,
        memory_char_limit: int | None = None,
        user_char_limit: int | None = None,
        data_home: Path | None = None,
        memory_dir: Path | None = None,
    ) -> None:
        self.data_home = Path(data_home) if data_home is not None else get_home()
        self.memory_dir = Path(memory_dir) if memory_dir is not None else get_memory_dir(self.data_home)
        catalog = MemoryCatalog(
            memory_dir=self.memory_dir, data_home=self.data_home,
            memory_char_limit=memory_char_limit, user_char_limit=user_char_limit,
        )
        self.memory_char_limit = catalog.memory_char_limit
        self.user_char_limit = catalog.user_char_limit
        self.memory_entries: list[str] = []
        self.user_entries: list[str] = []

    def load_from_disk(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_entries = self._read_file(self.memory_dir / "MEMORY.md")
        self.user_entries = self._read_file(self.memory_dir / "USER.md")

    @staticmethod
    def _read_file(path: Path) -> list[str]:
        try:
            raw = path.read_bytes().decode("utf-8")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError) as exc:
            raise MemoryCatalogError("STORAGE_ERROR", f"Cannot read {path}: {exc}") from exc
        try:
            return [entry.content for entry in parse_entries(raw)]
        except ValueError as exc:
            raise MemoryCatalogError("INVALID_FORMAT", f"{path}: {exc}") from exc
