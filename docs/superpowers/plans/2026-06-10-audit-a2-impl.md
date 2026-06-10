# 2026-06-10 — 审核 A2 实现（review / score：人确认审核结论 → 审核准确率）

> **Status**: 📝 plan
> **Design**: `2026-06-10-audit-design.md`（A2 = review/score，tune 审核规则）
> **基础**: A0 已 shipped（一项目一组文档；`run_audit` 一趟 judge 看图；`audits/{run}/report.json`）。
> **范围**: 人对每条规则的判定给真值 → ground truth → `score_audit` 重跑 judge 对比真值出 准确率 + precision/recall（fail 为正类）。规则即 prompt，tune 循环 = 改规则 → score → 看指标。
> **不在 A2**: 规则分级/L1 快路/前端视图（A3）、多组聚合（A1 后）。

---

## 与 match review 的两处刻意不同（设计决策）

1. **真值按规则文本 key，不按 index**。规则是版本化 prompt，会增删改排序；index 对齐会让旧真值错位到新规则上（静默污染）。按 rule text key：改了文案的规则自动失去旧真值（语义可能变了，本来就该重审），未动的规则真值跨版本存活。**拒绝**稳定 rule-id 方案——要求用户管理 ID，反 SSU。
2. **真值只有 pass|fail，没有 unclear**。`unclear` 是 judge 的能力局限，不是文档的合规状态——人审过就知道真相。judge 的 unclear 在 scoring 里＝没判对（真值 fail 时算漏报 fn，真值 pass 时不算误报 fp，单独计数上报）。

## 数据形态

- **一项目一组 → 单文件真值** `{slug}/reviewed_audit.json`（用户数据，绝不 rmtree；upsert merge，允许只确认部分规则——score 只算有真值的规则）：
  ```json
  {
    "expected": {"<rule text>": "pass" | "fail", ...},
    "match_prompt_version": 3,
    "reviewed_at": "..."
  }
  ```
- **score 输出**（fail = 正类，审核存在的意义是抓违规）：
  ```json
  {
    "run_id": "au_xxx",
    "reviewed": 5,
    "accuracy": 0.8,
    "precision": ..., "recall": ..., "tp": ..., "fp": ..., "fn": ...,
    "unclear": 1,
    "per_rule": [{"rule": "...", "truth": "fail", "predicted": "pass", "correct": false}],
    "unreviewed_rules": ["..."]
  }
  ```
  - tp = 真 fail 判 fail；fp = 真 pass 判 fail；fn = 真 fail 判 pass **或 unclear**；unclear 永不算 fp。
  - accuracy = correct / reviewed（unclear 不 correct）。
  - 无真值 → `reviewed=0` 零指标 envelope（同 `score_match` 口径）。

## 任务分解

### T1 — `app/tools/audit_review.py`（新建，镜像 `match_review.py` 结构）
- `save_reviewed_audit(ws, slug, *, expected: dict[str, str], reason="") -> dict`：
  - 读 active match prompt 的 `audit_rules`；`expected` 的 key 必须 ∈ 当前规则集，否则 `AuditError("audit_unknown_rule", …点名哪条…)`（防 typo / 防旧版本规则误写入）。
  - value 仅 `pass|fail`，否则 `audit_bad_status`。
  - 读旧文件 merge upsert，记录当前 prompt `version` + `reviewed_at`，atomic 写 `reviewed_audit.json`。
  - 返回 `{rules_confirmed, total_rules, unreviewed_rules}`。
- `score_audit(ws, slug, *, provider=None, model_id=None) -> dict`：
  - 无真值 / 真值与当前规则集零交集 → 零指标 envelope（不浪费 judge call：**先查真值再跑 judge**）。
  - `run_audit(ws, slug)` 重跑（评的是当前规则版本，这就是 tune 循环），按 rule text 对齐 checks ↔ expected，出上面指标。
- paths：`reviewed_audit_path(ws, slug)` 加进 `workspace/paths.py`（注释：user data, never rmtree）。

### T2 — 工具三形对称（`tools/__init__.py` + `routes/match.py` + symmetry map）
- `@tool save_reviewed_audit`（slug, expected, reason）/ `@tool score_audit`（slug；∈ `_TOUCHES_PROVIDER`）。
- HTTP twins 跟 A0 audit 路由同居 `routes/match.py`：`PUT /lab/projects/{slug}/audit-review`、`POST /lab/projects/{slug}/audit-score`。
- 描述用通用动词（confirm/score/rule），不硬编码文档类型。AuditError → `{error_code, error_message_en}` envelope（复用 t_run_audit 写法）。

### T3 — skill 渲染契约（`skills/emerge_extractor.md` audit 小节追加）
- 工作流：`run_audit` 出报告 → 用户逐条说"第 2 条其实不对/都对" → agent `save_reviewed_audit`（用户确认整份报告 = 把报告里 pass/fail 原样存真值；unclear 的规则必须问出真相才能存）→ 改规则后 `score_audit` 看指标变化。
- 渲染契约（browser/headless 一致）：score 出**一行指标**（`accuracy x/n · precision · recall · unclear k 条`）+ 逐条 `✓/✗ 规则 — 判了什么/真值是什么`（只列判错的 + unreviewed 提示）。不 dump JSON。

### T4 — tests（mock provider，沙箱禁 SSE 集成测试）
- `tests/unit/test_audit_review.py`：
  - save：合法 upsert merge / unknown rule 报错点名 / bad status / 部分确认。
  - score：全对 accuracy=1；fail 判 pass → fn；pass 判 fail → fp；unclear（真 fail → fn 且 unclear 计数；真 pass → 不进 fp）；规则改文案后真值脱钩（落 unreviewed_rules，不参与指标）；无真值零 envelope 且**不调 provider**（mock 断言未被调用）。
- symmetry：2 新工具进 map。
- 回归：`uv run pytest -v` 全量绿。

## 红线
- 真值是用户数据：`reviewed_audit.json` 绝不物理删/rmtree；`audits/` 仍是派生缓存。
- prompt 是真相：tune 只经 `write_audit_rules`，score 不写任何规则。
- provider 直连不回 SDK；score 重跑走 `run_audit` 现有路径，图不进 agent 上下文。
- chrome 任务类型无关：confirm/score/rule，不出现报价单/红章。
