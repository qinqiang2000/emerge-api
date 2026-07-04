# 审单核对白板（review board）— A 方案

Software 3.0 审单结果的人类复核体验：给**结构化/文本文档**新增「核对表」白板渲染分支。
不是页图圈注（文本 doc 无光栅），而是「原件 + 圈注」哲学在结构化数据上的等价物——
**两张原始表格（采购发票明细 + 结算细单）横排、问题行红框高亮 + 同号徽章跨表呼应**。

## 决策（用户已拍板）

- **形态**：后端 tool 产**自包含 HTML**（内联 CSS + token 变量，1:1 复刻原型），
  chat 卡片 iframe srcdoc 呈现，全屏 board 同源。明暗靠 `prefers-color-scheme`。
- **入口**：新 tool `render_review_board(slug)` + 新路由 `?reviewboard=1`。与现有
  audit `?board=1`（canvas 圈注）并存互不干扰——形态完全不同，隔离最清晰。
- **每单独立**：白板**左侧栏 doc list（select，每单一项带 verdict 徽标）**，
  点选 → 右侧 iframe 渲染那一单的自包含 HTML。每单一份 HTML。
- **精简**（用户「注意」）：单页只要 ①结算总单ID ②驳回/通过理由那一行 ③发票表 ④结算表。
  两表**横排**（不竖排，避免滚动）。去掉原型的 legend 长篇、程序核对摘要折叠、footer 啰唆段。

## 数据链路（纯计算，0 LLM）

每单数据来自两个文件（按 `docs/*.json` 文件名配对 `predictions/_draft/{filename}.json`）：

- **文档** `docs/审核数据_{id}.json`：
  - `发票主信息` → 单头（供应商名、含税总金额、金税发票号码、总单备注）
  - `采购发票明细行[]` → 发票原始表（货物名/规格/单位/数量/含税单价/含税金额/税率/细单ID）
  - `结算明细行[]` → 结算原始表（商品名/规格/单位/数量/单价/行金额/行类别/备注/细单ID）
  - `程序预计算.商品组配对明细[]` → **哪个商品组问题**（`数量合计一致:false` 的组），
    每组含发票侧/结算侧的 `细单ID[]`（用于在两张原始表里定位要高亮的行）+ 数量比。
- **预测** `predictions/_draft/{filename}.json`：
  - `entities[0].pass` → verdict（true=通过/false=驳回）
  - `entities[0].reason` → 驳回/通过理由行
  - `entities[0].issues[].product` → 交叉验证问题商品（与预计算的问题组对齐，产出徽章编号）

**高亮定位**：问题商品组 → 取其发票侧/结算侧 `细单ID[]` → 在 `采购发票明细行`/`结算明细行`
按 `采购发票细单ID`/`结算细单ID(SUSETDTLID)` 匹配行 → 标 `hit` class + 同号徽章。
数量单元格额外标 `qty-hit`。徽章编号 = 问题组序号（1-based）。

红线遵守：坐标只活渲染层（这里无坐标，纯表格行高亮）；文本 doc 前端不 grounding；
UI chrome 任务类型无关（tool 名 `render_review_board` 用通用动词，不出现 invoice/extract）。

## 实施步骤

### 1. 后端渲染核心 `backend/app/tools/review_board_render.py`（新文件）

```python
async def render_review_board(workspace: Path, slug: str) -> dict[str, Any]:
    """读 docs/*.json + predictions/_draft/*.json，逐单拼自包含 HTML。
    返回 {
      "docs": [{"id","verdict":"pass|fail","supplier","amount","invoice_no","reason"}],
      "html_by_id": {id: 自包含HTML字符串},
      "tally": {"pass": n, "fail": m},
      "model_label": "deepseek-v4-flash",
    }
    0 LLM：全部纯计算。无预测的 doc 跳过（不产 card）。"""
```

- 纯 Python 拼字符串（无模板引擎依赖，emerge 无前端模板）。CSS/token 变量内联，
  直接取原型 `<style>` 块（paper/ink/ochre/rose/moss + `@media prefers-color-scheme`），
  裁掉用不到的 legend/aux/footer 样式。
- `_build_doc_html(doc_json, pred_json)` → 单单 HTML：印章 chip + 单头一行 + reason 一行 +
  横排两表（`display:flex; gap` 或 grid 两列，各自 `overflow-x:auto`）。
- `_hit_settle_ids(precalc) -> (badge_by_inv_id, badge_by_settle_id)`：从问题组的细单ID
  建行→徽章号映射，渲染表格时查表决定 `hit`/`qty-hit`/徽章。
