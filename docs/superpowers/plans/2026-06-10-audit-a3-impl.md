# 2026-06-10 — 审核 A3 实现（规则分级 + L1 快路 + lab 审核报告视图）

> **Status**: 📝 plan
> **Design**: `2026-06-10-audit-design.md`（A3 + 开放决策 #4/#5 的落地）
> **基础**: A0（run_audit 一趟看图）+ A2（save_reviewed_audit/score_audit）已 shipped。
> **范围**: ① 规则分级 critical/warning（overall 三态）；② 区间/固定值 L1 确定性快路（省钱+可解释，judge 兜底）；③ lab 前端审核报告卡片（chat 内 AuditCard，对标 EvalCard 适配器模式）+ 报告读取 GET route。

---

## 设计决策（按品味定的三点）

1. **规则升级为对象但字符串永远可用**。`audit_rules: list[AuditRule]`，`AuditRule = {rule: str, level: "critical"|"warning" = "critical", check: Optional[L1Check] = None}`；pydantic validator 把裸字符串коerce 成 `{rule, level:"critical"}`——存量 prod match prompt JSON（list[str]）读入即兼容，工具/HTTP 入参 `list[str | object]` 混排合法。**规则文本仍是身份**（A2 真值按 text key，不受 level/check 影响——改 level 不脱钩真值，改 rule 文案才脱钩）。
2. **overall 三态 `pass | warn | fail`**：任一 critical fail → `fail`；仅 warning fail → `warn`；否则 `pass`（unclear 不降级，照旧单独提示）。`RuleCheck` 增 `level` + `decided_by: "l1"|"judge"`。score_audit 不分级加权（真值仍 pass/fail，指标口径不变）。
3. **L1 是"有结构 spec 且字段在手才走"的快路，不是新依赖**。审核哲学不变（提取不是前置、图是真相）：只有当规则带显式 `check` spec **且**引用的 doc 有已提取字段时才 L1 判定；spec 缺、字段缺、解析不动 → 整条规则照常进 judge 一趟。L1 判定的规则**不进 judge prompt**（省钱、可解释），报告里 `decided_by:"l1"`。

## L1Check spec（极简两型，复用 match/judge.py 的归一化原语）

```json
// 固定值断言：某 doc 的字段 == 常量
{"type": "eq", "left": {"doc": "报价单", "field": "brand_client"}, "right": "环胜电子商务（上海）有限公司"}
// 跨文档一致：两边都是字段引用（数值/日期自动归一化，数字剥货币符号千分位）
{"type": "eq", "left": {"doc": "报价单", "field": "total"}, "right": {"doc": "收货单", "field": "amount_after_discount"}, "tol": 0.01}
// 区间包含：value ∈ [low, high]，三处各可为字段引用或常量
{"type": "range", "value": {"doc": "订单", "field": "complete_date"}, "low": {"doc": "报价单", "field": "period_start"}, "high": {"doc": "报价单", "field": "period_end"}}
```

- `doc` 按 **filename 精确或唯一子串** 匹配 run_audit 实际载入的 doc（"报价单" 匹配 `报价单.pdf`；0 或 >1 命中 → 不走 L1 落 judge，理由写进 reason？不——L1 不产出 unclear，匹配失败就静默交 judge，报告只见 judge 结果）。
- 比较语义：两边先 `_try_number`（剥 ¥/千分位）再 `_try_date`，都失败按 unicode-canonical 字符串等值；`tol` 仅对数值。range 对数值和日期都成立。
- spec 由 **agent 在用户 NL 规则明显结构化时**附上（skill 教），用户仍只说 NL——SSU 不变。

## 任务分解

### T1 — schema（`app/schemas/match.py`）
- 新 `L1FieldRef {doc, field}`、`L1Check`（如上，extra=forbid，type 判别）。
- 新 `AuditRule {rule, level="critical", check=None}` + validator 收字符串。`MatchPromptVariant.audit_rules: list[AuditRule]`（validator 整列коerce）。`_content_hash` 用 canonical `model_dump`（确保同内容同 hash；纯 str 时代的 hash 变更可接受——只在下次写入时 bump）。
- `RuleCheck` 增 `level: Literal["critical","warning"]="critical"`、`decided_by: Literal["l1","judge"]="judge"`。`AuditReport.overall: Literal["pass","warn","fail"]`。

