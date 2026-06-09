# 2026-06-10 — 审核 A0 实现（单组审核最小闭环）

> **Status**: ✅ shipped + deployed prod (2026-06-10)。全量 1196 passed 零回归；E2E 实证（mock judge）报价单甲方签字栏空→正确判 fail。待真实数据 prod dogfood（含视觉 #2 红章）。
> **Design**: `2026-06-10-audit-design.md`（含真实数据验证 + 文档类型开放）。
> **范围**: 给**一组已凑齐**的文档（人工指定 anchor + 各 source 各一份）+ 一套 NL 审核规则 → `audit_group` judge（看字段 + 看图）逐条判 pass/fail → 审核报告。把「审核判定」这个新核心跑透。
> **不在 A0**: 自动凑齐（A1，复用 matching）、交付核对（A1+）、区间/固定值 L1 快路（A3）、规则分级、lab 前端审核视图、prod API。

---

## A0 的 5 个决策（用设计里的推荐默认）

1. **凑齐 = 人工指定**：`run_audit(slug, anchor_doc, source_docs={slug: doc})`。绕过自动配对，先把审核判定跑透。
2. **规则载体 = `audit_rules: list[str]`**：每条一句 NL（用户就这么列的），judge 按 index 对齐返回逐条结果（复用 [[feedback_llm_array_alignment_by_index]] 模式）。加进 `MatchPromptVariant`（`audit_rules: list[str] = []`，matching 不受影响）。
3. **视觉 = A0 附 anchor 图**：anchor（如报价单）是多数规则的主体，且 #2 红章在它上面。A0 总附 anchor 文档图（`read_doc_image`→`ImageBlock`），sources 仅字段。judge 自己从规则文本判断要不要用图。
4. **L1 快路 = 无**：A0 全交 LLM judge（最简）。#3/#5 确定性快路 A3 再加。
5. **overall = 所有规则必过**：任一 fail → fail；`unclear`（判不了）不算 fail，但拉低"确定通过"。

---

## 任务分解

### T1 — schema 扩展（`app/schemas/match.py`）
- `MatchPromptVariant` 加 `audit_rules: list[str] = []`（审核规则；与 pairing `rules` 区分）。`_content_hash` 纳入 audit_rules（改了产新版本）。
- 新增 audit 产出模型：
  - `RuleCheck`: `{rule: str, status: Literal["pass","fail","unclear"], reason: str}`。
  - `AuditReport`: `{run_id, created_at, group: {anchor: str, sources: dict[str,str]}, checks: list[RuleCheck], overall: Literal["pass","fail"]}`。

### T2 — paths/ids
- `audit_result_path(ws, slug, run_id)` → `{slug}/audits/{run}/report.json`；`new_audit_run_id()`（`au_`）。

### T3 — write_audit_rules（`app/tools/match_prompt.py` 扩展或同文件加）
- `write_audit_rules(ws, slug, audit_rules: list[str]) -> mpr_id`：upsert match prompt 的 `audit_rules`（复用现有版本化写法；mappings 不动）。或并进 `write_match_prompt(... audit_rules=None)`。倾向独立函数 `write_audit_rules` 清晰。

### T4 — audit judge（`app/match/audit.py` 新建）
- `audit_group(*, group_docs: dict[str, dict], anchor_role: str, audit_rules: list[str], anchor_image: Optional[ImageBlock], provider, model_id) -> list[RuleCheck]`：
  - `group_docs` = `{role: extracted_fields}`（role = anchor slug 或 source slug；值是该 doc 的首条 entity 字段 dict）。
  - 构造 judge 输入：system = 审核说明（逐条判，输出 index 对齐的 {status, reason}，看不了标 unclear，看图判视觉规则）；user_content = `[TextBlock(rules + 各 role 的字段 JSON), anchor_image?]`。
  - `response_schema` = `{checks: [{index, status, reason}]}`；按 index 对齐回 `audit_rules`，缺失/越界标 unclear（[[feedback_llm_array_alignment_by_index]]：不 strict-length-fail）。
  - 红线：provider 直连不回 SDK；图 pulled、规则触发才看；无 few-shot；bbox 不进 prompt。

### T5 — run_audit（`app/tools/audit_run.py` 新建）
- `run_audit(ws, slug, *, anchor_doc, source_docs: dict[str,str], provider=None, model_id=None) -> AuditReport`：
  - 读 match project（anchor_project + source_projects + active match prompt 的 audit_rules）。
  - 校验 anchor_doc ∈ anchor_project、各 source_docs[slug] ∈ 该 source_project。
  - 载入每个 doc 的 extract 首条 entity（`prediction_draft_path`→entities[0]）；缺则 error envelope（"先提取"）。
  - 载入 anchor 图（`read_doc_image`→`ImageBlock`）。
  - resolve judge provider（复用 match_run 的 `_resolve_judge_provider`）。
  - `audit_group` → checks → overall（all pass）。落 `audit_result_path`（派生缓存）。返回报告 summary。

### T6 — 工具三形对称（`__init__.py` + `routes/match.py` + symmetry）
- 2 个新 `@tool`：`write_audit_rules` / `run_audit`。always-on；`run_audit` ∈ `_TOUCHES_PROVIDER`。
- HTTP twins：`PUT /lab/match/projects/{slug}/audit-rules`、`POST /lab/match/projects/{slug}/audit`。symmetry map 加 2 条。
- chrome 通用动词（rule/check/audit），不硬编码文档类型。

### T7 — skill 渲染契约（`emerge_extractor.md`）
- 在 matching 章节后加 audit 小节：工作流（建项目+提取 → write_audit_rules → run_audit）+ 渲染契约：headless/browser 都把审核报告渲成**逐条清单**（✓/✗/? 规则 · 理由），末尾整体 过/不过 + 失败项点名。不 dump JSON。

### T8 — tests（mock provider）
- `test_audit_judge.py`: index 对齐（齐/缺/多）；status 三态；视觉规则附图分支（mock provider 收到 ImageBlock）；judge 失败→unclear。
- `test_audit_run.py`: 单组审核端到端（mock provider 返 5 条 → 报告 overall）；缺 extract→error；overall all-pass / 有 fail。
- `test_match_prompt.py` 扩展: audit_rules version bump。
- symmetry: 2 新工具。
- 回归：match 全套 + symmetry + mcp_remote + plugin_bundle 绿。

---

## 真实数据验证（prod dogfood，非本地）
本地 dev 是 dummy key，真实 extract/judge 只能在 prod。A0 落地后部署，然后用 `audit_demo/{报价单,收货单,订单}` 在 prod 走一遍：建 3 项目→提取→write_audit_rules(5 条)→run_audit→看第一份真实审核报告（预期 #1-#5 全 pass，红章 #2 靠视觉判出）。可由用户经 Cowork，或我经 prod MCP 连接器驱动。

## 红线
- lab=prod 一致；provider 直连不回 SDK；图 pulled 不 auto-attach；无 few-shot；bbox 不进 prompt；不物理删（audits/ 派生缓存）；task-agnostic chrome（不硬编码报价单/红章/文档类型）；prompt 是真相（规则只经 write_audit_rules 改）。
