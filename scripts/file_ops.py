#!/usr/bin/env python3
"""Cross-platform file locking and atomic text writes."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None


@contextmanager
def file_lock(
    lock_path: Path,
    *,
    timeout: float,
    poll_interval: float,
    logger: logging.Logger | None = None,
    description: str | None = None,
) -> Iterator[None]:
    """Acquire an exclusive advisory lock with a bounded retry loop."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    label = description or f"file lock {lock_path}"

    if fcntl is None and msvcrt is None:
        if logger is not None:
            logger.warning("lock: no supported backend; continuing unlocked for %s", lock_path)
        yield
        return

    descriptor = open(lock_path, "a+")
    acquired = False
    deadline = time.monotonic() + timeout
    attempts = 0
    log_every = max(1, round(1.0 / poll_interval))

    try:
        if msvcrt:
            descriptor.seek(0, os.SEEK_END)
            if descriptor.tell() == 0:
                descriptor.write(" ")
                descriptor.flush()

        while True:
            try:
                if fcntl:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    descriptor.seek(0)
                    msvcrt.locking(descriptor.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
                break
            except (OSError, IOError) as exc:
                attempts += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timed out waiting for {label} after {timeout:.0f}s."
                    ) from exc
                if logger is not None and (
                    attempts == 1 or attempts % log_every == 0
                ):
                    logger.warning(
                        "lock: waiting on %s (%.1fs left, attempt %d)",
                        lock_path,
                        remaining,
                        attempts,
                    )
                time.sleep(min(poll_interval, remaining))

        if logger is not None:
            logger.debug("lock: acquired %s after %d attempt(s)", lock_path, attempts)
        yield
    finally:
        if acquired and fcntl:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        elif acquired and msvcrt:
            try:
                descriptor.seek(0)
                msvcrt.locking(descriptor.fileno(), msvcrt.LK_UNLCK, 1)
            except (OSError, IOError):
                pass
        descriptor.close()
        if logger is not None:
            logger.debug("lock: released %s", lock_path)


def atomic_write_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    temp_prefix: str | None = None,
    temp_suffix: str = ".tmp",
    fsync: bool = True,
) -> None:
    """Write text to a sibling temporary file and atomically replace *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=temp_prefix or f".{path.name}.tmp.",
        suffix=temp_suffix,
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
            handle.flush()
            if fsync:
                os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
