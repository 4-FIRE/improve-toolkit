#!/usr/bin/env python3
"""
MCP Server for Improve Toolkit - stdio protocol

Exposes memory_tool and skill_manager_tool as MCP tools via stdio transport.
"""

import os
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent
VENV_DIR = PLUGIN_DIR / ".venv"
SCRIPTS_DIR = PLUGIN_DIR.parent / "scripts"
sys.path.insert(0, str(PLUGIN_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

IS_WINDOWS = sys.platform == "win32"


def venv_bin_dir():
    """Venv executable directory: Scripts on Windows, bin elsewhere."""
    return VENV_DIR / ("Scripts" if IS_WINDOWS else "bin")


def venv_python_path():
    """Resolve the venv's Python executable across platforms."""
    bin_dir = venv_bin_dir()
    candidates = [
        bin_dir / ("python.exe" if IS_WINDOWS else "python3"),
        bin_dir / ("python.exe" if IS_WINDOWS else "python"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def ensure_venv():
    """Create the venv if missing and return the path to its Python executable.

    Does NOT activate/re-exec — the caller decides whether to re-exec into the
    venv interpreter (see re_exec_into_venv). Kept separate so dependency
    probing and the venv switch each have one job.
    """
    if not VENV_DIR.exists():
        print(f"创建虚拟环境: {VENV_DIR}", file=sys.stderr)
        # Route the venv module's stdout to our stderr so it never lands on the
        # MCP JSON-RPC channel (our stdout), which the host parses line-by-line.
        subprocess.check_call(
            [sys.executable, "-m", "venv", str(VENV_DIR)],
            stdout=sys.stderr,
        )
        print("虚拟环境创建完成", file=sys.stderr)

    venv_python = venv_python_path()
    if venv_python is None:
        print(f"错误: 虚拟环境 Python 不存在: {venv_bin_dir()}", file=sys.stderr)
        sys.exit(1)
    return str(venv_python)


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


def check_and_install_dependencies(venv_python):
    """Ensure mcp + pyyaml are importable inside the venv.

    Deps are probed via the venv interpreter itself (a subprocess), not via
    __import__ in this process: on Windows the parent process cannot load
    pywin32's pywintypes DLL from the venv, so __import__ here would falsely
    report mcp as missing and trigger a reinstall on every boot (which never
    fixes the DLL problem and prevents the server from initializing before the
    MCP host's timeout).
    """
    probe = subprocess.run(
        [venv_python, "-c", "import mcp, yaml"],
        capture_output=True,
    )
    if probe.returncode == 0:
        return

    print("正在安装缺失的依赖: mcp>=1.0.0, pyyaml>=6.0", file=sys.stderr)
    try:
        # Route pip's stdout to our stderr: pip prints "Collecting/Installing"
        # status to stdout, which is the MCP JSON-RPC channel and would corrupt
        # the protocol stream on first boot.
        subprocess.check_call(
            [venv_python, "-m", "pip", "install", "mcp>=1.0.0", "pyyaml>=6.0"],
            stdout=sys.stderr,
        )
        print("依赖安装完成", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"依赖安装失败: {e}", file=sys.stderr)
        sys.exit(1)

    # pywin32 (a transitive dep of mcp on Windows) ships pywintypes as a DLL
    # that is only placed on the DLL search path by a post-install script.
    # Without this step, `import mcp` -> `import pywintypes` fails even inside
    # the venv interpreter. Idempotent and quiet on subsequent boots.
    if IS_WINDOWS:
        postinstall = venv_bin_dir() / "pywin32_postinstall.py"
        if postinstall.exists():
            subprocess.run(
                [venv_python, str(postinstall), "-install"],
                capture_output=True,
            )
            print("pywin32 post-install 完成", file=sys.stderr)


_venv_python = ensure_venv()
check_and_install_dependencies(_venv_python)
# Binary deps (pywin32/pywintypes) only load under the venv interpreter —
# re-exec into it. No-op (falls through) once we're already inside the venv.
if sys.prefix == sys.base_prefix:
    re_exec_into_venv(_venv_python)

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from tools import (
    MemoryStore,
    memory_tool,
    MEMORY_SCHEMA,
    skill_manage,
    SKILL_MANAGE_SCHEMA,
)

app = Server("improve")

memory_store = MemoryStore()
memory_store.load_from_disk()


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="memory",
            description=MEMORY_SCHEMA["description"],
            inputSchema=MEMORY_SCHEMA["parameters"],
        ),
        Tool(
            name="skill_manage",
            description=SKILL_MANAGE_SCHEMA["description"],
            inputSchema=SKILL_MANAGE_SCHEMA["parameters"],
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "memory":
        result = memory_tool(
            action=arguments.get("action", ""),
            target=arguments.get("target", "memory"),
            content=arguments.get("content"),
            old_text=arguments.get("old_text"),
            store=memory_store,
        )
        return [TextContent(type="text", text=result)]

    elif name == "skill_manage":
        result = skill_manage(
            action=arguments.get("action", ""),
            name=arguments.get("name", ""),
            content=arguments.get("content"),
            file_path=arguments.get("file_path"),
            file_content=arguments.get("file_content"),
            old_string=arguments.get("old_string"),
            new_string=arguments.get("new_string"),
            replace_all=arguments.get("replace_all", False),
        )
        return [TextContent(type="text", text=result)]

    else:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False))]


def main():
    asyncio.run(run_server())


async def run_server():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    main()
