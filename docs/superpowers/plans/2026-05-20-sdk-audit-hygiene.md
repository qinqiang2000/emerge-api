# 2026-05-20 SDK hygiene — 落地 audit 发现的 6 条 gap

## 背景

2026-05-20 跑了一次 `agent-sdk-verifier-py` audit(详见 `feedback_sdk_docs_audit_pattern.md` 描述的打法),对照官方 doc 找出 emerge 用 `claude_agent_sdk` 的 6 处不规范。本 plan 把这 6 条 + 1 条跨界 flag 一锅烹,分 3 个独立 commit 落地。

**前置**: pre_label subagent (`2026-05-20-pre-label-subagent.md`)必须先落地 commit。原因:5/6 都在 `service.py` / `tools/__init__.py` / `permissions.py`,跟 pre_label 的改动撞在同一函数里。

## 目标 / 非目标

**In**:
- `_build_options()` 治理(3 条:disallowed_tools 剥离、allowed_tools 通配预批、strict_mcp_config)
- session_id 读法换源
- shorthand schema 升级
- ThinkingBlock 注释修正
- `\btoken\b` 正则收紧

**Out**:
- 大幅改 permission gate 架构(只是收紧一个正则)
- 重新设计 chat service(不动 `chat_turn` / `_run_into_queue`)
- 改 SDK 集成行为(只调字段值,不引入新机制)

## Commit 1: m12-sdk-hygiene-options (`service._build_options()` 三连改)

**触点**: `backend/app/chat/service.py:470-517` 这一个 return,加上 `backend/app/chat/sdk_settings.json` 可能要改。

### Gap #1: 移到 follow-up plan,本批不做

**Explore findings**(2026-05-20):`ClaudeAgentOptions` 有 `tools: list[str] | ToolsPreset | None` 字段(`types.py:1582-1591`),**这才是真剥离 context 的字段**;`disallowed_tools` 只是 CLI 后期 deny filter(Claude 仍看得见 tool def)。`subprocess_cli.py:241-250` 印证 `--tools` 早期传,`--disallowedTools` 后期 deny。

**为什么本批不做**:emerge 当前 agent 重度依赖 built-ins(smoke test 看到调 Bash / Read / Glob),`tools=[]` 会一刀切让 agent 跛脚。正确做法是先做一份"emerge agent 在不同 chat path 里实际用到哪些 built-ins"survey,再写出 emerge 需要的白名单。

**Follow-up 任务**(单独 milestone):
1. 跑一组覆盖 typical chat path 的手测(extract / schema / autoresearch / pre_label / save_reviewed),用 SSE event log 抽出所有非 emerge-MCP 的 tool_call,得到实际 built-in 用量
2. 据此写 `tools=[...]` 白名单,删除 `disallowed_tools`
3. 配套手测回归

本批保留 `disallowed_tools=_SDK_NEVER_TOOLS` 不动。

### Gap #2: `allowed_tools` 通配预批 emerge MCP

```python
# 现在
allowed_tools=[],
# 改为
allowed_tools=["mcp__emerge_tools__*", "Agent"],
```

**Why**: 让 SDK 直接跳过 `can_use_tool` callback,减少每个 emerge tool 调用的一次 round-trip。`Agent` 已经在 pre_label commit 里加了。

**风险**: gate 仍然在 `permissions.py` 做 path-range / network-keyword 检查 —— **预批掉的是 callback 不是 gate**。验证:gate 里 `make_gate` 对 mcp__emerge_tools__* 的特殊处理是否依赖 callback 触发?如果是,要确认 SDK 在 `allowed_tools` 通配下仍然调 callback(doc 不太清),否则改回 ungated。

### Gap #6: `strict_mcp_config=True`

```python
return ClaudeAgentOptions(
    # ... 现有字段
    strict_mcp_config=True,   # NEW
)
```

**Why**: 防御深度。emerge 现在靠 `setting_sources=["project"]` 排除 user-level config,但不阻止 project-level `sdk_settings.json` 里偶然出现的第三方 MCP server entry。`strict_mcp_config` 强制 SDK 只用 `mcp_servers={...}` 显式传的,忽略 settings 文件里的 MCP 段。

**风险**: 极低。emerge 没在 `sdk_settings.json` 里配 MCP server。

### 测试

