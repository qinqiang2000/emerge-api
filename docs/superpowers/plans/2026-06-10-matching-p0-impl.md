# 2026-06-10 — 匹配 P0 实现（anchor + 1 source 最小闭环）

> **Status**: 📋 planned → implementing
> **Design**: `2026-06-09-doc-matching-design.md`（已定稿）。本 plan 是 P0 的任务分解 + 代码锚点。
> **范围**: anchor + **1** source 的对账闭环，**后端 + headless 可达**（前端核对视图放 P0.5 与扩 N source 一起）。二元 = N=1，数据模型一开始就支持 N，实现先做 1。
> **北极星**: 复用 emerge 已有脊（project / PromptVariant 版本化模式 / eval 归一化原语 / extract 结果 / review-eval 结构），新增只有「关系」这一层。

---

## 实现期对设计的三处修正（探锚点得出）

1. **project kind 复用现成 `project_type`**（`create_project` 已有 `project_type="extraction"`）→ match project = `project_type="match"`，**不新加 `kind` 字段**。anchor/source 引用用 `update_project(slug, patch)` 写进 project.json。
2. **match prompt 新建 `MatchPromptVariant` 类**（`PromptVariant` 是 `extra="forbid"` 焊死了 `schema` 字段，不能复用类）——复用的是**版本化模式**（`version` + `content_hash` + `_versions/` 快照，照搬 `write_prompt` 的写法）。
3. **L1 判定复用 normalize 的归一化原语，不复用 `normalize_equivalent` 本体**——后者是**精确等价**（`td == pd_`），匹配要**容差内**（金额 ±0.01、日期 ±N 天）。复用 `app/eval/normalize.py` 的 `_try_number` / `_try_date` / `_unicode_canonical`，容差比较新写。L2 LLM judge 复用 provider 直连。

---

## 任务分解

### T1 — schemas（`app/schemas/match.py` 新建）
- `Tol`: `{type: Literal["exact","number","date_days"], abs?: float, days?: int}`（pydantic, `extra="forbid"`）。
- `KeyMapping`: `{anchor: str, source: str, tol: Tol}`。
- `MatchPromptVariant`: `{prompt_id, label, mappings: dict[str, list[KeyMapping]], rules: str="", derived_from, created_at, updated_at, version: int=1, content_hash}`（`mappings` keyed by source slug；镜像 `PromptVariant` 版本化字段）。
- `PairVerdict`: `{source: str, doc: str|None, status: Literal["match","mismatch","missing"], mismatched_fields: list[str], reason: str|None, score: float}`。
- `MatchCard`: `{anchor_doc: str, pairs: list[PairVerdict], overall: Literal["complete","partial","unmatched"]}`。
- `MatchResult`: `{run_id, created_at, anchor_project, source_projects, cards: list[MatchCard], orphans: dict[str, list[str]]}`。

### T2 — paths + ids（`app/workspace/paths.py` / `ids.py`）
- `match_prompts_dir(ws, slug)` → `{slug}/match_prompts/`；`match_prompt_path(ws, slug, mpr_id)`；`match_prompt_versions_dir(...)`（镜像 prompts/_versions）。
- `matches_dir(ws, slug)` / `match_result_path(ws, slug, run_id)` → `{slug}/matches/{run}/result.json`。
- `reviewed_matches_dir(ws, slug)` → `{slug}/reviewed_matches/`。
- `new_match_prompt_id()`（`mpr_`）+ `new_match_run_id()`（`mr_`）。

### T3 — match project（`app/tools/match_project.py` 新建）
- `create_match_project(ws, *, name, anchor, sources: list[str]) -> {project_id, slug}`：复用 `create_project(project_type="match")` 起骨架，再 `update_project` 写 `{anchor_project, source_projects, active_match_prompt_id: None}`。校验 anchor/各 source 是已存在的**非 match** extract project（`project_json_path` exists 且 `project_type != "match"`），否则 error envelope。建 `match_prompts/`/`matches/`/`reviewed_matches/`。
- `read_match_project(ws, slug)` → 含 anchor/sources 的 dict；`is_match_project(ws, slug)`。

### T4 — match prompt CRUD（`app/tools/match_prompt.py` 新建）
- `write_match_prompt(ws, slug, *, mappings, rules, reason) -> mpr_id`：照搬 `app/tools/prompt.py::write_prompt` 的 `_content_hash`（hash mappings+rules）+ version-bump-on-change + `_versions/` 快照 + 设 `active_match_prompt_id`。`project_lock`。
- `read_active_match_prompt(ws, slug) -> MatchPromptVariant`。

