#!/usr/bin/env python3
"""
MCP Server for 4-Fire Toolkit - stdio protocol

Exposes memory_tool and skill_manager_tool as MCP tools via stdio transport.

Usage:
    python mcp_server.py

Or add to Claude Desktop config:
    {
        "mcpServers": {
            "4-fire": {
                "command": "python3",
                "args": ["${CLAUDE_PLUGIN_ROOT}/servers/mcp_server.py"]
            }
        }
    }
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


def ensure_venv():
    if not VENV_DIR.exists():
        print(f"创建虚拟环境: {VENV_DIR}", file=sys.stderr)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        print(f"虚拟环境创建完成", file=sys.stderr)
    
    bin_dir = VENV_DIR / ("Scripts" if sys.platform == "win32" else "bin")
    venv_python = bin_dir / "python3"
    if not venv_python.exists():
        venv_python = bin_dir / "python"
    
    if not venv_python.exists():
        print(f"错误: 虚拟环境 Python 不存在: {venv_python}", file=sys.stderr)
        sys.exit(1)
    
    in_venv = sys.prefix != sys.base_prefix
    
    print(f"sys.prefix: {sys.prefix}", file=sys.stderr)
    print(f"sys.base_prefix: {sys.base_prefix}", file=sys.stderr)
    print(f"in_venv: {in_venv}", file=sys.stderr)
    
    if not in_venv:
        print(f"切换到虚拟环境: {venv_python}", file=sys.stderr)
        os.execv(str(venv_python), [str(venv_python), __file__])


def check_and_install_dependencies():
    required_packages = {
        "mcp": "mcp>=1.0.0",
        "yaml": "pyyaml>=6.0",
    }
    
    missing_packages = []
    
    for module_name, package_spec in required_packages.items():
        try:
            __import__(module_name)
        except ImportError:
            missing_packages.append(package_spec)
    
    if missing_packages:
        print(f"正在安装缺失的依赖: {', '.join(missing_packages)}", file=sys.stderr)
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install"] + missing_packages
            )
            print("依赖安装完成", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print(f"依赖安装失败: {e}", file=sys.stderr)
            sys.exit(1)


ensure_venv()
check_and_install_dependencies()

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
    skill_spec_tool,
    SKILL_SPEC_SCHEMA,
)
from session_search import (
    session_search_tool,
    SESSION_SEARCH_SCHEMA,
    session_history_tool,
    SESSION_HISTORY_SCHEMA,
)

app = Server("4-fire")

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
        Tool(
            name="skill_spec",
            description=SKILL_SPEC_SCHEMA["description"],
            inputSchema=SKILL_SPEC_SCHEMA["parameters"],
        ),
        Tool(
            name="session_search",
            description=SESSION_SEARCH_SCHEMA["description"],
            inputSchema=SESSION_SEARCH_SCHEMA["parameters"],
        ),
        Tool(
            name="session_history",
            description=SESSION_HISTORY_SCHEMA["description"],
            inputSchema=SESSION_HISTORY_SCHEMA["parameters"],
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

    elif name == "skill_spec":
        result = skill_spec_tool()
        return [TextContent(type="text", text=result)]

    elif name == "session_search":
        result = session_search_tool(
            query=arguments.get("query"),
            role_filter=arguments.get("role_filter"),
            limit=arguments.get("limit", 3),
        )
        return [TextContent(type="text", text=result)]

    elif name == "session_history":
        result = session_history_tool(
            session_id=arguments.get("session_id", ""),
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
