#!/usr/bin/env python3
"""End-to-end smoke test for the stdio MCP launcher."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / "servers" / ".venv" / (
    "Scripts/python.exe" if os.name == "nt" else "bin/python"
)


async def run_test() -> None:
    with tempfile.TemporaryDirectory(prefix="improve-mcp-") as temp_dir:
        project_dir = Path(temp_dir).resolve()
        server = StdioServerParameters(
            command=str(REPO_ROOT / "servers" / "launch_mcp"),
            cwd=str(REPO_ROOT),
            env={
                **os.environ,
                "IMPROVE_HOST": "codex",
                "IMPROVE_PYTHON": str(VENV_PYTHON),
            },
        )

        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                print("Initializing MCP session...", flush=True)
                await session.initialize()
                print("Listing MCP tools...", flush=True)
                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                assert tool_names == {"memory", "memory_recall"}, tool_names

                print("Writing shared project memory...", flush=True)
                result = await session.call_tool(
                    "memory",
                    {
                        "action": "add",
                        "target": "memory",
                        "content": "MCP protocol smoke test",
                        "project_dir": str(project_dir),
                    },
                )
                payload = json.loads(result.content[0].text)
                assert payload["success"] is True, payload
                assert (
                    project_dir
                    / ".improve-toolkit"
                    / "memories"
                    / "MEMORY.md"
                ).is_file()

                print("Recalling task-relevant project memory...", flush=True)
                recalled = await session.call_tool(
                    "memory_recall",
                    {
                        "query": "MCP protocol smoke",
                        "project_dir": str(project_dir),
                    },
                )
                recall_payload = json.loads(recalled.content[0].text)
                assert recall_payload["success"] is True, recall_payload
                assert recall_payload["entries"][0]["content"] == "MCP protocol smoke test"


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(run_test(), timeout=60))
    print("MCP protocol smoke test passed")
