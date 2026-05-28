# 2026-05-28 — Bench leaderboard (project-level prompt × model 横览)

> **Status**: planned 2026-05-28
> **Inputs**: `docs/design_docs/HANDOFF.md` + `bench.jsx` (design demo) — Bench surface
> **Closes**: ROADMAP follow-up "Field-diff power-user view (spec §7.4.1)" + M9.3 deferred "Experiment detail sheet (FSSpine experiment row click)"
> **Does NOT close**: AutoResearch candidate banner（design 自承 stub）, ContextSurface 双卡（独立 follow-up）

---

## Goal

User 在 Project 内问「哪个 (prompt × model) 组合表现最好」时，能在一张 leaderboard 上直接看：

- 一行一个 experiment（含隐式 baseline = active prompt × active model + 最近 `predictions/_draft/` 的 eval）
- 每列一个 schema field，cell = `N/M 正确 + 6-tick ✓✗ strip`（前 6 个 reviewed doc 同一组，按 filename lex-sorted）
- 头部 prompt rail + model rail，hover chip 时矩阵里非该轴的行 dim
- 选 2 行 → diff modal（field-by-field Δ + prompt 文本 line-diff + 总分 Δ）
- promote 是显式 button，红线不破（experiment 不自动 promote）

入口：FSSpine `experiments/` group header click（M9.3 留的 inert 入口补上）；URL `?bench=1`，跟 `?eval=<ts>` 一样的 modal 风格。Row click → 现有 EvalMatrixModal（按该 experiment 的 `summary_ts` 路由）。

---

## Scope

**In:**
- 后端：1 个 thin aggregator endpoint `GET /lab/projects/{pid}/bench` + 对称 MCP tool `bench_view`
- 后端：`ExperimentEval.summary_ts: Optional[str]` 字段（M14 风格 audit link，向后兼容）
- 后端：`run_experiment_eval` 写 `meta.json.eval` 时把 `summary.ts` 写进 `summary_ts`
- 后端：legacy fallback — `summary_ts is None` 时扫 `metrics/eval_*/meta.json` 找 `experiment_id == ex_id`
- 前端：新 `<BenchOverlay>` modal，App.tsx 通过 `?bench=1` 挂载（mirror `EvalMatrixModal` 模式）
- 前端：FSSpine `experiments/` group header — 加 "↗ open bench" affordance（不破坏现有 toggleDir）
- 前端：`useBench` Zustand store（cache-first，invalidate-on-mutation hook）
- 前端：双轴 chip rail（hover dim）、matrix 表、selection bar、diff modal（per-field Δ + prompt 文本 line-diff）
- 前端：row click → `pathForEvalMatrix(slug, row.summary_ts)`（复用 EvalMatrixModal）
- i18n：所有新文案中英双语；UI 用通用动词（experiment/prompt/model），不出现 extract / invoice
- TDD：每个 task 先写测试，跑红，再写实现，跑绿

**Out (explicit defer):**
- AutoResearch candidate banner + 🤖 row（design 自承 stub；需 `versions_dir/_candidate/` 跟 experiment 串联，spec §5.2 未完成的迁移）
- `+ new prompt` / `+ new model` chip 的 onClick（chat NL 起新 prompt/model 已经能做）
- 「create experiment」empty row 的 onClick（同上）
- ContextSurface 双卡 prompt + model（独立 follow-up）
- 「open bench」keyboard shortcut（后期视 dogfood 加）
- 多向 diff（A vs B vs C）—— 本期 2-way
- Bench → score CSV export（YAGNI）

---

## 数据契约

### Backend response — `GET /lab/projects/{pid}/bench`