- HTML 转义所有文本值（`html.escape`）——文档内容是不可信数据（红线：external content）。

### 2. Tool 注册 `backend/app/tools/__init__.py`

- 仿 `t_render_audit_board` 加 `t_render_review_board`，加进 `_tools` list。
- description 写清 rendering contract 摘要（browser: 一句摘要 + `→ board`；
  headless: 逐单文字版）。工具返回：headless text 分支给**完整文字叙述**
  （每单：结算总单ID · verdict · reason · 问题商品组「发票 X 单位 vs 结算 Y 单位，数量比 Z」），
  外加 `interactive board: {base}/p/{slug}?reviewboard=1` 深链。
- HTML **不进 tool text 返回**（体积大 + 无意义给 agent）；HTML 只走 HTTP 给前端 iframe。

### 3. HTTP 对称 `backend/app/api/routes/review_board.py`（新文件）+ 注册

- `GET /lab/projects/{slug}/review/board-render` → `render_review_board`，返回同 dict。
- 加进 `_TOOL_HTTP_MAP`（`test_symmetry_invariant.py`）：
  `"render_review_board": ("GET", r"^/lab/projects/\{slug\}/review/board-render$")`。
- 路由挂进 `app/main.py`（仿 audit_board router include）。

### 4. 前端全屏 board `frontend/src/components/ReviewBoard/ReviewBoardOverlay.tsx`（新）

- 轻壳（**非 excalidraw**，不进 Board/ 那个重 chunk）：左栏 doc list（select，
  rose/moss 圆点徽标 + 结算总单ID），右侧 `<iframe srcDoc={html_by_id[selectedId]} />`。
- 数据经新 store `stores/reviewBoard.ts`（仿 `board.ts` cache-first，选择器纪律：
  不在 selector 里 `?? []`/`.filter`/对象字面量——repo trap）。
- lazy import，ESC/关闭/项目切换 → onClose 剥 `?reviewboard=1`。

### 5. 路由 helper `frontend/src/lib/slugUrl.ts` + 挂载 `AppShell.tsx`

- 加 `readReviewBoardOpenFromSearch` / `pathForReviewBoard(slug)`（仿 `?board=1` 那对）。
- AppShell 加 `reviewBoardOpen` state + popstate 同步 + Suspense overlay 挂载
  （仿 `boardOpen` 段落）。

### 6. Chat 卡片 `frontend/src/components/Chat/ReviewBoardCard.tsx`（新）+ dispatch

- adapter 模式（仿 AuditCard）：识别 `render_review_board` 结果 → 卡片头
  「审核白板 · N 单（驳回 m / 通过 k）· model」+ 「打开白板 ↗」按钮（pushState
  `?reviewboard=1`）+ 单列表（每单 verdict 徽标 + 结算总单ID + reason 首句）。
  JSON 不识别 → null（不劫持通用渲染）。
- `MessageList.tsx` `HoistedToolCard` 加 `render_review_board` → `ReviewBoardCardAdapter`。

### 7. Skill 渲染契约 `backend/app/skills/domains/match_audit.md`

- 新增 `render_review_board 的 rendering contract` 段：browser 一句摘要 + `→ board`；
  headless 逐单完整文字（结算总单ID · verdict · reason · 问题组数量对比）+ interactive 深链。

### 8. 测试

- `backend/tests/unit/test_review_board_render.py`：对 4 份 dogfood 文档跑 render，
  断言 verdict/tally 正确（2994530/2996030 fail，2981974/3002856 pass）、
  问题商品组高亮行 ID 命中、HTML 含转义、无预测 doc 跳过。
- `test_symmetry_invariant.py` 自动覆盖新 tool↔route（加 map 条目即过）。
- 前端 `ReviewBoardCard.test.tsx`：adapter 正/负识别。
- 全量 `cd backend && uv run pytest -q` + `cd frontend && npm run build`。

## 验收（用户标准）

1. 人复核 10 秒内定位失败商品组和关键数字（左栏选单 → 右侧红框行 + 徽章）。
2. chat 问审核结果：browser 一句摘要 + 白板卡片；headless 完整文字版。
3. 4 份 dogfood 文档白板渲染与原型视觉一致（明暗双主题），横排两表精简版。

## 不做（本期）

- B 方案（迁 audit 形态）——进 roadmap，多规则上线时再做。
- 白板批注/涂鸦（review board 是只读核对视图，不引入 excalidraw canvas）。
- 原型的 legend 长篇 / 程序核对摘要折叠 / 规则归因 rulenote（精掉；
  3002856 的「历史驳回属更价规则」这类注记若需要，后续按需加，非本期）。
