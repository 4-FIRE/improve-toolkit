#!/usr/bin/env python3
"""
MCP Server for Improve Toolkit - stdio protocol

Exposes persistent memory curation and bounded recall via stdio transport.
"""

import os
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent
SCRIPTS_DIR = PLUGIN_DIR.parent / "scripts"
sys.path.insert(0, str(PLUGIN_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

IS_WINDOWS = sys.platform == "win32"
REQUIREMENTS_LOCK = PLUGIN_DIR / "requirements.lock"
LOCAL_VENV_FALLBACK = PLUGIN_DIR / ".venv"

from venv_cache import ensure_runtime_venv


def re_exec_into_venv(venv_python):
    """Run this server under the venv interpreter; never returns.

    On POSIX, os.execv replaces the process in place. On Windows, os.execv
    spawns a child while the parent keeps running, which severs the stdio
    pipes the MCP host speaks over — so instead spawn the venv python as a
    child with inherited stdio handles and wait. The host talks to the child
    directly through those inherited pipes.

    Running under the venv interpreter is required on Windows because mcp's
    transitive dep pywin32 registers its pywintypes DLL onto the search path
    only via a .pth that runs at venv-interpreter startup; the parent (system)
    Python cannot load it, and importing mcp from site-packages prepended to
    the parent's sys.path fails with `No module named 'pywintypes'`.
    """
    argv = [str(venv_python), __file__, *sys.argv[1:]]
    if IS_WINDOWS:
        proc = subprocess.Popen(
            argv,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        sys.exit(proc.wait())
    else:
        os.execv(str(venv_python), argv)


# Resolve/install only from a base interpreter. After re-exec, sys.prefix is
# the selected shared (or local fallback) virtualenv and bootstrap is a no-op.
if sys.prefix == sys.base_prefix:
    _venv_python = ensure_runtime_venv(REQUIREMENTS_LOCK, LOCAL_VENV_FALLBACK)
    re_exec_into_venv(_venv_python)

import asyncio
import json

from mcp.server import Server
from mcp.types import Tool, TextContent

from memory import (
    MEMORY_RECALL_SCHEMA,
    MEMORY_SCHEMA,
    MemoryStore,
    mutate_memory,
    recall_memory,
)
from runtime_paths import get_host, get_project_dir, prepare_data_home
from memory_migration import prepare_memories_dir
from transport import stdio_server

app = Server("improve")

memory_stores = {}


def resolve_project_dir(arguments: dict) -> Path:
    """Resolve and validate the workspace root used by a stateful tool call."""
    raw_project_dir = arguments.get("project_dir")
    if not raw_project_dir:
        if get_host() == "codex":
            raise ValueError(
                "project_dir is required when Improve Toolkit runs under Codex. "
                "Pass the absolute current workspace root."
            )
        return get_project_dir().resolve()

    project_dir = Path(raw_project_dir).expanduser()
    if not project_dir.is_absolute():
        raise ValueError("project_dir must be an absolute path.")
    project_dir = project_dir.resolve()
    if not project_dir.is_dir():
        raise ValueError(f"project_dir does not exist or is not a directory: {project_dir}")
    return project_dir


def get_memory_store(project_dir: Path) -> MemoryStore:
    """Return the cached memory store for one project."""
    data_home = prepare_data_home(project_dir).resolve()
    memory_dir = prepare_memories_dir(project_dir).resolve()
    store = memory_stores.get(memory_dir)
    if store is None:
        store = MemoryStore(data_home=data_home, memory_dir=memory_dir)
        store.load_from_disk()
        memory_stores[memory_dir] = store
    return store


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="memory",
            description=MEMORY_SCHEMA["description"],
            inputSchema=MEMORY_SCHEMA["parameters"],
        ),
        Tool(
            name="memory_recall",
            description=MEMORY_RECALL_SCHEMA["description"],
            inputSchema=MEMORY_RECALL_SCHEMA["parameters"],
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "memory":
        try:
            project_dir = resolve_project_dir(arguments)
        except ValueError as exc:
            error = json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
            return [TextContent(type="text", text=error)]

        result = mutate_memory(
            action=arguments.get("action", ""),
            target=arguments.get("target", "memory"),
            content=arguments.get("content"),
            old_text=arguments.get("old_text"),
            entry_id=arguments.get("entry_id"),
            expected_revision=arguments.get("expected_revision"),
            summary=arguments.get("summary"),
            tags=arguments.get("tags"),
            priority=arguments.get("priority"),
            startup=arguments.get("startup"),
            source=arguments.get("source"),
            store=get_memory_store(project_dir),
        )
        return [TextContent(type="text", text=result)]

    if name == "memory_recall":
        try:
            project_dir = resolve_project_dir(arguments)
        except ValueError as exc:
            error = json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
            return [TextContent(type="text", text=error)]

        result = recall_memory(
            query=arguments.get("query", ""),
            target=arguments.get("target", "all"),
            limit=arguments.get("limit", 5),
            max_chars=arguments.get("max_chars"),
            tags_any=arguments.get("tags_any"),
            min_priority=arguments.get("min_priority"),
            store=get_memory_store(project_dir),
        )
        return [TextContent(type="text", text=result)]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False))]


def main():
    asyncio.run(run_server())


async def run_server():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    main()
