# improve-toolkit

让 Codex 与 Claude Code 持续进化的双宿主插件。它通过本地 MCP 工具提供持久记忆，并在会话启动时加载项目上下文。模型可以主动提出高价值技能候选，但只有用户同意后才会通过 `writing-great-skills` 创建或修改。

## 能力

- **MCP 服务 `improve`**：只提供持久化 `memory` 工具。
- **会话上下文**：`SessionStart` 钩子加载项目记忆、用户偏好和通用工作方式。
- **技能编写指导**：用户主动要求或同意具体提案后，由 `writing-great-skills` 指导使用宿主原生文件工具维护指定技能；详细门槛与授权规则见 `skills/improve/SKILL.md`。
- **双宿主兼容**：同一份技能、钩子和 MCP 实现同时支持 Codex 与 Claude Code。

## 环境要求

- Python 3.10+
- Codex CLI 或 Claude Code CLI
- 首次启动 MCP 服务时需要联网安装 `mcp`

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

数据按项目隔离，不会写进插件安装目录。Codex 与 Claude Code 共用同一个运行时根目录：

| 数据 | 路径 |
| --- | --- |
| 共享记忆 | `.improve-toolkit/memories/` |
| 共享日志 | `.improve-toolkit/logs/` |
| 共享临时工作区 | `.improve-toolkit/workbench/` |

插件会自动创建并维护 `.improve-toolkit/.gitignore`：忽略 `logs/`、
`workbench/`、记忆锁文件和原子写临时文件，但不会忽略
`memories/MEMORY.md` 与 `memories/USER.md`。记忆文件应随项目提交，以便克隆仓库后继续共享项目知识。

升级后首次加载记忆时，插件会把旧的 `.claude/memories/` 与
`.codex/improve-toolkit/memories/` 按条目去重合并到共享目录。共享目标文件一旦存在，
便成为唯一数据源。已在共享文件中验证存在的旧条目会从旧文件移除；旧文件全部同步后
会删除。无法读取、无法验证或未出现在共享文件中的条目保留在旧文件中，等待人工处理，
不会自动重新导入并复活已删除的共享记忆。
旧的宿主专用日志和 workbench 不迁移。

可用环境变量覆盖默认位置：

- `IMPROVE_HOST=codex|claude`
- `IMPROVE_PROJECT_DIR=/path/to/project`
- `IMPROVE_DATA_DIR=/path/to/data`
- `IMPROVE_MEMORY_DIR=/path/to/shared/memories`

## MCP 虚拟环境缓存

生产启动不会再把 `.venv` 建在按版本隔离的插件安装目录中。Codex 与
Claude Code 默认按 Python、平台和 `servers/requirements.lock` 指纹复用同一份
用户级缓存：

| 系统 | 默认缓存根目录 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\ImproveToolkit\Cache` |
| macOS | `~/Library/Caches/improve-toolkit` |
| Linux | `$XDG_CACHE_HOME/improve-toolkit`，未设置时为 `~/.cache/improve-toolkit` |

插件版本号不参与缓存键，因此只升级插件而 Python 与依赖未变化时不会重复创建
虚拟环境。缓存创建使用跨进程文件锁；依赖验证成功后才写入 `.improve-ready.json`。
用户缓存不可写时，会告警并回退到当前版本的 `servers/.venv`。

可用覆盖：

- `IMPROVE_CACHE_DIR=/path/to/cache`：覆盖用户缓存根目录。
- `IMPROVE_VENV_DIR=/path/to/existing-or-new-venv`：指定一个虚拟环境目录。
- `IMPROVE_PYTHON=/absolute/path/to/python`：指定基础解释器；两个宿主配置相同路径时可稳定复用。

仓库开发测试仍可使用 `servers/.venv`。修改 MCP 依赖时，应同步更新
`servers/requirements.lock` 与 `servers/pyproject.toml`，从而生成新的缓存指纹。

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
