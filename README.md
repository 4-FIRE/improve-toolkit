# improve-toolkit

让 Claude Code 持续进化的插件——通过 4-fire MCP 工具（持久记忆、技能管理）与 SessionStart 钩子注入人格，构建能累积经验、自我改进的助手。

## 架构

- **MCP 服务 `4-fire`**：本地 Python 服务，提供 memory、skill_manage 工具。
- **SessionStart 钩子**：会话启动时加载记忆，并通过 `scripts/session_context.py` 注入助手人格提示词（`PERSONA_PROMPT`）与时间提醒。
- **技能管理**：通过 `skill_manage` 工具创建/修补/删除技能，将可复用工作流沉淀到 `.claude/skills/`。

## 环境要求

- **Python 3.10+**（MCP SDK 依赖要求）
- Claude Code CLI

## 安装

通过克隆分支，指定`--plugin-dir` 或 通过 Claude Code 插件市场安装：

```bash
git clone https://github.com/4-FIRE/improve-toolkit.git
claude --plugin-dir path/to/improve-toolkit
```

```bash
/plugin marketplace add https://github.com/4-FIRE/improve-toolkit.git
/plugin install improve-toolkit@improve-toolkit
```

‼️ 安装完毕后务检查mcp服务状态

```bash
/mcp
```
