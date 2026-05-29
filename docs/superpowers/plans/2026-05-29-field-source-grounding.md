# Field source grounding — 点字段，看原文在哪

> Plan created 2026-05-29. Builds on M2A (review mode), M12 (`app/eval/normalize.py`),
> the textlayer/translate render layer (`app/tools/textlayer.py` + `TextLayer.tsx`).
> Read `docs/superpowers/plans/ROADMAP.md` first.

**Goal (one sentence):** review 时点一个字段，在 PDF 上高亮它的来源区域 —— 用
LangExtract 模式（模型出文本、系统做 post-hoc 文本→span 对齐），坐标永远只活在
render 层，never 进任何 LLM prompt。

## Why this shape (业界对照)

- Google 自家的 Gemini-powered 抽取库 **LangExtract** 故意**不用** Gemini 原生 bbox
  能力：模型只吐 verbatim 文本，库做 char-offset 对齐（`WordAligner` + difflib 模糊），
  对不齐的标 `char_interval=None` 直接过滤。PyMuPDF 官方 grounding 文章同理（fitz
  `search_for` 把模型出的文本解析回精确 rect）。让模型生成坐标 = 易幻觉 + 把空间模板
  灌进 prompt —— 建过 Gemini 的人做生产 grounding 都选文本对齐。
- emerge 的 render 底座**已经齐了**：`extract_textlayer` 用 fitz `get_text("dict")` 抽出
  自带 bbox 的 line-spans；`TextLayer.tsx` / `TranslateGhost` 已有 `(x0/pageW)*100%` 贴图
  公式（随 zoom/rotate 自动缩放）。缺的只是"字段值 → 命中 span → rect"这一段解析。
- `_evidence` **没进** Gemini controlled-generation schema（`extract.py:46-58` 故意省略，
  避开 OpenAPI-3.0 的 `additionalProperties` 限制），所以演进它的 shape 不触发 provider
  约束 —— 纯靠 `_EXTRACT_SYSTEM` prompt + `ExtractionOutput` pydantic 校验。

## 三档匹配（一个共享 resolver）

resolver 输入：doc + page hint + 字段值（+ 可选 `_source` 引文）+ 该范围的 fitz/OCR
spans。输出：每字段 `{rects, status, score}`。匹配范围 = **evidence 标的页优先，失败再
扩全文**（复用模型已给的 page 整数缩小搜索域，跨页同值不易错位）。

- **档 0 — 文本匹配**：value 对 page spans 做 NFKC 归一后 exact/substring，失败走
  `rapidfuzz`（后端已有依赖）滑窗模糊（阈值起步 ~85）。命中 spans 并集 → rects。
  覆盖发票号 / 人名 / 原样日期 / 行项目等 verbatim 字段。
- **档 1 — 类型感知归一化匹配（"value≠源文本"主力）**：对每个 span 调
  `normalize.py::normalize_equivalent(value, span_text, field_type=…)`，命中即源。
  `"15 Jan 2024"↔"2024-01-15"`、`"1,250.00"↔1250`、全角↔半角 —— M12.x 修过的等价类
  全部白拿，**零 prompt/schema 改动**。
- **档 2 — `_source` 逐字引文**：给残差（真正派生的 sum、自由文本摘要、无字面锚点的
  分类）。模型顺手吐它依据的 **verbatim 原文片段**（纯文本，不是坐标），resolver 把
  引文当 value 再跑档 0/1。只有这一档需要演进 `_evidence` + 改 prompt + 改红线措辞。

所有档位带 `status ∈ {exact, fuzzy, normalized, quote, none}`。`status=none` →
前端回退到现有 page 级 click-to-page，**永不硬失败**（见
`MEMORY:feedback_llm_array_alignment_by_index`）。

## Hard-rule posture（红线如何处理）

- **bbox 仍永不进任何 prompt。** locate 是 **render-only HTTP 端点，不是 @tool**
  （和 `textlayer` / `translate` 完全一致）—— 这样 rects 不进 agent SDK context，
  红线"bbox 永不进 extract/labeler/proposer/autoresearch"原样成立。symmetry invariant
  只强制"@tool 必须有 route"，不强制反向，所以 route-without-tool 合法、无需 exempt。
  **任务里显式注释：不要把 locate 包成 tool**，否则 rects 会泄进 agent context。
- **红线修订（档 2 触发）**：CLAUDE.md 现行 "_evidence 只携带 page 整数" → 改为
  "_evidence 携带 page 整数 + 可选 verbatim source 引文（纯文本，非坐标）；bbox 仍永不
  进任何 prompt"。用户 2026-05-29 已显式授权（选"一次性做全三档"）。INSIGHTS.md 补一条
  解释为何 source 是文本不是坐标、为何 locate 不做成 tool。

---

## Tasks

### Backend

**T1 — `app/tools/locate.py` resolver core（pure，单测先行）**
- `flatten`：复用 `extract.py::_collect_leaves` 的思路把 entities 摊成 `(path, value, field_type)` 叶子。
- `locate_fields(workspace, pid, filename, *, entities, evidence, lang?) -> list[FieldLocation]`，
  `FieldLocation = {entity_index, path, rects: list[[x0,y0,x1,y1]], page, status, score}`。
- 每字段：先取 evidence page 的 spans（`extract_textlayer(..., page=hint)`）跑档 0→1→2；
  miss 则按页迭代其余页（复用 textlayer 缓存；电子 PDF 是纯 fitz、便宜）。性能 guard：
  full-doc 扩展只对 page-hint 缺失或该页未命中的字段触发；首触发的 scanned-OCR 成本接受，
  慢了再议。
