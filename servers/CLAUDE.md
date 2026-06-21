# servers Directory

MCP server implementation for 4-fire toolkit.

## Tools

| File | Purpose |
|------|---------|
| `utils.py` | Helper functions: `get_home()`, `atomic_replace()`, `tool_error()` |
| `memory_tool.py` | Persistent memory store (MEMORY.md, USER.md) |
| `skill_manager_tool.py` | Skill creation and management |

## Source Attribution

Tools adapted from [hermes-agent](https://github.com/NousResearch/hermes-agent):

| Local File | Remote Source |
|------------|---------------|
| `memory_tool.py` | [memory_tool.py](https://raw.githubusercontent.com/NousResearch/hermes-agent/refs/heads/main/tools/memory_tool.py) |
| `skill_manager_tool.py` | [skill_manager_tool.py](https://raw.githubusercontent.com/NousResearch/hermes-agent/refs/heads/main/tools/skill_manager_tool.py) |

## Sync Procedure

To sync from upstream:

```bash
# 1. Fetch remote files
curl -sL https://raw.githubusercontent.com/NousResearch/hermes-agent/refs/heads/main/tools/memory_tool.py > /tmp/memory_tool.py
curl -sL https://raw.githubusercontent.com/NousResearch/hermes-agent/refs/heads/main/tools/skill_manager_tool.py > /tmp/skill_manager_tool.py

# 2. Apply local adaptations (see below)

# 3. Test
cd servers && python3 test_tools.py
```

## Local Adaptations Checklist

When syncing, apply these modifications to maintain compatibility:

### Path & Framework

- Replace `from hermes_constants import get_hermes_home` → `from .utils import get_home`
- Replace `HERMES_HOME` → `get_home()` calls
- Replace `from tools.registry import registry, tool_error` → `from .utils import tool_error`
- Remove `registry.register()` blocks at end of files
- Change absolute imports (`from tools.xxx`) → relative imports (`from .xxx`)
- Remove `display_hermes_home()` calls in SKILL_MANAGE_SCHEMA description → use `get_home()`

### Security Patterns

- Remove `hermes_env` from `_MEMORY_THREAT_PATTERNS`
- Remove `skills_guard` import and `_security_scan_skill()` calls (simplified version)
- Remove `_GUARD_AVAILABLE` and `_guard_agent_created_enabled()` functions

### Feature Removals

- Remove `category` parameter from `_create_skill()` and `skill_manage()`
- Remove `_validate_category()` function
- Simplify `_resolve_skill_dir(name, category)` → `_resolve_skill_dir(name)`
- Remove category cleanup in `_delete_skill()`
- Remove `category` field from `SKILL_MANAGE_SCHEMA`

### Import Dependencies

- Add `import yaml` in skill_manager_tool.py (not imported from hermes)

### Schema Preservation

- **Keep all SCHEMA descriptions exactly as original** (except removed fields)
- Only modify path references: `$HOME/.hermes` → `get_home()` path

## Testing

```bash
cd servers && python3 test_tools.py
```