- 跑现有 chat 路径,确认每个 emerge tool 调用还在工作(extract_one、derive_schema、label_docs 都点一遍)
- 看 SSE event stream 确认 `permission_request` 数量降低(`allowed_tools` 通配生效)
- 验证 `Skill`/`PowerShell` 工具在 Claude tool list 里真的消失了(可让 Claude 试着调一次,看错误返回是"unknown tool"还是 deny)

## Commit 2: m12-sdk-hygiene-session-source

**触点**: `backend/app/chat/service.py:751-754` 那一块。

### Gap #3: session_id 从 ResultMessage 读

**现在**(audit 描述):
```python
if hasattr(message, 'data') and 'session_id' in message.data:
    sid = message.data['session_id']
# fallback
elif hasattr(message, 'session_id'):
    sid = message.session_id
```

**doc 推荐**:`ResultMessage.session_id` 是契约字段(每个 result 都有,无论成功失败);`SystemMessage.data["session_id"]` 是内部 init 事件 shape,不是稳定 API。

**改法**: 让 session_id 的提取等到 `ResultMessage` 到来时再做。

### 风险

session_id 是 resume 的钥匙 —— 改错直接断 multi-turn 记忆。需要:
- 单测覆盖:模拟 SDK message 流,检查我们能从 ResultMessage 拿到 session_id
- 手测:发两轮对话,第二轮看是不是基于第一轮的 context(agent 记得第一轮说了啥)

### 测试

- 新增 `backend/tests/unit/test_session_id_source.py`(或加到现有 chat service 测试):mock ResultMessage,断言 session_id 走 `ResultMessage.session_id` 路径
- 手测 multi-turn

## Commit 3: m12-sdk-hygiene-schemas-and-misc

**触点**: 多个 tool 注册(`backend/app/tools/__init__.py`),`service.py:888-891` 注释,`backend/app/chat/permissions.py:62`。

### Gap #4: shorthand schema → JSON Schema

把这些工具(audit 列出的、所有用 `{"key": type}` shorthand 的)升级为完整 JSON Schema:
- `delete_project` (line ~125 附近)
- `set_labeler_model` (line ~244)
- `t_get_labeler_config` (line ~263)
- 其他凡 `{"slug": str}` / `{"slug": str, "model_id": str}` 形态的

**模式**(参考已有的完整 schema 写法,例如 `@tool("label_docs", ...)`):
```python
{
    "type": "object",
    "properties": {
        "slug": {"type": "string"},
    },
    "required": ["slug"],
}
```

### Gap #5: ThinkingBlock 注释修正

`service.py:888-891`:
- **现在**注释说"drop — re-enable as `agent_thinking` 后跟 UI toggle"
- 问题:`adaptive thinking` 模式下,`StreamEvent` partial messages 不会包含 thinking 块(SDK 已知限制),所以"re-enable via StreamEvent"这条路走不通
- **改**:把"re-enable via StreamEvent"这部分误描述删掉,只留事实:"Currently drop — model 内部推理,emerge 暂未消费"

### 跨界 #7: `permissions.py:62` `\btoken\b` 正则收紧

`_SECRET_LITERAL_PATTERNS` 里 `\btoken\b` 会误中 `pagination_token`, `cancel_token` 等合法字段名。

**改**:把 `\btoken\b` 改成更具体的形态,比如 `\b(api_token|access_token|auth_token|bearer_token)\b`,或者匹配 token 值的形态(`(?i)(token|secret)["\']?\s*[:=]\s*["\']?[A-Za-z0-9_-]{20,}`)。

**Why**: 现在某些 tool 调用 / Bash 命令含合法的 `token` 字段会被 gate 错误拦下,引发"why deny" 的 UX 坑。

### 测试

- 现有 tool schema 测试应该都过(JSON Schema 更严格但语义不变)
- 新增 `test_permissions_token_regex.py`:断言 `pagination_token` / `cancel_token` 不再触发,但 `api_token=xxx_real_long_value` 仍触发
- 手测一遍 chat,跑现有 tool flow

## 执行 plan

按 Commit 1 → 2 → 3 顺序。每个 commit 后:
- `cd backend && uv run pytest tests/unit/ -v` 全绿
- Smoke test:打开 chat,跑一遍 pre_label_runner subagent + extract_one + save_reviewed,看没回归

Commit 1 阻塞于 Explore subagent 关于 Gap #1 的 finding。如果 finding 推迟,先做 Commit 2 + 3,Commit 1 等 finding 回来。