### T5 — 判定层（`app/match/judge.py` 新建；`app/match/__init__.py`）
- `key_match(anchor_val, source_val, field: SchemaField, tol) -> (bool, normalizer)`：按 `tol.type` — `exact`（复用 `_unicode_canonical` + id/code casefold）/ `number`（`_try_number` 两边，`abs(a-b) <= tol.abs`）/ `date_days`（`_try_date`，`abs((a-b).days) <= tol.days`）。`field` 取自 anchor/source 的 active schema（按字段名查类型，给归一化用）。
- `judge_pair(anchor_entity, source_entity, mappings_for_source, anchor_schema, source_schema, rules, provider) -> PairVerdict`：逐 key `key_match` → 全 match=match / 有差=mismatch + `mismatched_fields`；**模棱**（部分 key 差或名称模糊）才调 L2 `provider` judge(rules + 两份字段) 兜底。`score` = matched_keys/total_keys。
- 红线：provider 直连不递归回 SDK；judge prompt 只喂字段值，无 bbox。

### T6 — 配对引擎（`app/match/engine.py` 新建）
- 读 anchor 每 doc 的 extract entities（`prediction_draft_path(ws, anchor_project, filename)` → `entities`）；同理每个 source。缺 draft 的 doc 跳过 + 记。
- **P0 全配对**（lab 规模小）：anchor × 该 source 全候选 → `judge_pair` 打分。**blocking 留 P0.5**。
- **贪心 1:1**：候选按 score 降序，anchor_doc 与 source_doc 都未占用且 score≥阈值则配对；占用即跳过。每 source 类别独立分配。
- 组装 `MatchCard`（anchor + 每 source 最佳 pair 或 `missing`）+ `orphans`（各 source 未被认领 doc）。`overall`: 全 match=complete / 部分=partial / 全 missing=unmatched。

### T7 — run_match（`app/tools/match_run.py` 新建）
- `run_match(ws, slug) -> MatchResult`：读 match project + active match prompt → engine → 落 `match_result_path`（派生产物，可 rmtree 重跑）。返回 summary（cards 数 / complete 数 / orphan 数）。

### T8 — review + score（`app/tools/match_review.py` 新建）
- `save_reviewed_match(ws, slug, *, anchor_doc, verdict)`：人确认一张发票整组核对 → 落 `reviewed_matches/{anchor_doc}.json`（ground truth）。
- `score_match(ws, slug) -> {per_source: {precision, recall}, doc_completeness}`：跑一次 match → 比对 `reviewed_matches/` → per-source precision/recall + 整单完整率。复用 `app/eval/` 聚合脊。

### T9 — 工具三形对称（`app/tools/__init__.py` + `app/api/routes/match.py` + symmetry）
- 5 个 `@tool`：`create_match_project` / `write_match_prompt` / `run_match` / `save_reviewed_match` / `score_match`。always-on。annotations：create/write/run/save 非 destructive 非 idempotent；score readOnly；`run_match`/`score_match` 进 `_TOUCHES_PROVIDER`。
- 各配 HTTP twin（新 `routes/match.py`，`bind_workspace` + `current_ws()`）+ `_TOOL_HTTP_MAP` 登记 + main.py include_router。chrome 通用动词。

### T10 — tests
- `test_match_judge.py`: tol exact/number(±)/date_days；mismatch；L2 兜底分支（mock provider）。
- `test_match_engine.py`: 全配对 + 贪心 1:1（占用排他）；orphans；missing source；card overall。
- `test_match_project.py`: create（project_type=match + 引用校验：source 不存在/指向 match project 报错）。
- `test_match_prompt.py`: version bump-on-change + 快照 + content_hash 稳定。
- `test_match_review.py`: save_reviewed_match + score precision/recall。
- `test_symmetry_invariant.py`: 5 个 match tool ↔ route。
- 回归：headless server tool count、symmetry、oauth、plugin bundle 全绿。

---

## 红线（遵守）
- **lab=prod 一致**：判定两趟（extract 先行 → match 在结果上）；provider 直连不回 SDK。
- **bbox 永不进 prompt**：judge 只喂字段值。
- **不物理删用户数据**：`matches/{run}/` 派生缓存可 rmtree；project/prompt/reviewed 走 trash/原子写。
- **任务类型无关 chrome**：工具/字段用 anchor/source/card/reconcile，不硬编码 invoice/payment。
- **prompt 是真相**：匹配规则只经 `write_match_prompt`（mappings + rules）改，业务规则不硬编码进 engine。
- **无新根级 sentinel**：match 产物都在 project 目录内。

## 不在 P0（明确推迟）
- 前端核对视图（P0.5，与扩 N source + review overlay 多栏一起）。
- blocking 候选剪枝（P0 全配对够小规模）。
- anchor + N source 引擎遍历 + per-source eval 细化（P0.5）。
- match prompt 挂 experiment / `/compare` / AutoResearch（P1）。
- 对账 prod API `/v1/{pid}/reconcile`（P2）。
- 同类 1:N（分期付款）。
