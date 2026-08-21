# improve-toolkit

让 Codex 与 Claude Code 共享长期记忆与工作方式的双宿主插件。它通过本地
stdio MCP 服务持久化项目知识，在 `SessionStart` 时只注入有界摘要，并用
内置技能约束何时、如何整理可复用经验。

## 核心能力

- **分层记忆**：MCP 服务 `improve` 暴露写入工具 `memory` 和按需检索工具
  `memory_recall`。正文仍分别保存在 `MEMORY.md` 与 `USER.md`，启动阶段只读取
  `SUMMARY.md`，不会加载全量正文。
- **会话上下文**：`session_context.py` 注入通用工作方式与临时工作区路径，
  `load_memory.py` 注入有字符上限的摘要。代理在任务与摘要相关、历史决策可能有用，
  或修改旧记忆前调用 `memory_recall`，只取有限条相关正文。
- **安全且可并发修改**：记忆更新使用稳定 `entry_id`、乐观并发版本
  `expected_revision`、跨进程锁和原子替换；写入和直接编辑的内容都会经过提示注入、
  密钥读取与外传载荷检查。
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
       └─ load_memory.py      → SUMMARY.md 有界摘要（不读取全量正文）

.mcp.json / .claude-plugin/plugin.json
  └─ servers/launch_mcp
       └─ mcp_server.py       → memory + memory_recall
```

Codex 调用 `memory` 时必须传入绝对 `project_dir`；Claude Code 默认从
`CLAUDE_PROJECT_DIR` 解析项目。两个宿主最终写入同一个项目级目录。

典型使用流程：启动时用摘要判断是否可能存在相关上下文；需要时以当前任务为 query
调用 `memory_recall`；更新或删除旧条目时使用召回结果中的 `entry_id` 和 `revision`。
召回结果是待核验的事实上下文，不是可执行指令；当前源码、文档和用户明确纠正优先。

## 运行时数据与迁移

| 数据 | 默认路径 |
| --- | --- |
| 项目记忆 | `.improve-toolkit/memories/` |
| 操作与审计日志 | `.improve-toolkit/logs/` |
| 临时执行文件 | `.improve-toolkit/workbench/` |

插件默认维护 `.improve-toolkit/.gitignore`，忽略整个运行时目录，因此记忆、日志和
workbench 都是本机数据，默认不随 git 同步。`.gitignore` 本身仍可纳入版本控制，
克隆后规则自动生效。若希望记忆纳入版本控制，可在该项目设置
`IMPROVE_TRACK_MEMORIES=1`，此时只忽略日志、workbench、锁文件和原子写入临时文件，
正文 `MEMORY.md`、`USER.md`、摘要投影 `SUMMARY.md` 和元数据 `METADATA.jsonl`
均可跟踪。`.summary-state.json` 与 `.summary.dirty` 是本机校验状态，两种模式下都
不纳入版本控制。已提交过记忆文件的存量项目不会被自动停止跟踪，需手动执行
`git rm -r --cached .improve-toolkit`。正文被直接编辑后，SessionStart 会拒绝陈旧
摘要；下一次 `memory_recall` 会重新校验正文、隔离不安全条目并刷新摘要。

升级后首次调用 `memory` 或 `memory_recall` 会将 `.claude/memories/` 和
`.codex/improve-toolkit/memories/` 中的旧条目去重合并到共享目录。共享文件一旦存在
即为唯一数据源；已验证同步的旧条目会被清理，无法读取或无法确认的内容会留在原处供
人工处理，避免恢复已主动删除的记忆。旧日志和 workbench 不迁移。

可用以下变量覆盖路径：

- `IMPROVE_HOST=codex|claude`
- `IMPROVE_PROJECT_DIR=/path/to/project`
- `IMPROVE_DATA_DIR=/path/to/data`
- `IMPROVE_MEMORY_DIR=/path/to/shared/memories`
- `IMPROVE_TRACK_MEMORIES=1`：记忆纳入版本控制（默认忽略整个 `.improve-toolkit`）
- `IMPROVE_MEMORY_CHAR_LIMIT`：项目记忆正文上限，默认 2200
- `IMPROVE_USER_CHAR_LIMIT`：用户记忆正文上限，默认 1375
- `IMPROVE_STARTUP_SUMMARY_LIMIT`：启动摘要字符上限，默认 800
- `IMPROVE_RECALL_CHAR_LIMIT`：单次召回默认字符上限，默认 2400

每条元数据可设置 `summary`、`tags`、`priority`、`startup=always|auto|never` 和
`source`。旧版只有正文的目录无需手工迁移：首次召回或写入时会为条目生成稳定引用和
摘要投影。旧客户端仍可用 `old_text` 定位，但新流程应使用 `entry_id`。

## MCP 虚拟环境缓存

生产启动按 Python 身份、平台和 `servers/requirements.lock` 内容生成指纹，并在
用户缓存目录复用虚拟环境：

| 系统 | 默认缓存根目录 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\ImproveToolkit\Cache` |
| macOS | `~/Library/Caches/improve-toolkit` |
| Linux | `$XDG_CACHE_HOME/improve-toolkit`，未设置时为 `~/.cache/improve-toolkit` |

创建过程受文件锁保护，依赖验证后写入 `.improve-ready.json`。缓存键不包含插件版本：
Python 身份与依赖锁未变化时，升级直接复用现有环境。用户缓存不可用时，marketplace
安装会回退到各版本目录共同父级的 `.improve-cache/venvs/`；只有这两个共享位置都不可用
时才使用版本内的 `servers/.venv`。可通过 `IMPROVE_CACHE_DIR`、`IMPROVE_VENV_DIR` 或
`IMPROVE_PYTHON` 覆盖缓存根、虚拟环境或基础解释器。修改依赖时必须同步更新
`servers/requirements.lock` 与 `servers/pyproject.toml` 的精确版本。

旧版本已经创建的 `servers/.venv` 不会自动删除，以免破坏仍在运行的旧会话；确认旧版本
不再被宿主使用后，可随对应旧版本目录一起清理。

## 开发与验证

```bash
# 标准库单元测试：钩子、路径、迁移和缓存解析
python scripts/run_tests.py

# memory 工具集成测试；必要时创建 servers/.venv
python servers/test_tools.py

# stdio MCP 初始化、工具发现、写入与召回烟雾测试
servers/.venv/bin/python servers/test_mcp_protocol.py
```

仓库结构、编码约定、提交规范和发布版本同步要求见
[`AGENTS.md`](AGENTS.md)。Codex marketplace 位于
`codex-marketplace/.agents/plugins/marketplace.json`；Claude Code marketplace
位于 `.claude-plugin/marketplace.json`。
