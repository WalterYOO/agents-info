---
name: agents-info
description: 列出本机所有 Claude Code 会话（session）的实时名单与详情：名字、状态、目录、启动时间、用户轮次、会话标题、首条、最近一条消息、ECC 任务摘要。当用户问“有哪些 session / 会话在跑”“某个会话在聊什么”“上次那个做 X 的会话是哪次”，想找回旧会话，或在 /resume、SendMessage、跨会话交接之前需要辨认会话时使用。
allowed-tools: Bash(python3:*), Bash(git:*)
---

# agents-info

把本机正在运行和历史遗留的 Claude Code 会话汇总成一张表。数据全部来自本地文件，只读、不联网、不改任何会话。

## 快速使用

```bash
# 默认 brief：只列 名称 / 状态 / 启动 / 会话标题
python3 "${CLAUDE_SKILL_DIR}/scripts/sessions_table.py"

# brief 子命令：与默认行为相同
python3 "${CLAUDE_SKILL_DIR}/scripts/sessions_table.py" brief

# detail：全量表格（ID、目录、轮次、最后活动、首条、最近一条、ECC 任务）
python3 "${CLAUDE_SKILL_DIR}/scripts/sessions_table.py" detail

# detail + 名称（也支持短 ID / 全 ID / 前缀）：单个会话详情
python3 "${CLAUDE_SKILL_DIR}/scripts/sessions_table.py" detail pocketgo-09
```

默认输出一张 4 列的 Markdown 表，末尾附本会话名字和接管提示。直接把输出原样呈现给用户，不要改写、补算或删列。

用户要机器可读格式、或需要未截断的完整字段时，在任意子命令后加 `--json`：

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/sessions_table.py" detail --json
```

## 输出的列

### 默认 / brief

| 列 | 含义 |
|---|---|
| 名称 | `SendMessage` / `--resume` 使用的会话名；`★` 表示当前会话 |
| 状态 | `busy` / `idle`；进程已退出显示“已退出”；`·本` 表示当前会话 |
| 启动 | 会话启动时间（本地时区） |
| 会话标题 | Claude Code 自动生成的会话标题（`ai-title` 记录的 `aiTitle`）；新会话尚未生成时显示 `—` |

### detail 追加

| 列 | 含义 |
|---|---|
| ID | sessionId 前 8 位，可用于 `--resume` |
| 目录 | 会话的工作目录（过长时保留末尾路径） |
| 轮次 | 真实用户消息条数（已排除 tool_result、系统注入、斜杠命令） |
| 最后活动 | transcript 最后一条记录的时间，括号内是相对时间 |
| 首条 | 第一条真实用户消息，通常代表这个会话在做什么 |
| 最近一条 | 最后一条真实用户消息，代表当前进展 |
| ECC 任务 | 匹配到的 ECC 会话摘要里的前两条 Tasks；没有摘要显示 `—` |
| 未提交 | 仅在 `--git` 时出现，`git status --porcelain` 的行数 |

`detail <名称>` 会输出单个会话的纵向详情，包含上述全部字段以及完整路径、ECC Tasks/Files、transcript。

## 可选参数

| 参数 | 作用 |
|---|---|
| `brief` | 默认子命令；只输出 名称 / 状态 / 启动 / 会话标题 |
| `detail` | 输出全量表格 |
| `detail <名称>` | 查询单个会话；名称、短 ID、全 ID、前缀都可以 |
| `--json` | 输出 JSON（含完整 sessionId、完整 cwd、ECC tasks/files、transcript 路径） |
| `--full` | Markdown 表格不截断单元格 |
| `--no-ecc` | 仅影响 detail：不读 ECC 摘要，表格少一列 |
| `--git` | 仅影响 detail：增加“未提交”列（非 git 目录显示 `—`） |
| `--alive-only` | 只显示进程还活着的会话 |
| `--limit N` | 最多显示 N 行 |

## 三类数据源

| 来源 | 提供什么 | 注意 |
|---|---|---|
| `~/.claude/sessions/<pid>.json` | 名字、sessionId、cwd、启动时间、busy/idle、pid | 进程退出后文件仍会留下，脚本用 `kill(pid, 0)` 判断是否真活着 |
| `~/.claude/projects/<slug>/<sessionId>.jsonl` | 会话标题（`aiTitle`）、首尾用户消息、轮次、最后活动 | slug 规则是“所有非字母数字字符换成 `-`”，不是简单把 `/` 换成 `-` |
| `~/.claude/session-data/*-<sessionId 后 8 位>-session.tmp` | ECC 摘出的 Tasks / Files Modified | 新会话可能还没有摘要；文件名匹配用的是 sessionId 去掉 `-` 后的末 8 位 |

## 关于“干了什么”

- “会话标题”直接取自 transcript 的 `ai-title.aiTitle`，是 Claude Code 自己生成的短标题，脚本不额外调用模型。
- 如果用户要截图里那种更像人话的总结，可以基于“会话标题 + 首条 + ECC 任务”压成一句话；只能压缩已有信息，不要补造没出现的事实。
- `aiTitle` 可能停留在会话中途的某个子话题上；与“首条”冲突时，以首条为准，并在回答里说明。

## 接到用户问题之后

1. **“哪个会话在做 X？”** —— 先跑默认 brief 看“会话标题”；需要更多线索时跑 `detail`；锁定某个会话后跑 `detail <名称>` 拿完整信息，回答时给出名称、短 ID 和目录。
2. **“接着那个会话做”** —— 告诉用户 `claude --resume <名字>`，会话内也可以用 `/resume <名字>`；提醒选择器里按 `Ctrl+A` 才显示全部项目。
3. **“给那个会话发消息”** —— 用 `SendMessage`，`to` 填会话名（脚本输出的名称就是地址）。用户没有明确要求时不要主动发消息。
4. **“会话刚开的，怎么没内容？”** —— transcript 可能尚未落盘，如实说明，不要编造主题。
5. **需要 cloud / Remote Control 会话** —— 脚本读不到服务端名单，调用 `ListAgents` 工具补一份，再和本地表并列说明。

## 边界

- 只读：脚本不写文件、不结束进程、不发消息。
- PID 复用（概率很低）可能让已退出会话显示为活着；状态列以注册表 + pid 存活综合判断。
- ECC 摘要可能滞后于 transcript；两处不一致时以“最近一条”为准。
- 大 transcript 只解析 user 行，其余行只做时间戳提取，80MB 级文件通常也在 1 秒内完成。