```ts
type BenchResponse = {
  // axis metadata
  prompts: Array<{ id: string; label: string; is_active: boolean; refs: number }>
  models:  Array<{ id: string; label: string; provider_model_id: string; is_active: boolean; refs: number }>
  // column headers — flat schema field names (currently active prompt's schema)
  fields: string[]
  // 同一组 6 个 reviewed filename，跨所有 row 用同一个 — 方便 "扫一列看哪份 doc 老错"
  sample_filenames: string[]   // ≤ 6, lex-sorted reviewed/*.json basenames
  // headline (best row by score)
  headline: { best_score: number | null; best_prompt_id: string | null; best_model_id: string | null }
  // experiments + synthetic baseline
  rows: Array<{
    id: string                          // ex_<id> | "_baseline"
    kind: "experiment" | "baseline"
    prompt_id: string
    model_id: string
    status: "draft" | "ran" | "promoted" | "baseline"
    is_active: boolean                  // matches project.active_prompt_id+active_model_id
    score: number | null                // field_accuracy_macro
    delta: number | null                // vs baseline; baseline row → null
    ran_at: string | null               // ISO
    summary_ts: string | null           // for row click → /p/<slug>?eval=<ts>
    cells: Record<string, {             // field_name → cell
      correct: number                   // count of "correct" or "absent_both" verdicts across reviewed docs
      total: number                     // count of any non-skip verdicts
      strip: Array<0 | 1 | null>        // len ≤ 6, aligned with sample_filenames
    }>
  }>
}
```

**Strip computation rules:**
- 对每行的 `summary_ts` 加载 `metrics/eval_<ts>/cells.jsonl`
- 对每个 `(filename in sample_filenames, field in fields)`：
  - 找所有匹配 `cells.filename == filename AND cells.field == field` 的 verdicts（多 entity 的 doc 有多条）
  - 全是 `correct` 或 `absent_both` → `1`
  - 任何一条是 `wrong / missing / spurious` → `0`
  - 没匹配（doc 不在这个 eval 里） → `null`
- N/M：`correct` = 1-tick 的数量（across ALL reviewed docs，不止 sample 6），`total` = 该 row eval coverage

**Baseline row（synthetic）：**
- 只有当存在 `metrics/eval_<ts>/meta.json` 满足 `experiment_id is None`（活动 baseline 的 eval）时才出现
- `id = "_baseline"`, `kind = "baseline"`, `status = "baseline"`
- `summary_ts` = 最近的 baseline eval ts
- `prompt_id` / `model_id` = 来自 `meta.json`（M14 stamp）或 `project.json.active_*` 兜底

**Delta：**
- `delta = row.score - baseline.score`（如果 baseline 存在）
- baseline 行的 delta = null
- 没 baseline 行时所有行 delta = null

### Backend tool — `bench_view`

签名：`bench_view(slug: str) -> BenchResponse` —— 跟 HTTP 路由共享同一个 service 函数（thin delegate，对称 invariant 维持）。

### `ExperimentEval.summary_ts` 新增

```python
class ExperimentEval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ran_at: str
    score: float
    per_field: dict[str, float] = Field(default_factory=dict)
    per_doc: dict[str, float] = Field(default_factory=dict)
    run_id: str
    coverage: int
    summary_ts: Optional[str] = None   # NEW — link to metrics/eval_<ts>/ (new field, Optional for backcompat)
```

- 旧 `meta.json.eval` 反序列化时 `summary_ts` 为 None（向后兼容）
- `run_experiment_eval` 新跑时写 `summary.ts`
- legacy fallback：bench backend `summary_ts is None` 时扫 `metrics/eval_*/meta.json` 找 matching `experiment_id`，最近一条为准

---

## 文件清单

### Backend (new)

- `backend/app/services/bench.py` — pure aggregator (no I/O wrapping):
  - `def compute_bench(workspace: Path, project_id: str) -> BenchResponse`
- `backend/app/api/routes/bench.py` — thin HTTP route delegating to service
- `backend/app/tools/bench.py` — thin MCP tool wrapping the same service
- `backend/tests/unit/test_bench_service.py` — service unit tests
- `backend/tests/integration/test_bench_route.py` — HTTP integration

### Backend (modified)

- `backend/app/schemas/experiment.py` — add `summary_ts: Optional[str] = None`
- `backend/app/tools/experiment.py` — `run_experiment_eval` writes `summary_ts=summary.ts` into eval blob
- `backend/app/api/main.py` — mount new router
- `backend/app/chat/mcp.py` — register `bench_view` in `build_emerge_mcp` + `_EMERGE_TOOL_NAMES`
- `backend/tests/unit/test_symmetry_invariant.py` — assert `bench_view` ↔ route pair

### Frontend (new)

