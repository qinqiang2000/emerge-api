# 2026-06-12 — Board 几何统一 + 涂鸦→teaching signal

> **Status**: ✅ shipped 2026-06-12（G1 `94993c1` / G2+G3+D1 `21d002f` / D2+D3 `97974e5` + 收尾 commit）。backend 1357 全绿；前端 638 过（14 失败均既有 FSSpine/ReviewBar）；tsc 干净。
> **Live dogfood（web :5173 + standalone board-view，本会话亲测）**：① chat 重跑审核 → 新 run 带 8 条 evidence，excalidraw 板圈/线/布局像素级如前；② 板上画圈 + 写「金额已核对，注意下月涨价」→ `board_notes.json` 落 anchor（源单位 rect）→ `GET /audit/latest` 返回 `board_annotations`，圈住的「43460.00 费用总计」反查成纯文本，**响应零坐标**；③ chat 问「看一下最新审核报告」→ agent 主动复述板上圈注 + 手写批注（D3 契约生效）；④ standalone `/lab/board-view/{token}` v10 自然加载完整渲染。截图 `docs/screenshots/2026-06-12-doodle-signal-board.png` / `2026-06-12-board-view-v10.png`。
> **过程 trap（已进 INSIGHTS + 静态测试）**：G2 初版 `const { GEOM } = BoardGeom` 与注入几何块的顶层 `const GEOM` 全局词法冲突 → 主块整块 SyntaxError 静默不执行（页面卡 initializing…）；node --check/new Function/eval 全测不出（各自独立作用域），headless Chrome 二分定位。修复 = 直接引用共享作用域绑定；防回归 = `test_board_app_no_global_lexical_collision_with_geometry`。
> **承接**: `2026-06-11-audit-board.md` 两个 follow-up：①几何三份手工同步（v9 commit `707e3b4` "手写 SVG 版漏搬 web 的 ray∩ellipse trim" 即第三次同形 patch——missing noun 信号）；②「板上涂鸦 → review note teaching signal」（plan §B3 显式留的回路）。
> **顺序依据**: 涂鸦 anchor 需要「板坐标 → (doc, page, 源矩形)」反向映射，几何统一是它的地基——先 G 后 D。

## 现状勘探结论（2026-06-12）

三个几何消费者，两套半实现：

| 消费者 | 位置 | 几何 |
|---|---|---|
| web excalidraw board | `frontend/src/components/Board/boardScene.ts` | 常量+layout+mapping+trim，有 vitest |
| MCP Apps iframe 白板 | `backend/app/skills/board_app.html`（手写单文件，serve 时 `_board_app_html()` 读取；URI 带内容 hash 版本化） | 同一套公式手抄一份（v9 刚补完 trim 漏搬）；布局用 A4 占位 + img onload 校正，k 经 `srcScale=pg.w/iw` 推 |
| Pillow 合成图 | `backend/app/tools/audit_board_render.py` | 独立常量已漂移：`_RECT_PAD=6` vs web `ELLIPSE_PAD=8`（web pad 是板单位，换算源像素 ≈14.5px，差 2.4×）；`_OUTLINE_W=5` vs web 3.5/SCALE≈6.4 |

涂鸦侧已有资产：user 元素经 `OWN_ID_RE` 过滤后防抖存 `audits/{run}/board_notes.json`（GET/PUT `/lab/projects/{slug}/audit/board-notes`，render-layer，无 @tool）；stale-run 提示已实现。review note 机制（`reviewed/{fn}.json` notes → autoresearch proposer 消费）是 extraction 域的；audit 域只有 `reviewed_audit.json`（规则真值布尔）——涂鸦信号走**agent 可见文本**路线，不硬塞 extraction notes。

## G — 几何统一（single source: `board_geometry.js`）

**架构**：单真相文件 `backend/app/skills/board_geometry.js`（与 board_app.html 同目录，随后端打包）。三消费者三种接入：

- **形态**：classic script（无 export——便于整段注入 inline `<script>`），顶层定义纯函数，结尾 `globalThis.BoardGeom = {...}`。常量写成严格 JSON 字面量夹在 `/*GEOM-JSON-BEGIN*/ {...} /*GEOM-JSON-END*/` 标记间（`const GEOM = /*GEOM-JSON-BEGIN*/{...}/*GEOM-JSON-END*/;`）——Python 端 regex 截取 + `json.loads`，零 JS 运行时。
- **内容**：`GEOM` 常量（SCALE/COL_GAP/ROW_GAP/PAGES_PER_COL/ELLIPSE_PAD/ARROW_GAP/STROKE_W/STROKE_ARROW/DASH/RENDER_DPI）+ `pxPerPtFor(ext)` + `layoutPages(docs, scale)`（参数化页尺寸——web 给实测 raster dims，iframe 给占位后校正）+ `unionRect(rects)` + `evidenceEllipse(rects, page)`（返回 {x,y,w,h,cx,cy,rx,ry} 两种消费形态通吃）+ `rayEllipseTrim(a, b, gap)` + `crossDocPairs(centers)`（贪心 stride-2 配对）+ `anchorForBounds(bounds, laidPages)`（**新**，D 阶段用：板坐标反查 (doc, page, 源单位 rect)，中心点落页判定）。

### G1 — 抽取模块 + web 接入
- 新建 `backend/app/skills/board_geometry.js`（上述内容，从 boardScene.ts 平移公式，行为零变化）。
- frontend 接入：vite/vitest alias `@board-geometry` → 该文件（side-effect import）+ `frontend/src/components/Board/board-geometry.d.ts` 类型声明（`declare module` + global BoardGeom）。`boardScene.ts` 删除重复实现，改薄适配层：re-export 共享函数/常量，**保持现有导出 API 不变**（BoardOverlay/测试不动）；excalidraw skeleton 组装（buildPageSkeletons/buildCheckOverlays/buildFocusRing/id 约定/颜色）留在 boardScene——那是 excalidraw 方言，不是几何。
- 现有 `boardScene.test.ts` 全绿（行为不变的回归网）+ 新增 anchorForBounds 向量测试（含跨页/页外/非 PDF k=1）。
- `npx tsc -b --noEmit` 干净。

