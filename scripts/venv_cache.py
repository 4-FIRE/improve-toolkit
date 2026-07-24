#!/usr/bin/env python3
"""Cross-platform shared virtualenv cache for the Improve MCP server."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None


CACHE_SCHEMA = 1
READY_FILENAME = ".improve-ready.json"
LOCK_TIMEOUT_SECONDS = 120.0
LOCK_POLL_INTERVAL = 0.2


@dataclass(frozen=True)
class VenvResolution:
    path: Path
    key: str
    requirements_sha256: str
    shared: bool
    cache_root: Path | None
    managed: bool


def get_cache_root(
    *,
    environ: dict[str, str] | None = None,
    platform_name: str | None = None,
    home: Path | None = None,
) -> Path:
    """Return the per-user cache root using native platform conventions."""
    env = os.environ if environ is None else environ
    override = env.get("IMPROVE_CACHE_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    active_platform = sys.platform if platform_name is None else platform_name
    user_home = Path.home() if home is None else Path(home)
    if active_platform == "win32":
        local_app_data = env.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else user_home / "AppData" / "Local"
        return base / "ImproveToolkit" / "Cache"
    if active_platform == "darwin":
        return user_home / "Library" / "Caches" / "improve-toolkit"

    xdg_cache = env.get("XDG_CACHE_HOME", "").strip()
    base = Path(xdg_cache).expanduser() if xdg_cache else user_home / ".cache"
    return base / "improve-toolkit"


def _requirements_sha256(requirements_path: Path) -> str:
    return hashlib.sha256(requirements_path.read_bytes()).hexdigest()


def _safe_tag(value: str, limit: int = 24) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (normalized or "unknown")[:limit]


def get_python_identity() -> dict[str, str]:
    """Return compatibility fields that make a cached venv safe to reuse."""
    base_executable = Path(
        getattr(sys, "_base_executable", None) or sys.executable
    ).resolve()
    return {
        "implementation": sys.implementation.name,
        "version": platform.python_version(),
        "executable": str(base_executable),
        "soabi": str(sysconfig.get_config_var("SOABI") or "none"),
        "platform": sys.platform,
        "machine": platform.machine() or "unknown",
    }


def build_cache_key(
    requirements_path: Path,
    *,
    identity: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Build a short key independent of the plugin installation/version path."""
    requirements_sha256 = _requirements_sha256(requirements_path)
    python_identity = get_python_identity() if identity is None else identity
    payload = {
        "schema": CACHE_SCHEMA,
        "requirements_sha256": requirements_sha256,
        "python": python_identity,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    version = python_identity.get("version", "unknown").replace(".", "")
    prefix = "-".join(
        (
            _safe_tag(python_identity.get("implementation", "python"), 12),
            _safe_tag(version, 12),
            _safe_tag(python_identity.get("platform", "unknown"), 12),
            _safe_tag(python_identity.get("machine", "unknown"), 16),
        )
    )
    return f"{prefix}-{digest}", requirements_sha256


def resolve_venv(
    requirements_path: Path,
    fallback_dir: Path,
    *,
    environ: dict[str, str] | None = None,
) -> VenvResolution:
    """Resolve an explicit or per-user shared venv without creating it."""
    env = os.environ if environ is None else environ
    key, requirements_sha256 = build_cache_key(requirements_path)
    explicit = env.get("IMPROVE_VENV_DIR", "").strip()
    if explicit:
        return VenvResolution(
            path=Path(explicit).expanduser(),
            key=key,
            requirements_sha256=requirements_sha256,
            shared=True,
            cache_root=None,
            managed=False,
        )

    cache_root = get_cache_root(environ=env)
    return VenvResolution(
        path=cache_root / "venvs" / key,
        key=key,
        requirements_sha256=requirements_sha256,
        shared=True,
        cache_root=cache_root,
        managed=True,
    )


def venv_python_path(venv_dir: Path, *, platform_name: str | None = None) -> Path | None:
    active_platform = sys.platform if platform_name is None else platform_name
    bin_dir = venv_dir / ("Scripts" if active_platform == "win32" else "bin")
    candidates = (
        (bin_dir / "python.exe",)
        if active_platform == "win32"
        else (bin_dir / "python3", bin_dir / "python")
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _locked_file_path(resolution: VenvResolution) -> Path:
    if resolution.cache_root is not None:
        return resolution.cache_root / "venvs" / f"{resolution.key}.lock"
    return resolution.path.with_name(f"{resolution.path.name}.lock")


@contextmanager
def _cache_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if msvcrt and (not path.exists() or path.stat().st_size == 0):
        path.write_text(" ", encoding="utf-8")

    descriptor = open(path, "r+" if msvcrt else "a+")
    acquired = False
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    try:
        while True:
            try:
                if fcntl:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif msvcrt:
                    descriptor.seek(0)
                    msvcrt.locking(descriptor.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
                break
            except (OSError, IOError):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timed out waiting for virtualenv cache lock {path}"
                    )
                time.sleep(min(LOCK_POLL_INTERVAL, remaining))
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


def _locked_requirements(requirements_path: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line)
        if not match:
            raise ValueError(
                f"Bootstrap requirement must use an exact == pin: {raw_line!r}"
            )
        expected[match.group(1)] = match.group(2)
    if not expected:
        raise ValueError(f"No dependencies found in {requirements_path}")
    return expected


def _probe_venv(python_path: Path, requirements_path: Path) -> bool:
    expected = _locked_requirements(requirements_path)
    probe_code = (
        "import importlib.metadata as m; import mcp, yaml; "
        f"expected={expected!r}; "
        "assert all(m.version(name) == version for name, version in expected.items())"
    )
    result = subprocess.run(
        [str(python_path), "-c", probe_code],
        capture_output=True,
    )
    return result.returncode == 0


def _ready_payload(resolution: VenvResolution) -> dict[str, object]:
    return {
        "schema": CACHE_SCHEMA,
        "key": resolution.key,
        "requirements_sha256": resolution.requirements_sha256,
        "python": get_python_identity(),
    }


def _ready_matches(resolution: VenvResolution) -> bool:
    marker = resolution.path / READY_FILENAME
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return payload == _ready_payload(resolution)


def _write_ready_marker(resolution: VenvResolution) -> None:
    payload = json.dumps(
        _ready_payload(resolution),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    fd, temp_path = tempfile.mkstemp(
        dir=str(resolution.path),
        prefix=".ready_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, resolution.path / READY_FILENAME)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _create_or_repair_venv(
    resolution: VenvResolution,
    requirements_path: Path,
) -> Path:
    python_path = venv_python_path(resolution.path)
    if (
        python_path is not None
        and _ready_matches(resolution)
        and _probe_venv(python_path, requirements_path)
    ):
        return python_path

    if python_path is not None and _probe_venv(python_path, requirements_path):
        _write_ready_marker(resolution)
        return python_path

    if resolution.path.exists() and not resolution.managed:
        if not (resolution.path / "pyvenv.cfg").is_file() or python_path is None:
            raise RuntimeError(
                f"IMPROVE_VENV_DIR is not a virtualenv: {resolution.path}"
            )
    else:
        if resolution.path.exists():
            shutil.rmtree(resolution.path)

        print(f"创建共享虚拟环境: {resolution.path}", file=sys.stderr)
        subprocess.check_call(
            [sys.executable, "-m", "venv", str(resolution.path)],
            stdout=sys.stderr,
        )
        python_path = venv_python_path(resolution.path)
        if python_path is None:
            raise RuntimeError(f"Virtualenv Python not found under {resolution.path}")

    subprocess.check_call(
        [
            str(python_path),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirements_path),
        ],
        stdout=sys.stderr,
    )

    if sys.platform == "win32":
        postinstall = resolution.path / "Scripts" / "pywin32_postinstall.py"
        if postinstall.is_file():
            subprocess.run(
                [str(python_path), str(postinstall), "-install"],
                capture_output=True,
            )

    if not _probe_venv(python_path, requirements_path):
        raise RuntimeError(
            f"Virtualenv dependency verification failed under {resolution.path}"
        )
    _write_ready_marker(resolution)
    return python_path


def ensure_runtime_venv(requirements_path: Path, fallback_dir: Path) -> Path:
    """Return a healthy shared venv Python, falling back to version-local state."""
    resolution = resolve_venv(requirements_path, fallback_dir)
    try:
        with _cache_lock(_locked_file_path(resolution)):
            return _create_or_repair_venv(resolution, requirements_path)
    except (OSError, TimeoutError) as exc:
        if resolution.path == fallback_dir:
            raise
        print(
            f"improve: shared virtualenv cache unavailable ({exc}); "
            f"falling back to {fallback_dir}",
            file=sys.stderr,
        )

    fallback_key, requirements_sha256 = build_cache_key(requirements_path)
    fallback = VenvResolution(
        path=fallback_dir,
        key=fallback_key,
        requirements_sha256=requirements_sha256,
        shared=False,
        cache_root=None,
        managed=True,
    )
    with _cache_lock(_locked_file_path(fallback)):
        return _create_or_repair_venv(fallback, requirements_path)