- `frontend/src/types/bench.ts` — TS mirror of `BenchResponse`
- `frontend/src/stores/bench.ts` — `useBench` Zustand store (load + invalidate + reset)
- `frontend/src/lib/api.ts` — `getBench(slug)` fetcher
- `frontend/src/components/Bench/Bench.css` — `b-*` prefix CSS port from `bench.jsx` styles (only those needed)
- `frontend/src/components/Bench/BenchOverlay.tsx` — modal shell (mirror EvalMatrixModal pattern)
- `frontend/src/components/Bench/BenchTopBar.tsx` — n=N + close button
- `frontend/src/components/Bench/BenchHeadline.tsx` — best score + counts
- `frontend/src/components/Bench/AxisRail.tsx` — chip rail (prompt / model)
- `frontend/src/components/Bench/BenchMatrix.tsx` — matrix table
- `frontend/src/components/Bench/BenchSelectionBar.tsx` — compare button bar
- `frontend/src/components/Bench/BenchDiff.tsx` — 2-row diff modal (per-field bars + line-diff)
- `frontend/src/components/Bench/__tests__/*.test.tsx` — component tests
- `frontend/src/stores/__tests__/bench.test.ts` — store tests

### Frontend (modified)

- `frontend/src/App.tsx` — `?bench=1` URL hook + mount `<BenchOverlay>`
- `frontend/src/lib/slugUrl.ts` — `pathForBench(slug)` helper + `readBenchOpenFromSearch(search)`
- `frontend/src/components/Spine/FSSpine.tsx` — `experiments/` group header secondary affordance (open Bench)
- `frontend/src/stores/chat.ts` — `useChat.handleToolResult` invalidates `useBench` on relevant mutations (promote_experiment, run_experiment_eval, create_experiment, archive_experiment, delete_experiment, write_prompt, switch_active_prompt, switch_active_model, score)
- `frontend/src/i18n/en.ts` + `zh.ts` — `bench.*` namespace

---

## Tasks (TDD)

每个 Task 用单独 subagent 跑：先写测试（红），再写代码（绿），再回归（backend `uv run pytest` + frontend `npm test` + `tsc -b --noEmit`）。

### T1 — `ExperimentEval.summary_ts` + write site

**Test first**:
- `backend/tests/unit/test_run_experiment_eval_summary_ts.py` —
  - `run_experiment_eval` 写 `meta.json.eval.summary_ts == summary.ts`（断言两侧 ts 一致）
  - legacy meta.json（没 `summary_ts` key）反序列化为 `ExperimentEval` 不抛
  - schema `extra="forbid"` 仍然 reject 未知字段（仅 `summary_ts` 是新 known field）

**Code**:
- `backend/app/schemas/experiment.py` 加 `summary_ts: Optional[str] = None`
- `backend/app/tools/experiment.py::run_experiment_eval` 把 `summary_ts=summary.ts` 写入 `ExperimentEval(...)`

**Done when**: 新增测试绿，全量 `uv run pytest` 不退步。

### T2 — Backend bench service (pure aggregator)

**Test first**:
- `backend/tests/unit/test_bench_service.py` —
  - 空项目（无 experiments、无 metrics）→ `rows=[]`, `headline.best_score is None`
  - 1 baseline + 0 experiment → `rows=[{kind:'baseline', is_active:True}]`, baseline delta=null
  - 1 baseline + 2 experiments → 3 rows，experiment 行 delta vs baseline 正确
  - sample_filenames lex-sort、≤6
  - strip 1/0/null 三态：(filename in sample) × (field in fields) 的 cells.jsonl status 聚合
  - multi-entity doc（同一 filename 多 entity_idx）—— any wrong → 0；all correct/absent_both → 1
  - `refs` 计数：跨 experiment 数 prompt/model 引用，archived 不计入
  - legacy summary_ts fallback — experiment.eval.summary_ts=None 但 metrics/eval_<ts>/meta.json experiment_id 匹配 → 能找回

**Code**:
- `backend/app/services/bench.py` `compute_bench(workspace, project_id) -> BenchResponse`
- 复用 `read_experiment` / `list_experiments` / `load_cells_jsonl` 等现成读路径
- 不写盘，纯计算

