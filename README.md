# improve-toolkit

让 Codex、Claude Code 与 pi 共享长期记忆与工作方式的插件。它通过本地
stdio MCP 服务持久化项目知识，在 `SessionStart` 时只注入有界摘要，并用
内置技能约束何时、如何整理可复用经验。

## 核心能力

- **分层记忆**：MCP 服务 `improve` 暴露写入工具 `memory` 和按需检索工具
  `memory_recall`。正文仍分别保存在 `MEMORY.md` 与 `USER.md`，启动阶段只读取
  `SUMMARY.md`，不会加载全量正文。
- **会话上下文**：`session_context.py` 注入本插件的记忆用途与按需整理条件，
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
       ├─ session_context.py  → 记忆用途与按需整理条件
       └─ load_memory.py      → SUMMARY.md 有界摘要（不读取全量正文）

.mcp.json / .claude-plugin/plugin.json
  └─ servers/launch_mcp
       └─ server.py           → memory + memory_recall

package.json（pi）
  ├─ skills/                  → 原有共享技能
  └─ extensions/improve.ts
       ├─ session_start / session_compact → 共享 Python 启动脚本
       ├─ before_agent_start → 独立提示词片段中的记忆说明与有界摘要
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
内容与元数据；可以直接核对，后续并发写入仍可能改变状态。正文超过 1200 字符时，
返回 `content_truncated=true`，可按 ID 分段读取。未验证假设保留在任务记录中；
已验证的条件性经验可以作为有范围和来源的事实保存。

### 隔离与显式修复

可疑条目保留在磁盘中，但不会进入启动摘要或搜索结果；按 ID 读取会返回
`UNSAFE_CONTENT` 并指出受影响的字段，不回显可疑原文。`replace` 省略 source 或 tags
表示保留旧值，只替换正文不会清除这些字段的污染。显式传入干净的 source、tags，
或用 `source=""`、`tags=[]` 清空它们，可以保留 ID 和其他元数据完成修复。

若 ID 本身受污染，使用已知选择器（必要时用唯一的 `old_text`），在 `replace` 中
显式传 `repair_id=true`，工具会生成新 ID，并保留未覆盖的其他元数据；后续使用返回的
新 ID。这个选项仅用于受污染的 ID，仍检查最终条目的所有字段，不会自动清除来源或标签。
隔离条目无法从索引中取得 ID，但浏览结果仍提供当前 `revision`，修复时可作为
`expected_revision` 使用。删除仍是另一种选择，不是唯一恢复手段。

### 查找与分页

`memory_recall` 默认使用 `mode=relevant`，按英文词和中文连续双字匹配关键词，
不保证同义表达命中。空搜索结果不代表记忆不存在；需要时用下面两种模式补充查找：

| 模式 | 参数 | 返回内容 |
| --- | --- | --- |
| `relevant`（默认） | `query` | 始终含 `content`；过长时返回正文前缀，标记 `content_truncated=true` |
| `browse` | 省略 `query`，可指定 `target`、标签、优先级 | 带稳定引用的摘要索引 |
| `get` | `entry_id`，可指定 `target` | 某一条记忆的正文和元数据，长正文按段返回 |

搜索或浏览返回 `next_offset` 时，下一页传入该值作为 `offset`，保持模式、查询和
筛选条件不变。搜索返回正文前缀时，用该条目的 `entry_id` 切换到 `mode=get`，省略
query、搜索 offset 和筛选条件，把 `next_content_offset` 作为 `content_offset`
接着读正文；后续 get 沿用相同条目引用。每次续读同时传入上次返回的 `revision`
作为 `expected_revision`。搜索结果可同时给出两种 next 值，分别续读结果列表和当前正文。
发生 `REVISION_CONFLICT` 时从第一页重新开始；相应的 `next_*` 为 `null` 表示读完。
后续正文片段的 `content_truncated` 仍为 `true`，因为每段只是整条正文的一部分。
offset 大于匹配条数或正文长度时返回 `INVALID_REQUEST`；恰好等于末尾时允许返回空页。
分页保持连续排序窗口，不跳过装不下的条目。因此返回条数可能少于 limit，即使后面
还有单独能装下的短条目；此时使用 `next_offset` 继续。
分页版本只用于防止跨版本拼接；浏览完所有页也不等于核验了所有事实。

`max_chars` 现在约束完整的成功 JSON 返回文本，包括正文、元数据和结构；
`returned_chars` 是同一文本的字符数，不包含宿主额外的 MCP 包装。默认 2400，允许
512—12000；512 是参数下限，不保证任意条目都能在该预算内读取。正文分段至少返回
256 字符，剩余不足 256 时须能返回整个尾段；预算按 JSON 转义后的实际长度计算。
预算放不下一条索引摘要，或必要元数据加有效正文片段时，返回 `BUDGET_TOO_SMALL`，
并用 `required_max_chars` 给出该次请求所需的预算，不会静默跳过条目或返回极小片段。
工具保留 `NOT_FOUND` 与 `UNSAFE_CONTENT` 的区别，
避免把被隔离的记忆误认为已删除。

### 兼容性

现有 `memory` 操作和不指定模式的关键词查询仍可使用；`query` 仅在关键词模式必需。
旧客户端需要适应以下返回约定：`max_chars` 从正文预算改为完整 JSON 预算，最小值
从 128 调整为 512；搜索仍返回 `content`，但长正文可能截断，客户端须检查
`content_truncated` 并用 `get` 续读。只有 browse 返回无正文的 `detail=summary` 视图。
旧的 `returned_chars` 不能与新版按相同口径比较。

新写入的每个标签最多 32 字符、最多 12 个标签，source 最多 256 字符。旧记忆中的
较长元数据保留在文件中，工具显示受限内容并标记 `metadata_truncated=true`，不静默
改写旧来源。正文存储预算增加不会增加启动摘要或单次返回的预算；旧正文无需迁移。

分层预算及分页接口的取舍见 [ADR 0001](docs/adr/0001-layered-memory-and-addressable-recall.md)。
上述 max_chars 口径和下界是不兼容变更。若按语义化版本发布且不提供旧接口兼容层，
应同步提升三个宿主清单的主版本，而不是视作 patch。
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
投影 `SUMMARY.md` 和元数据 `METADATA.jsonl` 均可跟踪。`.summary-state.json` 与
`.summary.dirty` 是本机校验状态，两种模式下都不纳入版本控制。已提交过记忆文件的
存量项目不会被自动停止跟踪，需手动执行 `git rm -r --cached .improve-toolkit`。
正文被直接编辑后，SessionStart 会拒绝陈旧摘要；下一次 `memory_recall` 会重新校验
正文、隔离不安全条目并刷新摘要。

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
