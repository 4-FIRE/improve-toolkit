# improve-toolkit

让 Codex 与 Claude Code 共享长期记忆与工作方式的双宿主插件。它通过本地
stdio MCP 服务持久化项目知识，在 `SessionStart` 时注入用户偏好和项目记忆，并用
内置技能约束何时、如何整理可复用经验。

## 核心能力

- **持久记忆**：MCP 服务 `improve` 仅暴露 `memory` 工具，支持
  `add`、`replace`、`remove`，分别维护项目事实 `MEMORY.md` 与用户偏好
  `USER.md`。
- **会话上下文**：`session_context.py` 注入通用工作方式与临时工作区路径，
  `load_memory.py` 注入会话开始时的记忆快照。会话中写入立即落盘，但要到下一次
  SessionStart 才会进入提示词。
- **安全写入**：记忆更新使用跨进程锁和原子替换，并拒绝常见提示注入、密钥读取与
  外传载荷。
- **技能编写指导**：`improve` 负责筛选值得长期保留的事实和高价值流程候选；
  用户主动要求或接受具体方案后，`writing-great-skills` 才指导宿主用原生文件工具
  修改技能。本插件不提供技能管理 MCP 工具。
- **双宿主兼容**：技能、钩子、运行时状态和 MCP 实现由 Codex 与 Claude Code
  共用，并提供 POSIX 与 Windows 启动脚本。

## 环境要求

- Python 3.10+
- Codex CLI 或 Claude Code CLI
- 首次启动 MCP 服务时可联网安装锁定版本的 `mcp`

## 安装

### Codex

```bash
git clone https://github.com/4-FIRE/improve-toolkit.git
codex plugin marketplace add /absolute/path/to/improve-toolkit/codex-marketplace
codex plugin add improve-toolkit@improve-toolkit
```

启动新会话后使用 `/mcp`、`/hooks` 和 `/skills` 检查发现结果。首次启用钩子时
需要审阅信任提示；MCP 首启会创建虚拟环境，因此耗时可能更长。

本地 marketplace 默认从 GitHub 安装发布版本。开发改动需要先推送相应提交，再重新安装：

```bash
codex plugin remove improve-toolkit@improve-toolkit
codex plugin add improve-toolkit@improve-toolkit
```

### Claude Code

直接加载本地仓库：

```bash
git clone https://github.com/4-FIRE/improve-toolkit.git
claude --plugin-dir /absolute/path/to/improve-toolkit
```

或通过 marketplace 安装：

```text
/plugin marketplace add https://github.com/4-FIRE/improve-toolkit.git
/plugin install improve-toolkit@improve-toolkit
```

安装后使用 `/mcp` 检查服务状态。

## 工作原理

```text
hooks/hooks.json
  └─ scripts/run_hook
       ├─ session_context.py  → 通用工作方式与 workbench 路径
       └─ load_memory.py      → USER.md 与 MEMORY.md 的冻结快照

.mcp.json / .claude-plugin/plugin.json
  └─ servers/launch_mcp
       └─ mcp_server.py       → memory 工具
```

Codex 调用 `memory` 时必须传入绝对 `project_dir`；Claude Code 默认从
`CLAUDE_PROJECT_DIR` 解析项目。两个宿主最终写入同一个项目级目录。

## 运行时数据与迁移

| 数据 | 默认路径 |
| --- | --- |
| 项目记忆 | `.improve-toolkit/memories/` |
| 操作与审计日志 | `.improve-toolkit/logs/` |
| 临时执行文件 | `.improve-toolkit/workbench/` |

插件维护 `.improve-toolkit/.gitignore`，只忽略日志、workbench、锁文件和原子写入
临时文件；`memories/MEMORY.md` 与 `memories/USER.md` 仍可纳入版本控制。

升级后首次加载会将 `.claude/memories/` 和
`.codex/improve-toolkit/memories/` 中的旧条目去重合并到共享目录。共享文件一旦存在
即为唯一数据源；已验证同步的旧条目会被清理，无法读取或无法确认的内容会留在原处供
人工处理，避免恢复已主动删除的记忆。旧日志和 workbench 不迁移。

可用以下变量覆盖路径：

- `IMPROVE_HOST=codex|claude`
- `IMPROVE_PROJECT_DIR=/path/to/project`
- `IMPROVE_DATA_DIR=/path/to/data`
- `IMPROVE_MEMORY_DIR=/path/to/shared/memories`

## MCP 虚拟环境缓存

生产启动按 Python 身份、平台和 `servers/requirements.lock` 内容生成指纹，并在
用户缓存目录复用虚拟环境：

| 系统 | 默认缓存根目录 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\ImproveToolkit\Cache` |
| macOS | `~/Library/Caches/improve-toolkit` |
| Linux | `$XDG_CACHE_HOME/improve-toolkit`，未设置时为 `~/.cache/improve-toolkit` |

创建过程受文件锁保护，依赖验证后写入 `.improve-ready.json`。共享缓存不可用时回退到
`servers/.venv`。可通过 `IMPROVE_CACHE_DIR`、`IMPROVE_VENV_DIR` 或
`IMPROVE_PYTHON` 覆盖缓存根、虚拟环境或基础解释器。修改依赖时必须同步更新
`servers/requirements.lock` 与 `servers/pyproject.toml` 的精确版本。

## 开发与验证

```bash
# 标准库单元测试：钩子、路径、迁移和缓存解析
python scripts/run_tests.py

# memory 工具集成测试；必要时创建 servers/.venv
python servers/test_tools.py

# stdio MCP 初始化、工具发现与写入烟雾测试
servers/.venv/bin/python servers/test_mcp_protocol.py
```

仓库结构、编码约定、提交规范和发布版本同步要求见
[`AGENTS.md`](AGENTS.md)。Codex marketplace 位于
`codex-marketplace/.agents/plugins/marketplace.json`；Claude Code marketplace
位于 `.claude-plugin/marketplace.json`。