**Done when**: service tests 绿；`tsc`/lint 类型一致；`uv run pytest backend/tests/unit/test_bench_service.py` 绿。

### T3 — Backend HTTP route + symmetry invariant

**Test first**:
- `backend/tests/integration/test_bench_route.py` —
  - `GET /lab/projects/<slug>/bench` 200 + 形状匹配 `BenchResponse`
  - 项目不存在 → 404
  - safe_slug 路径攻击拒绝
- `backend/tests/unit/test_symmetry_invariant.py` — `bench_view` tool ↔ `/bench` route 对偶 lock

**Code**:
- `backend/app/api/routes/bench.py` —— thin delegate
- `backend/app/api/main.py` mount
- `backend/app/tools/bench.py` —— MCP tool wrapping `compute_bench`
- `backend/app/chat/mcp.py` —— 注册到 `build_emerge_mcp` + `_EMERGE_TOOL_NAMES`

**Done when**: 整套 backend 测试绿，symmetry invariant 不退步。

### T4 — Frontend types + store + API helper

**Test first**:
- `frontend/src/stores/__tests__/bench.test.ts` —
  - `load(slug)` 命中 API 一次；二次调用复用 cache
  - `invalidate(slug)` 让下次 `load` 再 fetch
  - `reset()` 清状态

**Code**:
- `frontend/src/types/bench.ts`（与 backend `BenchResponse` 镜像）
- `frontend/src/lib/api.ts::getBench(slug)`
- `frontend/src/stores/bench.ts`（结构 mirror `useEval`）

**Done when**: store 测试绿，`tsc -b --noEmit` 干净。

### T5 — Bench UI components (matrix + rails + headline + topbar)

**Test first**:
- `frontend/src/components/Bench/__tests__/BenchMatrix.test.tsx` —
  - 给 mock rows 渲染对应行数
  - cell 高分（≥0.9）→ ok class；中（0.75-0.9）→ mid；低 → bad；null cell → 占位
  - hover prompt chip → matrix 里非该 prompt 的行有 `dimmed` class
  - row click 触发 onOpenRow callback
- `frontend/src/components/Bench/__tests__/AxisRail.test.tsx` —
  - active chip 有 ⭐；refs 显示 `·N`
- 空 state（rows=[]）渲染 empty hero

**Code**:
- 上面"文件清单"里 Bench/ 各组件实现
- 样式从 design jsx `styles.css` 的 `/* ── Bench ── */` 段裁剪需要的，转 Tailwind/CSS-var token system（不引入新 raw color）
- 文案走 i18n（en + zh）

**Done when**: 组件单测绿。

### T6 — BenchOverlay + URL/route integration

**Test first**:
- `frontend/src/components/Bench/__tests__/BenchOverlay.test.tsx` —
  - `?bench=1` 时 modal 渲染
  - close button → URL 移除 `?bench=1`
  - ESC 关
  - 项目切换时 modal 自动关（mirror QuickLook pattern）
  - row click 触发 push `?eval=<summary_ts>` 后关 modal

**Code**:
- `frontend/src/components/Bench/BenchOverlay.tsx` — 装配 TopBar + Headline + AxisRail × 2 + Matrix + SelectionBar + BenchDiff
- `frontend/src/lib/slugUrl.ts` — `pathForBench(slug)` + `readBenchOpenFromSearch`
- `frontend/src/App.tsx` — `benchOpen` state + popstate sync + mount

**Done when**: overlay 单测绿，手动 URL 进/退页面无报错。

### T7 — Diff modal (per-field Δ + line-diff)

**Test first**:
- `frontend/src/components/Bench/__tests__/BenchDiff.test.tsx` —
  - 给 2 行（不同 prompt + 同 model）— 渲染 score Δ + per-field Δ bar + "PROMPT TEXT" col
  - 同 prompt 不同 model — 不渲染 prompt diff 段
  - prompt line-diff：新增行高亮，删除行 strikethrough（不引入 diff-match-patch；用 simple line-by-line `aLines.includes(line)` 判断）
  - close → 触发 onClose