### G2 — iframe 白板接入（消灭手抄）
- `board_app.html`：几何段替换为注入占位 `/*__BOARD_GEOMETRY_JS__*/`；layout/ellipse/trim/配对改调 `BoardGeom.*`（iframe 特有的 onload 校正、reflow 编排、SVG 绘制保留）。debug HUD bump v10。
- `mcp_server.py::_board_app_html()` serve 时把占位替换为 `board_geometry.js` 文件内容（lru_cache 照旧；URI hash 算在注入后的最终 HTML 上——几何变更自动 bust host 缓存）。
- pytest：`_board_app_html()` 无占位残留、含 `BoardGeom`、`/lab/board-view/{token}` HTML 响应同样完整。

### G3 — Pillow 接入 + 漂移闸门
- 新建 `backend/app/tools/board_geom.py::load_geom()`：解析 GEOM 标记段（lru_cache）。
- `audit_board_render.py`：`_RECT_PAD`/`_OUTLINE_W`/虚线比例改由 GEOM 推导——**语义统一为源像素空间**：`pad_src = ELLIPSE_PAD/SCALE`、`stroke_src = STROKE_W/SCALE`、dash on:off 比对齐 web 的 10:7。视觉对齐 web 板（修复 2.4× pad 漂移）。
- 漂移闸门 pytest：GEOM 可解析、必备键齐、`board_geometry.js` 与 `board_app.html` 不再含本地几何常量定义（regex 断言手抄死透）。
- `test_audit_board_render.py` 按新常量调整。

## D — 涂鸦→teaching signal

**设计**：涂鸦的教学对象是 **agent 同事**（Chat 能完成一切），不是某张表单。回路 = 用户在板上圈/写 → 前端落 anchor → 后端把 anchor 反查成**纯文本**（圈住的原文 + 用户手写字）→ `read_audit_report` 返回 `board_annotations` 段 → agent（chat/Cowork/headless 同权）把它当用户反馈行动（按用户意图改规则 via `write_audit_rules`、或给 doc 加 review note、或重审）。

**红线姿势**：rect 从板（board 单位）→ board_notes.json（render-layer 文件，本来就存元素坐标）→ 后端 sidecar 反查（服务端内存）→ **出口只有文本** `{doc, page, kind, user_text?, region_text?}`。坐标永不进 tool result / prompt。

### D1 — 前端 anchor
- `BoardOverlay` 保存 user 元素时（现有防抖管道），对每个元素调 `BoardGeom.anchorForBounds`：板坐标 → 命中页 → 源单位 rect。`board_notes.json` 体加 `annotations: [{id, doc, page, rect, kind, text?}]`（additive；`elements` 原样保留作回放）。text 元素带 `text`；freedraw/形状只有 anchor。落不到页上（画在空白处）→ `doc:null` 仍存（digest 渲染为"板上空白处批注"）。
- PUT 体积上限 1MB 校验照旧覆盖新字段。
- vitest：anchor 计算 + 保存管道组装（纯函数层）。

### D2 — 后端 digest（rect→text，出口纯文本）
- 新建 `backend/app/tools/audit_notes.py::digest_board_annotations(ws, slug, run_id) -> list[dict]`：读 `audits/{run}/board_notes.json` 的 `annotations`；有 anchor 的经 warm sidecar（`extract_textlayer(..., skip_ocr=True)`）取该页 spans，**span bbox ∩ rect 中心点包含**判定圈住的文字，拼 `region_text`（≤200 字，超截断）；text 元素直接 `user_text`。无 sidecar/无命中 → region_text 省略，不硬失败。
- `read_audit_report`（tool）结果加 `board_annotations` 段（仅当非空）：每条 `{doc, page, kind, user_text?, region_text?}`——**无 rect**。HTTP twin 经 symmetry 自动继承。
- pytest：fixture sidecar + 假 board_notes → digest 正确；**断言结果序列化后不含 rect/坐标键**；空 notes / 旧格式（无 annotations 键）兼容；text-only 元素；anchor 落空白处。

### D3 — skill 契约（interface-aware 双分支）
- `emerge_extractor.md` audit 小节：`board_annotations` 出现时 = 用户在板上留的反馈，**主动复述并提议行动**（改规则草案给用户确认 / 加 review note / 重跑审计）；browser 分支一句摘要 + `→ board`；headless 分支逐条 `① doc pN 圈注「region_text」+ 手写 "user_text"` 完整输出。
- 渲染契约测试照现有 skill 测试惯例（如有）。

## Out of scope（防爬）
- iframe 白板内涂鸦（MCP Apps 版仍只读 pan/zoom）。
- 涂鸦自动写 `reviewed/{fn}.json` notes——agent 经对话确认后用现有工具写，不做静默直写（AutoResearch 永不自动 promote 同理）。
- match board / 旧 run 批注迁移。

## Verify
- 每 phase：`cd backend && uv run pytest -q` 全绿 + `cd frontend && npm test -- --run && npx tsc -b --noEmit` 干净。
- Dogfood（web :5173，本会话自测）：开真实 audit 项目 board → 圈一笔 + 写一句 → `board_notes.json` 落 anchor → HTTP 调 read_audit_report twin 看 `board_annotations` 文本正确、无坐标。
- iframe 白板回归：`/lab/board-view/{token}` 浏览器开板，圈注/连线/缩放如 v9。