### T2 — L1 引擎（`app/match/audit_l1.py` 新建）
- `try_l1(rule: AuditRule, doc_fields: dict[filename, fields]) -> Optional[RuleCheck]`：None = 交 judge。纯函数,不碰 provider/IO。归一化 import 自 `app/match/judge.py`（已有 `_try_number`/`_try_date`——若为私有,在 judge.py 导出公共别名,别复制实现）。
- reason 模板可解释：`"L1: 370815.56 == 370,815.56 (tol 0.01)"` / `"L1: 2025-02-28 ∈ [2025-01-15, 2025-02-28]"`。

### T3 — run_audit 接线（`app/tools/audit_run.py` + `app/match/audit.py`）
- run_audit：载入 fields 后先对每条带 check 的规则 `try_l1`；命中的收 RuleCheck(decided_by="l1")，**剩余规则**才进 `audit_group` 一趟（全 L1 命中则 0 judge call）。
- `audit_group` 入参改 `list[AuditRule]`（编号仍 0-based 对剩余子集,按子集 index 对齐后映射回原规则——或更简:传原 index 让 judge 按原 index 答,二选一,测试锁行为）。
- overall 三态计算挪到 run_audit（含 level）。
- write_audit_rules / routes / @tool 入参放宽 `list[str | dict]`;工具描述补 level/check 说明（通用动词,具体文档类型只出现在示例串里）。
- A2 兼容：save_reviewed_audit/score_audit 取规则文本 `[r.rule for r in mpv.audit_rules]`,其余不动。

### T4 — 报告读取 GET（三形对称）
- `read_audit_report(ws, slug) -> 最新 report`（按 run 目录 mtime/run_id 取最新；无 → `audit_no_report`）。@tool + `GET /lab/projects/{slug}/audit/latest`，symmetry map 登记。前端面板与 Cowork/headless 共用。

### T5 — 前端 AuditCard（对标 EvalCard 适配器模式）
- `src/components/Chat/AuditCard.tsx`：识别 `run_audit`/`score_audit` tool_result JSON（适配器写法参照 `EvalCard.tsx` 的 `adaptScoreResult` + ToolCall 接线处）→ 卡片：
  - run_audit：逐条 `✓/✗/?` 行（rule 文本 + reason 次行;level=warning 行加 ochre badge「警告」,critical 不加 badge——默认即关键;`decided_by:"l1"` 加小标「规则」/「L1」以示可解释）;头部 overall 徽章 pass=moss / warn=ochre / fail=rose + soft 底。
  - score_audit：一行指标（accuracy x/n · P · R · unclear k）+ 仅判错行列表。
- 色彩只用语义 token（moss/rose/ochre + soft 变体），无裸色。雷区：Zustand selector 别在内联生成新引用（[[project_zustand_selector_fresh_ref_loop]]）。
- `npm run test`（vitest）加 adapter 单测：合法 JSON→行数据、非 audit JSON→null（不劫持别的 tool result）、三态 overall 配色映射。

### T6 — skill 契约更新（`emerge_extractor.md` audit 小节）
- 教 agent：用户 NL 规则明显是 固定值/跨文档数值/区间 时,`write_audit_rules` 给该条附 `check` spec + 合适 `level`（用户说"这条只是提醒"→ warning）;不确定就纯 NL 交 judge——**宁可全 judge,不可错 spec**。
- 渲染契约补 overall=warn 分支（browser: AuditCard 自动;headless: `过(有警告)` + 点名 warning 失败条目;L1 判定条目说明判定来源）。

### T7 — tests
- `test_audit_l1.py`：eq 数值（千分位/货币符号/tol）、eq 字符串 canonical、range 日期/数值、doc 子串唯一/歧义/不命中→None、字段缺→None。
- `test_audit_run.py` 扩展：L1 命中规则不进 judge（mock 断言 judge 只收到剩余规则且 index 对齐正确）、全 L1 零 judge call、overall 三态（critical fail→fail / 仅 warning fail→warn / 全过→pass）、存量 list[str] prompt JSON 读入兼容。
- `test_audit_review.py` 回归：对象规则下真值按 text 仍工作。
- symmetry +1（read_audit_report）。全量 pytest + 前端 vitest + `tsc -b` 绿。

## 红线
- 提取不是前置：L1 仅在字段碰巧在手时快路,缺字段静默交 judge,绝不报"先提取"。
- bbox/few-shot 红线不变;L1 纯字段值比较,不碰图。
- prompt 是真相：check spec 活在 audit_rules（版本化）里,不硬编码业务规则进引擎。
- Tailwind 只用语义 token;chrome 通用动词。
- `audits/` 派生缓存;`reviewed_audit.json` 用户数据不删。