**Code**:
- `frontend/src/components/Bench/BenchDiff.tsx`
- prompt 文本化：把 `schema:[{name, description, ...}]` + global_notes flatten 成 `# name\n  description\n...` 文本块（client 端做，data 已经在 useBench 加载 prompts 时拿到）
- 拉两个 prompt 完整 body：第一次实现就在 BenchOverlay 把整 `prompts/{id}` blob 加载到 store（多 fetch 2 次，但只在 modal 打开时；YAGNI 不预 cache）

**Done when**: diff modal 测试绿，2-选 compare 流程跑通。

### T8 — FSSpine entry point

**Test first**:
- `frontend/src/components/Spine/__tests__/FSSpine.bench.test.tsx`（如有 FSSpine 测试目录，否则新建）—
  - `experiments/` group header 旁边渲染 "↗" 按钮
  - 点击 ↗ → `window.location.search` 含 `bench=1`
  - 点击 arrow 仍然 toggle 展开

**Code**:
- `frontend/src/components/Spine/FSSpine.tsx` — `experiments/` group 渲染加一个小 ↗ icon button（右对齐，hover 才显），click → `pathForBench(slug)`
- 不破坏其他 group（仅 `experiments/`）

**Done when**: FSSpine 测试绿，UI 手动验证 hover 显示 ↗。

### T9 — Cross-store invalidation on mutations

**Test first**:
- `frontend/src/stores/__tests__/chat.test.ts` 加 case —
  - mock `mcp__emerge_tools__promote_experiment` tool_result → `useBench.invalidate(slug)` 被调用
  - 同样：`run_experiment_eval`, `create_experiment`, `archive_experiment`, `delete_experiment`, `write_prompt`, `switch_active_prompt`, `switch_active_model`, `score`

**Code**:
- `frontend/src/stores/chat.ts::useChat.handleToolResult` 在现有 invalidate branches 加 `useBench.getState().invalidate(slug)`

**Done when**: chat store 测试绿，全量 frontend 测试不退步。

### T10 — Live verify + ROADMAP closeout

**Test plan (manual, after T1–T9 ship)**:
1. 起 dev 后端 + 前端（CLAUDE.md 端口 8080 / 5173）
2. 在测试 project（如 `默沙东_小票`，已有 experiments）：
   - FSSpine 展开 `experiments/` → 看到 ↗ icon
   - 点 ↗ → BenchOverlay 弹出
   - matrix 显示所有非 archived experiment + baseline 行
   - hover prompt chip → 其他行 dim
   - 点一行 → `?eval=<ts>` modal 上层叠
   - 选 2 行 → compare → diff modal
   - close 各级 modal → URL 恢复
3. dogfood：用浏览器（Claude in Chrome）操作，截一张 `docs/screenshots/2026-05-28-bench-leaderboard-*.png`

**Code**:
- 更新 `docs/superpowers/plans/ROADMAP.md` 加这条 ✅ + commit range
- 移走/划掉 follow-up "Field-diff power-user view (§7.4.1)" + "Experiment detail sheet"

---

## Hard rules cross-check

| Hard rule | 本 plan 处理 |
|---|---|
| 没有 image few-shot | 不引入；Bench 是纯 leaderboard 视图 |
| 没有 bbox / 区域信息 | 不触动 |
| AutoResearch 永不自动 promote | 维持；candidate banner explicit defer |
| Counterexample 永不进 runtime prompt | 不触动 |
| Public API 读 `versions/v{N}.json` | publish path 零改动 |
| 不读取/打印/提交 secrets | bench response 不含 keys / chats |
| Agent brain ↔ Extract LLM 分离 | bench 是纯 read aggregator，不调任何 LLM |
| `schema.json` 只通过 `write_schema` tool 修改 | 不触动 |
| Doc vision is pulled | 不触动 |
| Tool ↔ HTTP dual-form symmetry | `bench_view` 对偶 `/bench` 路由，invariant 锁住 |
| Task-type-agnostic chrome | "Bench" / "experiment" / "prompt" / "model" 全是通用动词，不出现 invoice / extract |

## Insights cross-check (trap notes)

