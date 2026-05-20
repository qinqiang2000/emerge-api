# 2026-05-20 pre-label as subagent

## 背景

`pre_label` 现在是单个 tool call,N 文件**串行**,SDK turn 期间阻塞,几十到百文件场景断了要从头跑。Agent SDK doc `subagents.md` 给出 native 解法 —— subagent:自己 loop、每 turn 小批、parent 只回总结、session_id resume + idempotent skip = 真断点续传。

参考: `feedback_long_task_ux_agent_first.md`(agent 自己说话比 progress 卡好),`feedback_ai_native_api_symmetry.md`(tool ↔ HTTP dual-form 不变)。

## 目标

把"批量预标"从单 tool call 改为 subagent 编排 + 小批原子 tool,**进度 / resume / cancel 全部 SDK 原生**,不引入 progress 卡 / job-runner / lock 文件。

## 蓝图

```
parent agent
  └─ Agent(subagent_type="pre_label_runner", prompt="标 N 文件: [...]")
       └─ subagent loop (own session, max_turns=30, effort=low)
            ├─ turn 1: label_docs(slug, [f1..f5])  → agent_text "5/30 done"
            ├─ turn 2: label_docs(slug, [f6..f10]) → agent_text "10/30 done"
            ├─ ...
            └─ final: "Done. processed=N, skipped=K, errors=E"
```

- 每 turn = 一条 AssistantMessage(`parent_tool_use_id` 标记) → 前端 stream 白送 x/n
- session_id resume + `label_docs` 内的 `pending_reviewed_path(fn).exists()` skip = 真断点续传
- cancel = 停 subagent;已落盘的 `pending/<fn>.json` 不丢

## 改动清单

### A. tool 层 (`backend/app/tools/`)

**A1. `pre_label.py`**:
- 把 `async def pre_label(...)` → `async def label_docs(...)`(签名不变)
- 主循环加 idempotent skip:
  ```python
  if reviewed_path(workspace, slug, fn).exists():
      skipped.append({"filename": fn, "reason": "already_reviewed"}); continue
  if pending_reviewed_path(workspace, slug, fn).exists():   # NEW
      skipped.append({"filename": fn, "reason": "already_pending"}); continue
  ```
- 不在函数体内 hard-cap chunk 大小;靠 tool 描述和 subagent prompt 引导 caller 用 ≤10。

**A2. `__init__.py`**:
- 删 `@tool("pre_label", ...)` 块(line 188-230)、`tools=[...]` 里的 `t_pre_label`(line 831)、`__all__` 里的 `"pre_label"`(line 873)
- 加 `@tool("label_docs", ...)`:同 schema,描述说"原子小批 ≤10 files,upstream caller(主 agent / CLI / `pre_label_runner` subagent)负责分块"
- `set_labeler_model`, `get_labeler_config` 原样保留

### B. HTTP route

**B1.** `app/api/routes/pre_label.py` 改 `label_docs.py`,路径 `POST /lab/projects/{slug}/pre_label` → `POST /lab/projects/{slug}/label_docs`,thin-delegate 到 `pre_label_mod.label_docs(...)`
**B2.** `app/main.py:19, 75` 更新 import 和 `include_router`
**B3.** `app/api/routes/reviewed.py:9` `from app.tools.pre_label import get_pending` 不变(只是模块名保留)

### C. Symmetry test

`tests/unit/test_symmetry_invariant.py:79`: `"pre_label"` → `"label_docs"`,route pattern 同步改。

### D. Skill

**D1. 新建 `app/skills/emerge_pre_label_runner.md`** — subagent 的 system prompt 蓝本:
- 角色:批量预标 runner;唯一职责:把 `filenames` 标完并 narrate 进度
- 工作流:看入参 filenames,分 5-10 一批,每批一个 `label_docs` 调用
- Turn 之间 narrate:"已完成 X/Y(skip K,errors E),下一批 N 个: [...]"
- Errors 软处理:某个 doc 错了不中断,记下来在 final summary 里
- Resume 语义:外部再调一次完全等同于续跑(`label_docs` idempotent 兜底)
- Final 返回 parent 一句话总结(总数、跳过原因分类、errors 数)
- **不允许**:调 `extract_one`/`extract_batch`、改 schema、改 prompt、调任何 UI 工具

