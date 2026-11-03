# ai-title 与 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`

记录日期：2026-11-03

## 背景

本机长期设置 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`，用于关闭遥测、错误上报和插件市场自动安装等非必要外联。Claude Code 2.1.316 起，这个总开关同时抑制了自动会话标题（`ai-title`），导致 `agents-info` 里大量会话没有“会话标题”。

排查结论：这不是 `agents-info` 的读取问题，而是 Claude Code 在标题请求前直接短路。

## 代码事实（2.1.316 / 2.1.317）

2.1.316 与 2.1.317 的判断逻辑相同，只是压缩后的函数名变了：

```js
function Ptn() {
  if (process.env.CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC) return "essential-traffic";
  // ...
}
function St() { return Ptn() === "essential-traffic" }
function ZDo() { return St() || i.CLAUDE_CODE_DISABLE_TERMINAL_TITLE }   // 2.1.317；2.1.316 中叫 MPo()
if (!Lo && !ZDo() && !yn && !un && !rn && !this._haikuTitleAttempted) {
  // 这里才会发起标题请求
}
```

结论：

- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` 是**全有或全无**的开关；目前没有“只放行 ai-title”的环境变量。
- `CLAUDE_CODE_DISABLE_TERMINAL_TITLE` 只会让标题更早被禁用，不能反向放行。
- 标题请求由 Claude Code 自己发起，`agents-info` 不会补调模型，也无法补写历史标题。

## 当前处置

在 `~/.claude/settings.json` 的 `env` 中删除总开关，换成精确开关：

```json
"DISABLE_TELEMETRY": "1",
"DO_NOT_TRACK": "1",
"DISABLE_ERROR_REPORTING": "1",
"CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL": "1"
```

代价：cloud / 插件市场等非必要功能恢复可用（只在真正用到时联网）。

本机标题请求只发往本地网关，不出本机。

## 备份

| 文件 | 说明 |
|---|---|
| `~/.claude/settings.json.bak.20261103-111730-pre-precise-switches` | 改动前，含 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` |
| `~/.claude/settings.json.bak.20261103-111907-post-precise-switches` | 改动后，四个精确开关 |
| `~/.cc-switch/cc-switch.db.bak.20261103-111730-pre-precise-switches` | cc-switch 数据库改动前 |

## 谁会重新写回这个开关

`cc-switch`（`com.ccswitch.desktop`）会把 Claude 配置写进 `~/.cc-switch/cc-switch.db`：

- `settings` 表的 `common_config_claude` 行
- `providers` 表中各 provider 的 `settings_config`

2026-11-03 已同时从 `common_config_claude` 和 `百炼` provider 中删除该键。以后新增或切换 provider 时，仍要检查 cc-switch 是否又把它带回来。

`magpie` 只做本地路由和模型字段管理，无法控制这个标题开关。

## 回退条件

满足以下任一条件时，可以把 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` 改回来：

1. Claude Code 提供精确控制 ai-title 的开关（例如允许“禁用非必要流量但保留标题”）；或
2. 新版本中 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` 不再抑制 ai-title。

回退步骤：

1. 在 `~/.claude/settings.json` 的 `env` 中恢复 `"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"`；
2. 同步修改 `~/.cc-switch/cc-switch.db` 的 `common_config_claude` 和所有 provider 的 `settings_config`，否则切换 provider 时会被重新写回；
3. 视情况删除四个精确开关（保留也不冲突，但会重复）；
4. 重启 Claude Code；恢复开关不会给已有会话补标题。

## 生效范围

- 已在运行的会话继续使用旧环境，直到重启；重启/恢复旧会话也不会补写历史 ai-title。
- 只有设置生效后**新启动**的会话才会生成标题。
- 2.1.316 与 2.1.317 都受同一个门控制；升级到 2.1.317 不会自动解决。

## 审计“没有 ai-title 的会话”时的注意点

`~/.claude/projects/*/*.jsonl` 里不全是用户会话。Claude Code / ECC 的摘要子进程也会各自落一个 transcript，其首条用户消息通常以：

```
Below is a conversation log from a Claude Code coding session.
```

开头。这类文件不会生成 ai-title，也不应计入“用户会话”。排查时先排除它们，再看首条真实用户消息或 slash command。
