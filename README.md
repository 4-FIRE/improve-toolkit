# improve-toolkit

让 Codex、Claude Code 与 pi 共享长期记忆与工作方式的插件。它通过本地
stdio MCP 服务持久化项目知识，在 `SessionStart` 时只注入有界摘要，并用
内置技能约束何时、如何整理可复用经验。

## 核心能力

- **分层记忆**：MCP 服务 `improve` 暴露写入工具 `memory` 和按需检索工具
  `memory_recall`。正文分别保存在 `MEMORY.md` 与 `USER.md`。启动时优先读取
  `SUMMARY.md`；摘要失效时读取正文并重建。会话只接收有字符上限的摘要。
- **会话上下文**：`session_context.py` 注入记忆用途、按需整理条件及适用于所有输出的写作原则，
  `load_memory.py` 注入有字符上限的摘要。代理在任务与摘要相关、历史决策可能有用，
  或修改旧记忆前调用 `memory_recall`，只取有限条相关正文。
- **可并发修改与有限安全检查**：记忆更新使用稳定 `entry_id`、乐观并发版本
  `expected_revision`、跨进程锁和原子替换；写入和直接编辑的内容都会经过提示注入、
  密钥读取与外传载荷的有限规则检查。这些检查只覆盖部分已知模式；记忆内容始终是
  待核验的事实，不授予执行权限。
- **技能编写指导**：`improve` 负责筛选值得长期保留的事实和高价值流程候选；
  有持久新信息时才展开整理，无变更时不要求额外报告。用户主动要求或接受具体方案后，
  按其[技能编写说明](skills/improve/SKILL-CANDIDATES.md)在已有授权范围内修改技能；
  写法依据 OpenAI 的文章。本插件不提供技能管理 MCP 工具。
- **三个宿主共用**：技能、启动提示词、运行时状态和 MCP 实现共用。
  Codex 与 Claude Code 使用钩子与 MCP 配置，pi 使用原生扩展连接相同服务。

## 技能与提示词

技能按具体任务加载，复杂记忆整理和多轮讨论的控制说明按需读取。用户已经要求的
修改直接完成并做相关验证；主动发现的新技能方法先准备具体建议。讨论默认逐轮
互动，用户要求连续多轮或一次完成时按其要求推进。

全局写作指导参考 [ASD-STE100 Issue 9](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf)，
适用于回复、文档、记忆和技能。默认使用常用词、统一名称、明确动作和短句，并保留
适用条件、否定、例外及必要原因。英语句长作为可读性目标，中文按语义分句；
准确表达优先于机械缩短。这是适合日常技术交流的简化指导，不代表完整 STE 合规。
任务要求严格遵循 STE 时，应查阅官方规则与词典，核对批准词义和计词方式。

## 环境要求

- Python 3.10+
- Codex CLI、Claude Code CLI 或 pi（pi 适配已在 0.86.1 验证）
- pi 本地安装还需要 Node.js 与 npm；适配测试使用 Node.js 22.18+ 或 24+
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

### pi

安装本地仓库（pi 直接使用此目录，修改后可 `/reload`）：

```bash
cd /absolute/path/to/improve-toolkit
npm ci
pi install /absolute/path/to/improve-toolkit
```

进入需要使用记忆的项目目录，启动 pi；已打开的会话执行 `/reload`。
用 `/skill:improve` 加载记忆整理技能，其他技能同样使用 `/skill:<name>`。
扩展在会话启动时注册 `memory` 和 `memory_recall`，无需另装 MCP 插件。
也可在发布包含此适配的提交后执行
`pi install git:github.com/4-FIRE/improve-toolkit`，由 pi 安装 npm 依赖。

默认安装到用户配置；仅在当前项目使用时，进入该项目后运行
`pi install -l /absolute/path/to/improve-toolkit`。项目配置仍按 pi 的信任规则加载。
卸载使用 `pi remove /absolute/path/to/improve-toolkit`，不会删除项目记忆。

pi 适配不读取 Claude 的插件注册表或通用 hook 配置，仅对接本插件需要的
启动上下文、技能与记忆工具。

