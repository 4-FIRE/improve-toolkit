# improve-toolkit

让 Codex 与 Claude Code 持续进化的双宿主插件。它通过本地 MCP 工具提供持久记忆和技能管理，并在会话启动时加载项目上下文，让编码助手能够累积经验、维护偏好并沉淀可复用工作流。

## 能力

- **MCP 服务 `improve`**：提供 `memory` 与 `skill_manage` 工具。
- **会话上下文**：`SessionStart` 钩子加载项目记忆、用户偏好和通用工作方式。
- **技能沉淀**：把验证过的复杂流程写成宿主可发现的 `SKILL.md`。
- **双宿主兼容**：同一份技能、钩子和 MCP 实现同时支持 Codex 与 Claude Code。

## 环境要求

- Python 3.10+
- Codex CLI 或 Claude Code CLI
- 首次启动 MCP 服务时需要联网安装 `mcp` 与 `pyyaml`

## Codex 安装

克隆仓库，然后把仓库内专用于 Codex 的 marketplace 目录注册为市场源：

```bash
git clone https://github.com/4-FIRE/improve-toolkit.git
codex plugin marketplace add /absolute/path/to/improve-toolkit/codex-marketplace
codex plugin add improve-toolkit@improve-toolkit
```

安装后启动一个新会话，并检查：

```text
/mcp
/hooks
/skills
```

首次使用钩子时，Codex 会要求审阅并信任插件钩子。MCP 首次启动可能需要更长时间，因为它会创建独立 Python 虚拟环境并安装依赖。

本地开发时仍注册同一个目录。该 marketplace 条目默认从 GitHub 安装发布版本；修改插件后应先推送对应提交，再重新安装：

```bash
codex plugin remove improve-toolkit@improve-toolkit
codex plugin add improve-toolkit@improve-toolkit
```

Codex 的标准 marketplace 文件位于 `codex-marketplace/.agents/plugins/marketplace.json`。它与 Claude Code 的 `.claude-plugin/marketplace.json` 分开维护，因为两个宿主的远程插件源格式不同。

## Claude Code 安装

直接加载本地插件：

```bash
git clone https://github.com/4-FIRE/improve-toolkit.git
claude --plugin-dir /absolute/path/to/improve-toolkit
```

或通过插件市场安装：

```text
/plugin marketplace add https://github.com/4-FIRE/improve-toolkit.git
/plugin install improve-toolkit@improve-toolkit
```

安装后使用 `/mcp` 检查服务状态。

## 运行时数据

数据按项目隔离，不会写进插件安装目录：

| 宿主 | 记忆、日志和临时工作区 | 新建技能 |
| --- | --- | --- |
| Codex | `.codex/improve-toolkit/` | `.agents/skills/` |
| Claude Code | `.claude/` | `.claude/skills/` |

可用环境变量覆盖默认位置：

- `IMPROVE_HOST=codex|claude`
- `IMPROVE_PROJECT_DIR=/path/to/project`
- `IMPROVE_DATA_DIR=/path/to/data`
- `IMPROVE_SKILLS_DIR=/path/to/skills`

## 开发与验证

```bash
# SessionStart、记忆加载和路径解析测试
python scripts/run_tests.py

# MCP 工具测试；首次运行会创建 servers/.venv
python servers/test_tools.py

# MCP stdio 端到端握手与工具调用测试
servers/.venv/bin/python servers/test_mcp_protocol.py
```

Codex 插件入口是 `.codex-plugin/plugin.json`，MCP 配置位于 `.mcp.json`；Claude Code 的入口保留在 `.claude-plugin/`。