- char-interval → span 并集：value 跨多 line 时返回多个 rect。
- 复用 `app/eval/normalize.py`（`normalize_equivalent` / `normalize_scalar`）做档 1；
  `rapidfuzz` 做档 0 模糊。
- 单测：三档各一例 + none 回退 + 多 span 并集 + evidence-页优先再扩全文 + 派生字段
  （value 无字面来源）走 quote/none。

**T2 — render HTTP 端点（非 @tool）**
- `POST /lab/projects/{slug}/docs/by-name/{filename}/locate?page=int`，
  body `{entities, evidence}`（前端传当前显示 tab 的值，保持 tab-agnostic + 无状态）。
  返回 `list[FieldLocation]`。route 形状镜像 `textlayer.py` / `translate.py`
  （`project_workspace` + 404/400 envelope）。
- 文件头注释 + plan 引用：**故意不注册为 @tool**（理由如上）。
- `app/api/__init__` 注册 router。

**T3 — `_source` 引文：演进 evidence + prompt（Tier 2，碰红线）**
- `schemas/extraction.py`：`ExtractionOutput.evidence` 接受 union —— 旧 `{field: int|null}`
  与新 `{field: {page: int|null, source: str|null}}` 都收，`model_validator` 里归一成
  内部 `{page, source}` 形（int → `{page:int, source:None}`，兼容磁盘上旧 reviewed/ blob，
  无需 migration，符合 `MEMORY:test_data_deletable`）。length 校验保留。
- `tools/extract.py::_EXTRACT_SYSTEM`：把 `_evidence` 说明从"field→page 整数"改成
  per-field `{page, source}`，`source` = 它实际读到的**逐字原文片段**（≤120 字，保留原语言，
  不要改写）；纯派生字段 `source=null`。强调仍**不要**输出任何坐标/bbox。
- `tools/surface_state.py:103-111`：evidence 读取改走新 accessor（兼容两形）。
- 回归：现有 extract / score / review 用到 `_evidence[i][field]` 取 page 的地方全部过
  accessor。

**T4 — 红线 + INSIGHTS 文档**
- `CLAUDE.md`：改 "Hard rules" 里 `_evidence` / bbox 那条措辞（page-only → page + 可选
  verbatim source 引文；bbox 仍永不进 prompt）。
- `docs/superpowers/INSIGHTS.md`：新增条目——为何 source 是文本不是坐标（LangExtract/
  fitz 对照）、为何 locate 是 render 端点不是 tool（否则 rects 泄进 agent context）。

### Frontend

**T5 — fetch helper + 类型**
- `lib/locate.ts`：`fetchLocate(projectId, filename, page, entities, evidence) -> FieldLocation[]`。
  类型与后端对齐。

**T6 — 共享 bbox rect 原语（hoist）**
- TextLayer / TranslateGhost / 新 LocateHighlight 现在是三个 bbox-定位层 →
  按 `MEMORY:feedback_three_patches_means_missing_noun` 抽 `<BBoxRect>`（吃
  `bbox/pageW/pageH` → `%` style）。TextLayer + TranslateGhost 改用它（保持像素行为不变），
  LocateHighlight 复用。

**T7 — locate 状态 + 渲染**
- 轻量 `useLocate` store：按 `(filename, page, tabKey)` 缓存结果；`focusedPath` 状态。
- `PdfViewer` 的 PageOverlays 加 `<LocateHighlight>` 层（在 raster 之上、textlayer 之下），
  画 focusedPath 的 rects。rect 在他页 → 复用 `goPage` 自动滚。
- 高亮样式走语义 token（见 `MEMORY:project_design_token_roles`：ochre-soft 仅限菜单填充，
  这里用 ochre ring/outline + 低 alpha 高亮，**子决策**：定稿前对照 token 角色确认，不要
  raw color）。

**T8 — 字段 → locate 接线**
- `FieldRow` / `Section` / `FieldEditor`：字段行 focus/click → `useLocate.focus(path)` →
  触发 fetch + 高亮。现有 `p{page}` 按钮保留，作 `status=none` 的 page 级回退。
- `stores/review.ts::open()` 时清 locate 缓存 + focusedPath（随 doc 重置，对齐 tab state）。
- locate 结果按当前显示 tab 的 entities/evidence 取（draft/pending/experiment/reviewed）。

### Verify

**T9 — 测试**
- backend：T1 单测 + 端点测（含 evidence-页优先→全文、none 回退）。
- frontend：useLocate store + BBoxRect + 字段 focus→高亮 渲染测。
- 全量：`cd backend && uv run pytest -q`；`cd frontend && npm test && npx tsc -b --noEmit`。

**T10 — live dogfood（human，见 `MEMORY:feedback_milestone_dogfood_handoff`）**
- 真实电子 PDF：点各字段，量**每档命中率 / 残差率**（尤其档 1 对日期/金额、档 2 对派生
  字段）；确认 scanned 页（text layer 空）干净回退到 page 级。
- 截图存 `docs/screenshots/2026-05-29-locate-*.png`。

## Out of scope（明确不做）

- Gemini 原生 bbox 输出（违背"坐标进 prompt"——见 Why）。
- 派生 sum 的"高亮所有贡献 cell"（档 2 先吐单个最相关锚点或 null；多锚点后续）。
- locate 做成 @tool（会把 rects 泄进 agent context）。
- 把 source 引文喂回 extract few-shot（违背"no example I/O pairs"红线）。