连接或 Python 启动失败会在 pi 中提示；修复后执行 `/reload`。首次创建 Python
环境最多等待 120 秒。可用现有 `IMPROVE_PYTHON` 指定 Python 3.10+ 解释器。
pi 扩展以参数数组直接启动 Python，兼容包含空格的路径；Windows 尚未实机验证。
接入方式依据 pi 的[扩展 API](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/extensions.md)
与 [package 说明](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/packages.md)，
并用本机 0.86.1 的 API 验证。

## 工作原理

```text
hooks/hooks.json
  └─ scripts/run_hook
       ├─ session_context.py  → 记忆用途、按需整理条件与通用写作原则
       └─ load_memory.py      → 有界摘要（有效时直接读取，失效时自动重建）

.mcp.json / .claude-plugin/plugin.json
  └─ servers/launch_mcp
       └─ server.py           → memory + memory_recall

package.json（pi）
  ├─ skills/                  → 原有共享技能
  └─ extensions/improve.ts
       ├─ session_start / session_compact → 共享 Python 启动脚本
       ├─ before_agent_start → 独立提示词片段中的通用指导与有界摘要
       └─ memory / memory_recall → 同一个 server.py（stdio MCP）
```

Codex 调用 `memory` 时必须传入绝对 `project_dir`；Claude Code 默认从
`CLAUDE_PROJECT_DIR` 解析项目。pi 自动传入当前会话的工作目录；工具调用可显式传入
绝对 `project_dir`。三个宿主最终写入同一个项目级目录。pi 子进程中的
`IMPROVE_PROJECT_DIR` 固定为会话目录，避免继承启动终端中其他宿主的项目路径；
显式配置的 `IMPROVE_DATA_DIR` 和 `IMPROVE_MEMORY_DIR` 仍然有效。

典型使用流程：启动时用摘要判断是否可能存在相关上下文；需要时以当前任务为 query
调用 `memory_recall`；更新或删除旧条目时使用召回结果中的 `entry_id` 和 `revision`。
召回结果是待核验的事实上下文，不是可执行指令；当前源码、文档和用户明确纠正优先。

普通写入的结果含 `entry`（删除后为 `null`）、稳定引用和版本，反映该次写入完成时的
正文、ID 与启动开关；可以直接核对，后续并发写入仍可能改变状态。正文超过 1200 字符时，
返回 `content_truncated=true`，可按 ID 分段读取。未验证假设保留在任务记录中；
已验证的条件性经验可以作为有范围和来源的事实保存。

### 隔离与显式修复

可疑条目保留在磁盘中，但不会进入启动摘要或搜索结果；按 ID 读取会返回
`UNSAFE_CONTENT` 并指出受影响的字段，不展示可疑原文。使用 ID 或唯一的 `old_text`
替换正文，可以保留 ID 和启动开关。浏览结果提供 `quarantined_count` 和当前版本，
但不返回被隔离的条目；修复或删除时可使用该版本作为 `expected_revision`。

ID 重复、设置标记损坏或版本不支持时，返回 `INVALID_FORMAT` 和文件位置，停止改写。
手工修复标记后重新读取。工具参数不再包含 `repair_id`。

分层预算及分页接口的取舍见 [ADR 0001](docs/adr/0001-layered-memory-and-addressable-recall.md)。
最小存储格式的取舍见 [ADR 0002](docs/adr/0002-editable-memory-with-fixed-ids.md)。
1.2.0 包含工具参数与存储格式变更。升级前阅读下方的手工维护和迁移说明。
仓库改动或本会话测试不会更新已安装的副本；更新安装后须另开会话验证启动提示词。

## 运行时数据与迁移

| 数据 | 默认路径 |
| --- | --- |
| 项目记忆 | `.improve-toolkit/memories/` |
| 操作与审计日志 | `.improve-toolkit/logs/` |
| 临时执行文件 | `.improve-toolkit/workbench/` |