**D2. 改 `app/skills/emerge_extractor.md`** — 6 处 `pre_label` 提及更新:
- `line 45`: tool list 里 `pre_label` → "`label_docs`(原子)和 `pre_label_runner` subagent(批量)"
- `line 125, 268, 276, 284, 319`: 文案改为"批量预标:用 `pre_label_runner` 子 agent(via Agent tool);单文件 atomic 调用:`label_docs`"

### E. Chat service (`app/chat/service.py`)

**E1. `_build_options()` (line 450-517)**:
```python
from claude_agent_sdk import AgentDefinition  # 新 import

agents = {
    "pre_label_runner": AgentDefinition(
        description=(
            "Use this subagent to pre-label many docs (5+ files). "
            "It batches in chunks of ~8, narrates progress between batches, "
            "and soft-fails per doc instead of aborting the run."
        ),
        prompt=_load_skill_text("emerge_pre_label_runner"),  # 现有 skill 读取方式
        tools=[
            "mcp__emerge_tools__label_docs",
            "mcp__emerge_tools__list_docs",
            "mcp__emerge_tools__get_labeler_config",
        ],
        max_turns=30,
        effort="low",
    ),
}

return ClaudeAgentOptions(
    # ... 现有字段
    allowed_tools=["Agent"],   # 原 []
    agents=agents,
)
```

**E2.** 文案 `service.py:160, 202` 同步:旧 `pre_label` 提及改为"`pre_label_runner` 子 agent / `label_docs` 原子工具",区分用例。

### F. Frontend

**F1. `chat/stream.py`**(后端): 确认 SDK message 里的 `parent_tool_use_id` 透传到 SSE event payload。**待查**——如果 stream 转换层目前丢弃,需要加。

**F2. `frontend/src/components/Chat/MessageList.tsx`**: ToolCallEvent / AssistantMessage 渲染对 `parent_tool_use_id` 加 visual cue。**最小改动**:有 parent_tool_use_id 的消息加 "via pre_label_runner" 标签 + 左边一道 chrome rail 缩进,视觉上嵌套。

### G. Tests

**G1. 新 `tests/unit/test_label_docs.py`**:
- idempotency: 第二次 call 同 filenames → 全 skip,reason `already_pending`
- reviewed wins: 已 `reviewed/` 的总是 skip,reason `already_reviewed`
- filenames=[] / None → all unreviewed(语义不变)
- `labeler_model_not_configured` 路径

**G2.** 旧 `test_pre_label.py` 若存在 → rename + 改函数 reference,或 nuke 写新

## 待查(执行中 5 分钟内能定的)

1. **`permissions.py` gate 对 `Agent` 内置 tool 的判定** —— 当前 gate 主要看 `mcp__emerge_tools__*` prefix;`Agent` 不在这个 prefix,可能落到 default deny。需要在 gate 里显式 allow `Agent` 内置 tool(或在 `allowed_tools` 里预批就够)。
2. **`AgentDefinition.prompt` 字段长度** —— emerge skill markdown 大概 ~5-15KB;SDK doc 只提 Windows 8KB 命令行限制,Linux/Mac 上 inline 整段 markdown 应正常。
3. **`parent_tool_use_id` 在 `chat/stream.py` 是否透传** —— 待执行时 grep 确认。

## Out of scope (defer)

- Audit 发现的 6 个其他 SDK gap(`disallowed_tools` / `allowed_tools` / `session_id` 读法 / shorthand schema / ThinkingBlock / strict_mcp_config)—— 单独 milestone
- progress query tool / 进度 SSE 事件类型(subagent stream 已经够)
- pre_label job-runner 化(不需要——subagent + idempotent + filesystem state 已足)

## 执行顺序

A → B → C → D → E → F → G,每个 chunk 独立 commit(m12-pre-label-subagent-{a..g} 风格),`uv run pytest tests/unit/ -v` 每步绿,手测一遍 6 文件路径(看 chat UI 是否出现 subagent 进度 turn,断线/刷新后再发是否续跑)。
