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


async def run_test() -> None:
    with tempfile.TemporaryDirectory(prefix="improve-mcp-") as temp_dir:
        project_dir = Path(temp_dir).resolve()
        server = StdioServerParameters(
            command=str(REPO_ROOT / "servers" / "launch_mcp"),
            cwd=str(REPO_ROOT),
            env={**os.environ, "IMPROVE_HOST": "codex"},
        )

        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                assert tool_names == {"memory", "skill_manage"}, tool_names

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
                    / ".codex"
                    / "improve-toolkit"
                    / "memories"
                    / "MEMORY.md"
                ).is_file()


if __name__ == "__main__":
    asyncio.run(run_test())
    print("MCP protocol smoke test passed")