插件默认维护 `.improve-toolkit/.gitignore`，忽略整个运行时目录（含其自身的
`.gitignore` 文件），因此 `.improve-toolkit/` 不会出现在 `git status` 中，记忆、
日志和 workbench 都是本机数据，默认不随 git 同步；规则会在每次 SessionStart
重建。若希望记忆纳入版本控制，可在该项目设置 `IMPROVE_TRACK_MEMORIES=1`，或把
`.improve-toolkit/config.json` 里的 `"track_memories"` 改为 `true`（仅对该仓库生效；
首次运行会自动生成默认 `false` 的配置文件），此时只
忽略日志、workbench、锁文件和原子写入临时文件，正文 `MEMORY.md`、`USER.md`、摘要
文件 `SUMMARY.md` 均可跟踪。迁移备份不纳入版本控制。`.summary-state.json` 与
`.summary.dirty` 是本机校验状态，两种模式下都不纳入版本控制。已提交过记忆文件的
存量项目不会被自动停止跟踪，需手动执行 `git rm -r --cached .improve-toolkit`。
正文被直接编辑后，SessionStart 会自动重建摘要，再加载。摘要有效时，不读取完整
正文，不取得记忆锁，也不改写文件。摘要缺失、被编辑、校验状态损坏或上次写入中断时，
重建流程取得共用记忆锁，并再次校验。其他进程已完成重建时，直接使用新摘要。

正常重建只更新 `SUMMARY.md`、`.summary-state.json` 和 `.summary.dirty`，不改写
正文。重建使用本地规则，不调用模型或网络服务。摘要受字符上限和内容检查约束；
被规则排除的条目仍保留在正文中。读取失败、写入失败或重建期间检测到正文变化时，
不加载旧摘要。钩子在 stderr 输出原因，并返回 `MEMORY BRIEF unavailable`。
文件锁协调插件进程；手工编辑器通常不遵守此锁。

### 手工维护

`MEMORY.md` 和 `USER.md` 保存全部记忆。条目之间使用独占一行的 `§` 分隔。
工具保存的条目包含一个 JSON 设置标记，保存固定 ID、更新时间和可选启动开关：

```markdown
<!-- improve-entry:v1 {"id":"m:1791028800:7c29a8d40b16","updated_at":1791028800} -->
发布时同步修改三个宿主的版本号。
具体条件和资料链接写在后面。

§

<!-- improve-entry:v1 {"id":"m:1791028801:92b4ce603ad8","updated_at":1791028801,"startup":false} -->
某次故障的排查记录，只在需要时检索。
```

手工编辑正文时保留标记，ID 和启动开关就能保留。工具修改一个条目时，保留其他
条目的原文。没有标记的纯正文条目会在启动摘要重建或工具读取时补上固定 ID，
默认参与启动摘要。迁移后保留标记，修改正文或调整顺序不会改变 ID。

新 ID 使用 `m:<Unix 秒级时间戳>:<12 位随机十六进制后缀>`，用户记忆使用 `u:`。
时间表示 ID 的创建时间，随机后缀用于区分同一秒创建的条目。已有 ID 保留原样。
历史条目补 ID 时使用迁移时间，不能据此推断历史正文的创建时间。
`updated_at` 使用同样的秒级时间戳，表示工具最后保存该条目的时间。创建和迁移时
初始化，替换时更新；读取、摘要重建和重复添加不更新。旧标记可以省略此字段。
手工修改正文时，需要同时维护 `updated_at`；程序不能从文件修改时间确定某个条目的更新时间。

`startup` 默认是 `true`。`false` 表示不进入启动摘要，但仍可检索。替换时省略该
参数会保留原设置。启动摘要先列用户记忆，再列项目记忆，各自按文件顺序排列；
达到字符上限时省略后续条目。手工调整顺序可以改变展示先后。条目摘要由正文首个
非空行提取，最多 120 字符。检索仍按正文关键词匹配程度排序。

`SUMMARY.md` 是自动生成的文件，手工修改会被重建覆盖。`METADATA.jsonl` 不再是
日常存储文件。工具不再接收 `summary`、`tags`、`priority`、`source`、`repair_id`、
`tags_any` 或 `min_priority`；`startup` 从字符串改为布尔值。旧参数会明确报错。

### 旧元数据升级