| Insight | 是否触动 |
|---|---|
| #1 `can_use_tool` 强制 | 新 tool 用 `mcp__emerge_tools__` 前缀 |
| #2 `setting_sources=[]` | 不触动 |
| #4 Gemini `additionalProperties` 禁用 | 不触动（bench 不调 LLM） |
| #7 SDK echo ToolResultBlock | 不触动 |
| #8 `safe_project_id` 强制 | `/bench` 路由必须用 |
| #10 `/` 前缀 leading space | 不触动 |
| #11 `resume=...` + session id sidecar | 不触动 |

---

## YAGNI / 显式不做

- AutoResearch candidate banner（需 spec §5.2 未完成的 `versions_dir/_candidate/` → `prompts/_candidate/` 迁移）
- `+ new prompt` / `+ new model` chip onClick（chat NL 起新轴已足够）
- 「create experiment」row 的 onClick（同上）
- ContextSurface 双卡（独立 follow-up）
- Tab pin 分屏（spec §7.4.1 explicit "不做"）
- 多向 diff（A vs B vs C）
- Bench → score CSV 导出
- AutoSearch keyboard shortcut（dogfood 后看）
- 6-tick N 可配（写死 6 跟设计一致）

## Decisions

- **Bench row 包含 synthetic baseline** — 当存在 `experiment_id is None` 的 metrics eval 时，加一行代表 active prompt × active model 的"production line"。所有 experiment delta 都 vs 这条 baseline。无 baseline eval 时所有行 delta=null（不强制 user 先跑 baseline）。
- **`summary_ts` 写到 ExperimentEval** —— 而不是另开 `eval_link.json` sidecar：因为 `extra="forbid"` 的 model 已经 strict，Optional 字段添加是 backwards-compatible 的最小变更（M14 风格 audit link）。
- **strip 数据源走 cells.jsonl** —— 不引入新的 per-doc-per-field 聚合存储。每次 bench 渲染时实时 scan（项目典型 < 50 reviewed × < 30 fields × ≤ 10 experiments，O(15000) cell verdicts，单机毫秒级）。
- **prompt 文本 diff 用 client-side simple line-diff** —— 不引入 `diff-match-patch`。本期只展示「新增行高亮 + 删除行 strikethrough」，跟现有 EvalCompare 风格一致。
- **FSSpine `experiments/` group header 加 ↗ icon** —— 不替换现有 toggleDir 行为。SSU：阅读时不弹意外 modal，主动 click ↗ 才弹。
- **URL 用 `?bench=1` 而非 `?bench=<...>`** —— Bench 是 project-level，无 sub-state；URL 简单。
- **修改 row 不去尝试 lazy partial recompute** —— mutation 来时 store invalidate，下次 open 重新拉。Bench API 单次 ~50ms，无需复杂的 incremental update。

## Migration / backward compat

- 旧 `meta.json.eval` 无 `summary_ts` 字段：反序列化 OK（Optional），bench backend fallback 扫 `metrics/eval_*/meta.json` 找匹配 experiment_id（最近一条胜出）
- 旧 metrics 文件（`eval_<ts>.json` flat file）—— legacy fallback：无 cells.jsonl，所以 strip 全 `null`。Bench row 仍可显示，cell 显示 `—`
- 完全新项目（无 experiments、无 reviewed、无 metrics）—— Bench overlay 显示 empty hero "no experiments yet — type `/improve` or create one"

---

## Test footprint expected

- Backend: +6 unit tests (service) + +3 integration (route) + +1 symmetry invariant case = +10
- Frontend: +3 store tests + +4 component tests + +1 overlay integration = +8
- Total +18 tests，全量 `uv run pytest` + `npm test` + `tsc -b --noEmit` 不退步

---

## Closeout checklist (T10)

- [ ] ROADMAP.md 加 "2026-05-28 — Bench leaderboard" 行，状态 ✅ + commit range
- [ ] ROADMAP follow-ups: "Field-diff power-user view (§7.4.1)" → 划掉，标 "closed by 2026-05-28 bench"
- [ ] ROADMAP follow-ups: "Experiment detail sheet (FSSpine experiment row click)" → 标 "closed (group header → Bench; individual row click → EvalMatrix)"
- [ ] design-decisions.md 加一条「Bench is project-level horizontal; EvalMatrix is per-experiment per-doc grid — two-tier nav」
- [ ] live dogfood screenshot
- [ ] CLAUDE.md 不动（无新 hard rule）
