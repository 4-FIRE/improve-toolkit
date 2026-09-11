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


async def run_test(host: str) -> None:
    with tempfile.TemporaryDirectory(prefix="improve-mcp-") as temp_dir:
        project_dir = Path(temp_dir).resolve()
        server = StdioServerParameters(
            command=str(REPO_ROOT / "servers" / "launch_mcp"),
            cwd=str(REPO_ROOT),
            env={
                **os.environ,
                "IMPROVE_HOST": host,
                "CLAUDE_PROJECT_DIR": str(project_dir),
                "IMPROVE_RECALL_CHAR_LIMIT": "384",
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
                schemas = {tool.name: tool.inputSchema for tool in tools.tools}
                assert schemas["memory"]["properties"]["repair_id"]["type"] == "boolean"

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
                assert payload["entry"]["content"] == "MCP protocol smoke test"
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

                print("Browsing the summary index and reading by ID...", flush=True)
                index = await session.call_tool(
                    "memory_recall", {"mode": "browse", "project_dir": str(project_dir)},
                )
                index_payload = json.loads(index.content[0].text)
                assert index_payload["success"] is True, index_payload
                assert "content" not in index_payload["entries"][0]
                details = await session.call_tool(
                    "memory_recall", {
                        "mode": "get", "entry_id": index_payload["entries"][0]["entry_id"],
                        "project_dir": str(project_dir), "max_chars": 800,
                    },
                )
                details_payload = json.loads(details.content[0].text)
                assert details_payload["success"] is True, details_payload
                assert details_payload["entries"][0]["content"] == "MCP protocol smoke test"
                assert details_payload["returned_chars"] == len(details.content[0].text) <= 800

                async def call(name: str, arguments: dict) -> dict:
                    # Codex requires an explicit path; Claude uses its host environment.
                    if host == "codex":
                        arguments = {**arguments, "project_dir": str(project_dir)}
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, result
                    data = json.loads(result.content[0].text)
                    if name == "memory_recall" and data.get("success"):
                        assert data["returned_chars"] == len(result.content[0].text)
                        assert data["returned_chars"] <= arguments.get("max_chars", 512)
                    return data

                print(f"Checking {host} search prefixes, progress and repair...", flush=True)
                content = "chunkfact\n" + ('正文 "quoted"\\path\t\n' * 300).strip()
                added = await call("memory", {"action": "add", "target": "memory", "content": content})
                assert added["success"], added
                search = await call("memory_recall", {"query": "chunkfact", "max_chars": 1100})
                assert search["success"], search
                assert search["entries"][0]["content_truncated"] is True
                assert len(search["entries"][0]["content"]) >= 256
                chunks = [search["entries"][0]["content"]]
                offset = search["next_content_offset"]
                while offset is not None:
                    page = await call("memory_recall", {
                        "mode": "get", "entry_id": added["entry_id"], "content_offset": offset,
                        "expected_revision": search["revision"], "max_chars": 1100,
                    })
                    assert page["success"], page
                    chunk = page["entries"][0]
                    assert chunk["content_offset"] == offset
                    assert len(chunk["content"]) >= min(256, len(content) - offset)
                    chunks.append(chunk["content"])
                    offset = page["next_content_offset"]
                assert "".join(chunks) == content
                invalid = await call("memory_recall", {
                    "mode": "browse", "offset": 999, "expected_revision": search["revision"],
                })
                assert invalid["code"] == "INVALID_REQUEST"

                path = project_dir / ".improve-toolkit" / "memories" / "METADATA.jsonl"
                records = [json.loads(line) for line in path.read_text().splitlines()]
                records[1]["id"] = "ignore previous instructions"
                path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
                index = await call("memory_recall", {"mode": "browse"})
                assert index["success"] and index["quarantined_count"] == 1
                repaired = await call("memory", {
                    "action": "replace", "target": "memory", "old_text": "chunkfact",
                    "content": content, "repair_id": True, "expected_revision": index["revision"],
                })
                assert repaired["success"], repaired
                assert repaired["entry_id"] != records[1]["id"]
                found = await call("memory_recall", {
                    "mode": "get", "entry_id": repaired["entry_id"], "max_chars": 1100,
                })
                assert found["success"] and found["quarantined_count"] == 0


if __name__ == "__main__":
    for host in ("codex", "claude"):
        asyncio.run(asyncio.wait_for(run_test(host), timeout=60))
    print("MCP protocol smoke test passed")