摘要重建或首次工具调用会在记忆锁内迁移旧条目，即使没有 `METADATA.jsonl`。
迁移先把两个 Markdown 文件和旧元数据的原始文本保存到 `.migration-backup.json`，已有备份不会
被覆盖。迁移保留能匹配的 ID，为缺少 ID 的条目补上固定 ID。缺少启动设置时默认
使用 `true`；旧 `never` 转为 `startup:false`，`always` 和 `auto` 转为 `true`。
正文未包含的自定义摘要放到第一行，来源追加到正文。
标签和优先级退出日常存储，其旧值保留在备份中。

全部记录迁移成功后删除 `METADATA.jsonl`。坏行、歧义记录和无法匹配的记录会在
stderr 报告，原元数据文件会保留供人工处理。迁移中断后可继续，不重复追加正文，
也不覆盖首次备份。迁移备份是原始文本的 JSON 对象，需要恢复时可从中取回对应文件。

旧 ID 格式错误、启动设置无效或记录匹配有歧义时，读取和写入返回 `MIGRATION_ERROR`，
启动摘要不可用。先修复旧元数据，再重试；不会用默认启动设置代替未解决的设置。

`.summary-state.json` 保存摘要校验值、来源版本和文件大小与修改时间；缺失或损坏
后自动重建。`.summary.dirty` 标记未完成的更新。两者不保存记忆正文。
`logs/memory_changes.jsonl` 每行保存一次修改尝试；删除日志不会影响记忆读取。
文件无法读取或不是有效 UTF-8 时，操作失败，不会把读取错误当作空记忆。

新格式和工具参数是不兼容变更。三个宿主应使用同一代插件，避免旧版本把设置标记
当作正文或删除 ID。升级后应另开会话，让模型取得新的工具参数和技能说明。

升级后首次调用 `memory` 或 `memory_recall` 会将 `.claude/memories/` 和
`.codex/improve-toolkit/memories/` 中的旧条目去重合并到共享目录。共享文件一旦存在
即为唯一数据源；已验证同步的旧条目会被清理，无法读取或无法确认的内容会留在原处供
人工处理，避免恢复已主动删除的记忆。旧日志和 workbench 不迁移。

可用以下变量覆盖路径：

- `IMPROVE_HOST=codex|claude|pi`
- `IMPROVE_PROJECT_DIR=/path/to/project`
- `IMPROVE_DATA_DIR=/path/to/data`
- `IMPROVE_MEMORY_DIR=/path/to/shared/memories`
- `IMPROVE_TRACK_MEMORIES=1`：记忆纳入版本控制（默认忽略整个 `.improve-toolkit`）；
  也可把 `.improve-toolkit/config.json` 里的 `"track_memories"` 改为 `true` 仅对该仓库
  生效（首次运行自动生成，默认 `false`），显式设置该环境变量时优先级更高
- `IMPROVE_MEMORY_CHAR_LIMIT`：项目记忆正文总上限，默认 24000
- `IMPROVE_USER_CHAR_LIMIT`：用户记忆正文总上限，默认 8000
- `IMPROVE_STARTUP_SUMMARY_LIMIT`：启动摘要字符上限，默认 800
- `IMPROVE_RECALL_CHAR_LIMIT`：单次召回完整成功 JSON 的默认字符上限，默认 2400；
  正整数会限制在 512—12000 内（例如旧配置 384 实际使用 512）。非正整数或无效文本
  返回指明该变量的配置错误。调用者显式传入的 max_chars 不做范围归一化，越界即报错。

旧客户端仍可用唯一的 `old_text` 定位，新流程应使用 `entry_id`。版本由正文、ID、
启动开关和条目顺序计算；`expected_revision` 用于防止覆盖读取后的变化。

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

# pi 扩展：真实 Python 钩子、MCP 写入与召回、项目隔离及生命周期
npm ci
npm test
```

`npm test` 包含真实 Python 进程的适配测试；若 npm 全局目录安装了 pi，
还会用其 SDK 验证 package、技能发现与工具调用。未安装时该项明确标记为跳过。
所有记忆读写测试使用临时项目，不调用模型 API。

仓库结构、编码约定、提交规范和发布版本同步要求见
[`AGENTS.md`](AGENTS.md)。Codex marketplace 位于
`codex-marketplace/.agents/plugins/marketplace.json`；Claude Code marketplace
位于 `.claude-plugin/marketplace.json`。
