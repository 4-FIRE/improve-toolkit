# 4-Fire Toolkit MCP Server

MCP server exposing memory and skill management tools for Claude Code.

## Quick Start

```bash
# Run the MCP server
python3 mcp_server.py

# Test all tools
python3 test_tools.py
```

## Available Tools

| Tool | Description |
|------|-------------|
| `memory` | Persistent curated memory (MEMORY.md, USER.md) |
| `skill_manage` | Create, edit, patch, delete skills |
| `session_search` | Search past session transcripts |
| `session_history` | Get full session history |

## Source Attribution

This project incorporates tools from the [hermes-agent](https://github.com/NousResearch/hermes-agent) project by NousResearch:

- **memory_tool.py** - Synchronized from [hermes-agent memory_tool.py](https://raw.githubusercontent.com/NousResearch/hermes-agent/refs/heads/main/tools/memory_tool.py)
- **skill_manager_tool.py** - Synchronized from [hermes-agent skill_manager_tool.py](https://raw.githubusercontent.com/NousResearch/hermes-agent/refs/heads/main/tools/skill_manager_tool.py)

## License

See hermes-agent repository for original tool licenses.