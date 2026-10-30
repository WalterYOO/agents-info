# agents-info

把本机所有 Claude Code 会话汇总成一张可读的表：**名字、状态、目录、启动时间、用户轮次、会话标题、首条、最近一条消息、ECC 任务摘要**。

这就是会话 `20261026-174317-d4` 里定下的方案落地版：`skill + scripts/sessions_table.py`，三源合并（注册表 + transcript + ECC 摘要），新名字 `/agents-info`，内置 `/list-agents`、`/peers` 原样不动。

## 目录结构

```
agents-info/
├── .gitignore
├── LICENSE
├── README.md
└── skills/
    └── agents-info/
        ├── SKILL.md             # skill 定义，Claude 加载后照此调用脚本
        └── scripts/
            └── sessions_table.py # 纯数据层：扫注册表、读 transcript 首尾、匹配 ECC 摘要
```

## 安装

把 **skill 目录**（不是 repo 根目录）链接到 Claude Code 的 skills 目录：

```bash
ln -s /Users/walter/agents-skills/agents-info/skills/agents-info ~/.claude/skills/agents-info
```

新开一个会话后即可使用：

```
/agents-info
```

也可以不安装，直接跑脚本：

```bash
python3 /Users/walter/agents-skills/agents-info/skills/agents-info/scripts/sessions_table.py --md
```

如果之后发布到 GitHub，也可以按常规方式安装：

```bash
npx skills add <owner>/agents-info
```

## 用法

```bash
python3 skills/agents-info/scripts/sessions_table.py --md          # 默认：Markdown 表格
python3 skills/agents-info/scripts/sessions_table.py --json        # 机器可读
python3 skills/agents-info/scripts/sessions_table.py --full        # 不截断单元格
python3 skills/agents-info/scripts/sessions_table.py --no-ecc      # 不读 ECC 摘要
python3 skills/agents-info/scripts/sessions_table.py --alive-only  # 只看还活着的
python3 skills/agents-info/scripts/sessions_table.py --limit 5     # 只看前 5 行
python3 skills/agents-info/scripts/sessions_table.py --git         # 增加未提交文件数
```

输出示例（截断）：

```
共 3 个会话，2 个在运行（busy 1 / idle 1）。

| 名称 | 状态 | ID | 目录 | 启动 | 轮次 | 最后活动 | 会话标题 | 首条 | 最近一条 | ECC 任务 |
|---|---|---|---|---|---|---|---|---|---|---|
| agents-info-2b ★ | busy·本 | cd5ea42b | ~/agents-skills/agents-info | 10-30 09:34 | 3 | 10-30 09:59 (刚刚) | agents-info skill 实现 | 实现 agents-info skill | 补上会话标题列 | — |
| pocketgo-09 | idle | 04680c0b | ~/dsh/embodied_ai_umi/pocketgo | 10-27 23:42 | 8 | 10-28 17:14 (1天前) | calibration_guide.html 上传与 index.html 引导卡 | 把 calibration_guide 传到服务器 | 修订 nginx 引导页 | 上传 guide + 改 index |
```

## 数据从哪来

| 来源 | 字段 |
|---|---|
| `~/.claude/sessions/<pid>.json` | `pid` / `sessionId` / `cwd` / `startedAt`（epoch ms）/ `name` / `status`（`idle` / `busy`） |
| `~/.claude/projects/<slug>/<sessionId>.jsonl` | `type` / `isMeta` / `timestamp`（如 `2026-10-30T00:59:39.669Z`）/ `message.content`；`type:"ai-title"` 记录里的 `aiTitle` 就是会话标题 |
| `~/.claude/session-data/<date>-<末8位>-session.tmp` | `### Tasks`、`### Files Modified` 下的 `- ` 条目 |

关键细节：

- 项目目录 slug 的规则是**所有非字母数字字符都换成 `-`**，所以 `embodied_ai_umi` → `embodied-ai-umi`。直接拼路径会找不到 transcript。
- 会话是否还活着用 `kill(pid, 0)` 判断；注册表文件在进程退出后不会自动删除。
- 轮次只数“真实用户消息”：排除 `tool_result`、`isMeta` 系统注入、以 `<` 开头的斜杠命令/系统提醒。
- “会话标题”来自 transcript 里 `type:"ai-title"` 记录的 `aiTitle`（Claude Code 自动生成）。同一会话有多条，取最后一条非空值；新会话可能还没生成。
- 读 transcript 时只对 user 行做 JSON 解析，其余行只提取时间戳；80MB 级文件通常 1 秒内完成。
- ECC 摘要按 `sessionId` 去掉 `-` 后的末 8 位匹配文件名，例如 `...-62de63f69f02` 对应 `2026-10-30-63f69f02-session.tmp`。

## 边界

- 只读：不写文件、不结束进程、不发消息、不联网。
- 看不到 cloud / Remote Control 会话的服务端名单；需要时在会话里让 Claude 调 `ListAgents` 补充。
- PID 复用（概率很低）可能把已退出会话误判为活着。
- 新会话的 transcript / ECC 摘要可能尚未落盘，对应列显示 `—`。
- 合盖休眠等情况下“最后活动”会停在 transcript 的最后一条记录时间。

## 和内置 `/list-agents` 的关系

- 新名字，零冲突：`/list-agents`、`/peers` 完全不动，随时能看原版名单。
- 如果以后想用 `/list-agents` 直接输出这张表，可以在 `~/.claude/commands/list-agents.md` 里放一个薄壳命令转调本脚本（已验证用户命令能覆盖内置命令）；不想要了删掉该文件即可回退。
- `SendMessage`、subagent/teammate 列表等能力不受影响。

## 卸载

```bash
rm ~/.claude/skills/agents-info   # 只删软链，源目录保留
```
