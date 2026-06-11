# 2026-06-11 — Audit Board（审核白板 + evidence 引文 + job 化 + Cowork 阶梯）

> **Status**: ✅ B0-B5a code landed 2026-06-11（backend 1560 passed；前端 +43，14 失败为既有 scrollIntoView）。**Live dogfood**：① B3 board ✅ prod 真实数据两轮过（百胜audit1，7 规则 29 证据 23 页）。一轮修 fit 失效/长条布局/怼脸 zoom（`ec7893e`）；二轮按用户反馈定型交互（`3998cd8`）：**store 自愈暖层**（miss 的 (doc,page) 走 GET /textlayer 暖 OCR 再重定位——报价单.pdf 实为扫描件，暖后引文全命中，"未命中"质量问题就此关闭）、**单规则圈注**（场景只铺页图，点行按需挂该规则虚线圈+连线，全画太乱）、虚线描边无填充、行点击兜底跳文档页、文档按页数升序排（跨文档规则相邻）、全屏。截图 `docs/screenshots/2026-06-11-board-*`；② B4 Cowork 圈图 ✅（跑通但发现 **Cowork 不内联渲染工具图**——图给模型不给用户;补了服务端自暖+虚线样式对齐+board 深链,`0229b5e..`）；③→B5b 直接落地（跳过 hello gate）：`ui://emerge/audit-board.html` 单文件 SVG 白板 + HMAC capability 数据面（`board_view.py` + `/lab/board-view/{token}` 双格式:浏览器→白板/fetch→JSON）+ `_meta.ui` 注入。**服务端全链验证 ✅**（prod tools/list 实测带 `_meta.ui`;standalone 白板真机圈+连线+联动全过,截图 `2026-06-11-appsboard-*`）。**iframe 就地渲染 ✅ 通关（2026-06-11 深夜,官方付费 Cowork）**：对话内完整白板（规则栏+magenta 圈+缩放 HUD）。三层闭环缺一不可:① `_meta.ui.resourceUri` 挂 `read_audit_report`（gateway 版 Cowork 不渲染,官方付费 Cowork 渲染——账号面差异实锤）;② **CSP**:`_meta.ui.csp.connectDomains/resourceDomains` 必须在 **resources/read 的 contents[] 侧**（声明侧不够;且 `Resource(meta=)` 静默丢参,必须 model_validate 走 `_meta` wire key）;③ **CORS**:`/lab/board-view/*` 全响应（含 4xx）带 `ACAO:*`（middleware 兜底;CSP 放请求出沙箱、CORS 放响应回来,缺一即 "Failed to fetch" 且后者服务端能看到请求、前者看不到——分流诊断法）。尺寸:渲染后发 `ui/notifications/size-changed`(720px)+`ui/request-display-mode` 全屏按钮。诊断器留存:list_tools 时 log `session.client_params`（挂 uvicorn.error;stateless 模式下 initialize 参数常为 None,别指望）。
> **Seed**: `2026-06-11-audit-board-seed.md`（白板表达用户原话 + scope 合并依据）。
> **Design 基础**: `2026-06-10-audit-design.md`（A0/A2/A3 全 shipped）+ `2026-05-29-field-source-grounding.md`（locate 三档 + render-only 红线）+ `2026-06-09-filesystem-over-mcp.md`（job 化 follow-up + capability URL 模式）。
> **Scope**: ① `run_audit` job 化；② `RuleCheck.evidence` 引文（additive optional）；③ locate-quotes render 路由；④ lab 前端 audit board（excalidraw）；⑤ Cowork 阶梯（服务端合成标注图兜底 + MCP Apps hello-world gate）。
> **P0.5 折入说明**: 原 P0.5 的「N source 引擎遍历」**已 shipped**（`app/match/engine.py:124-143` 已循环全部 source_projects + 贪心 1:1，勘探确认）；剩余的「核对卡前端」被 board 重塑。**v1 board 只表达 audit report**（真实用例驱动：百胜/KFC 审核），match 核对板（anchor↔source 配对连线）是同一 board 的第二数据源，留 follow-up——AuditReport 有规则↔evidence 结构，表达力检验更充分。

---

## Spike 结论（2026-06-11，本 plan 的依据）

### Spike A — excalidraw embed ✅ 可行

`frontend/src/spike/BoardSpike.tsx`（dev-only，`?boardspike=1` pre-auth 挂载，静态页图）+ Playwright 实测：

- **React 19 + Vite 5 挂载 ✓**（`@excalidraw/excalidraw@0.18.1` peerDeps 显式支持 React 19；已装）。
- **多文档页图铺板 ✓**：5 张页图（110dpi dataURL ~1MB 总量）列布局、locked、自由 pan/zoom；程序化 pan 60 帧 avg 16.5ms（满 60fps）。
- **bbox→板元素对齐 ✓**：ellipse 按 `(imgX + rx0*w*scale)` 映射（与 `BBoxRect` 同公式）落点准确。
- **双向联动 ✓**：规则行点击 → `scrollToContent(els, {fitToViewport, animate}) + updateScene({appState:{selectedElementIds}})`；画布点 ellipse → `onChange` 读 `selectedElementIds` 反查规则行。
- **跨文档连线 ✓**：arrow skeleton `start/end: {id}` 绑定两 ellipse + label（✓/✗）+ dashed。

**四个 trap（实现必须遵守）**：
1. `convertToExcalidrawElements(skeletons, {regenerateIds: false})` —— 默认会重生成 id，规则↔元素联动全断（spike 第一坑）。
2. **选中元素会浮出属性面板岛盖住画布左上**——产品 board 用 `UIOptions` 裁剪工具栏/面板（保留手绘笔），或聚焦高亮不走 selection（叠加高亮元素）。
3. Vite 必须 `define: {'process.env.IS_PREACT': JSON.stringify('false')}`（已加进 `vite.config.ts`）。
4. evidence 高亮用**低透明度填充**（`fillStyle:'solid', opacity:40`）不是纯描边——可见性 + 可点中（2px 描边在缩小后点不中）。

另：excalidraw 字体/资产默认走 CDN——prod 国内 VPS 不可靠，`window.EXCALIDRAW_ASSET_PATH` 自托管进 `public/`；excalidraw 必须独立 lazy chunk（+213 npm 包，只在开 board 时加载）。

### Spike B — MCP Apps ✅ 机制确认，真机渲染待 gate

- 规范（GA 2026-01-26）：tool 声明带 `_meta.ui.resourceUri` → `ui://` 资源（mimeType **`text/html;profile=mcp-app`**）→ 沙箱 iframe 渲染 → postMessage JSON-RPC（`ui/initialize` 握手；UI 侧用 npm `@modelcontextprotocol/ext-apps` 的 `App` 类，打进单文件 HTML）。外源（页图）需资源侧 `_meta.ui.csp.resourceDomains: [origin]` 声明。
- **python 侧零新依赖**：`mcp==1.27.2` 的 `Tool`/`Resource`/`TextResourceContents`/`CallToolResult` 全有 `meta`(alias `_meta`)；`build_mcp_server` 已有 handler 替换先例（`app/mcp_server.py:138-155` 换 ListToolsRequest、`@server.list_prompts()`）——注 `_meta` + 注册 resources 同一模式。ext-apps server SDK 只是 thin helper，不需要。
- 客户端支持：Claude web / Claude Desktop / VS Code 等。⚠️ ext-apps#671 报过 Desktop **Windows** 渲染 bug（用户是 macOS，留意即可）。
- **真机渲染未验证** → B5a hello-world gate（利用现有 prod OAuth connector，比另起 ext-apps 示例服务器快）。

---

## Phases（按序执行；B0-B2 后端可并行，B3/B4 依赖 B1/B2）

### B0 — run_audit job 化（已批小件，先行）

大组审计 judge 趟 ~70s 超 Cowork 客户端工具超时 ~60s（`2026-06-09-filesystem-over-mcp.md` 2026-06-11 dogfood）。幂等窗/in-flight 去重（`75f1322`/`0a9a9d7`）只是止血，job 化是正解，互补不冲突。

- `app/jobs/runner.py::JobRunner.start` 现在只认 `skill="autoresearch"`（`runner.py:100-136`）——加 `"audit"` 分支：job fn 调 `app/tools/audit_run.py::run_audit(ws, slug, filenames=params.get("filenames"))`（它自带幂等窗 + in-flight 去重，job 化后双保险）。完成时 emit `JobEvent("ended", {overall, run_id, checks_n})`；报告本体照旧落 `audits/{run}/report.json`，客户端经 `read_audit_report` 取全文。
- `JobInfo` 的 autoresearch 特有字段（`best_macro_f1` 等）保持 Optional 空——不为 audit 改 schema。
- 工具面不加新工具：`start_job`/`get_job` 已注册（`tools/__init__.py:1314-1336`）且在 minimal surface。skill（`emerge_extractor.md` audit 小节）补编排指引：**组内文档总页数 > 8 或上次趟时接近超时 → `start_job(skill="audit")` + `get_job` 轮询 + `read_audit_report` 取报告**；小组照旧直接 `run_audit`。渲染契约不变。
- Tests：`test_jobs_audit.py`——start→done 拿到 report 戳；error 路径（缺规则）status=ERROR + error_code；`get_job` 轮询语义。回归 autoresearch job 全绿。

### B1 — RuleCheck.evidence 引文（schema + judge + L1 + AuditCard）

**红线姿势**：evidence 是**纯文本逐字引文**（同 grounding tier-2 `_source` 设计，`INSIGHTS:field-source-grounding`）；bbox 仍永不进任何 prompt/tool result；坐标只在 B2 的 render 路由里活。

- `app/schemas/match.py`：新 `AuditEvidence {doc: str, page: Optional[int] = None, quote: str}`（extra=forbid）；`RuleCheck` 加 `evidence: list[AuditEvidence] = []`（additive optional——存量 report JSON 读入不变）。
- `app/match/audit.py::audit_group`：`_AUDIT_SCHEMA` 每条 check 加 `evidence: [{doc, page, quote}]`；system prompt 教 judge：每条结论给出依据的**逐字原文片段 ≤120 字**（保留原语言、不改写、标注出自哪个文档/页码；判 unclear 可空）。index 对齐回填时带 evidence；缺失/越界照旧宽容（`feedback_llm_array_alignment_by_index`）。
- `app/match/audit_l1.py::try_l1`：L1 命中也合成 evidence——operand 解析到的字段**值**当 quote、`doc` 来自 operand 的 doc 匹配（值匹配是 locate 档 0/1 的强输入，引文缺页码也能定位）。
- `tools/audit_run.py`：报告落盘原样带 evidence（`AuditReport` 不用动，checks 已是 `list[RuleCheck]`）。
- 前端 `AuditCard.tsx`：`adaptAuditReport` 透传 evidence；每条规则行下渲染引文次行（`「quote」— doc · pN`，ink-4 小字）。卡片**只显示文字**，不画框——板才是空间表达。
- skill 渲染契约（headless）：逐条清单每条后附 `依据: 「quote」(doc pN)` 一行。
- Tests：`test_audit_judge.py` 扩展（evidence 回填齐/缺）；`test_audit_l1.py` 扩展（L1 合成 evidence）；`test_audit_run.py` 报告带 evidence 落盘 + 存量无 evidence report 读入兼容；前端 adapter 单测。

### B2 — locate-quotes render 路由（grounding 机器复用）

把「引文 → 页面 rects」从 field-path 耦合里解出来，给 board / 合成图 / MCP App 三个消费者共用。

- `app/tools/locate.py` 加 `locate_quotes(workspace, project_id, filename, *, quotes: list[dict]) -> list[QuoteLocation]`：每项 `{page?: int, quote: str}`；复用现有内部三档（引文当 source 主锚跑档 0/1：NFKC 归一 + rapidfuzz + 数字 token 对齐），page hint 优先、miss 扩全文；返回 `{index, rects, page, status, score}`。**不碰 `locate_fields` 现有行为**（高精度低召回调参原样，`project_locate_precision_pass`）。
- `app/api/routes/locate.py` 加 `POST /lab/projects/{slug}/docs/by-name/{filename:path}/locate-quotes`。**镜像 locate 的全部纪律**（INSIGHTS 四条全适用）：**非 @tool**（rects 不得进 agent context；route-without-tool 合法无需 exempt）、`asyncio.to_thread(lambda: asyncio.run(...))` 跑 worker 线程、`skip_ocr=True` 只读 warm sidecar。
- Tests：`test_locate_quotes.py`——exact / 归一化命中 / page hint 优先→扩全文 / none 回退 / 多 span 并集；route 404/400 envelope。

### B3 — lab 前端 audit board（excalidraw）

- 依赖落定：`@excalidraw/excalidraw@0.18.1`（已装）；excalidraw 资产拷贝进 `frontend/public/excalidraw-assets/` + 入口处 `window.EXCALIDRAW_ASSET_PATH`；board 整体 `React.lazy` 独立 chunk。
- **入口**：`?board=1` URL 参数 overlay（对标 `BenchOverlay` 的 URL↔mount 模式，App/AppShell 持有 search 状态）；`AuditCard` 头部加 `open board ↗`（有 report 才显示）。Chrome 通用动词：board/check/rule，不出现审核业务词。
- **数据流**：`GET /lab/projects/{slug}/audit/latest` → report（group 文件名列表 + checks + evidence）→ 每 doc 页图 `pdfPageUrl(slug, fn, p)`（150dpi 渲染缓存路由，session cookie 同源）→ fetch→dataURL→`api.addFiles` → 列布局 locked image 元素（spike 布局算法直接搬）。页数从 `list_docs`/sidecar 取（`useDocs` 已有）。
- **evidence 高亮**：对每条 check 的每个 evidence，按 `(doc, page hint)` 调 B2 locate-quotes（按 doc 聚合一次请求）；命中 rects → 低透明度填充 ellipse（pass=moss / fail=rose / unclear=ochre，hex 从 token CSS var 读出）；`status:none` → 退化为页面角落规则编号 badge（永不硬失败）。跨 doc 双 evidence → dashed arrow + ✓/✗ label（`regenerateIds: false`！）。
- **联动**：左栏 checks 列表（复用 AuditCard 行渲染）↔ board：行点击 → scrollToContent + 高亮；画布点击 evidence 元素 → 行高亮（spike 已验证两向）。聚焦高亮**不依赖 selection**（避开属性面板岛 trap）：叠加一个粗描边 ring 元素，聚焦切换时增删。
- **手绘保留**（同事精神红利）：`UIOptions` 裁剪到 选择/手/画笔/橡皮 + zoom；用户新增元素（涂鸦/批注）序列化存 `audits/{run}/board_notes.json`（与 report 同目录；report 是派生缓存，notes 文件在重跑 run 后由前端提示「上次批注来自旧 run」并可带走——v1 简单挂最新 run）。「涂鸦→teaching signal 喂 review note」留 follow-up。
- **board 状态 store**：`useBoard` Zustand（cache-first load/invalidate，对标 `useBench`；selector 雷区 `project_zustand_selector_fresh_ref_loop`）。
- spike 文件退役：`src/spike/BoardSpike.tsx` + `public/_boardspike/` 删除，App.tsx spike 分支移除（被正式 board 替代）。
- Tests：vitest——adapter/布局纯函数（bbox→元素坐标映射）、useBoard store、checks 行联动 handler；`tsc -b` 干净。excalidraw 画布本体不做 jsdom 渲染测（canvas 限制），live 验证走 dogfood。

### B4 — Cowork 阶梯 v1：服务端合成标注图（普适兜底）

所有客户端能显示图——比 MCP Apps 便宜且立即可用。

- `app/tools/audit_board_render.py::render_audit_board(ws, slug) -> dict`：读最新 report + evidence → 对 group 内每 doc 各页跑 `locate_quotes`（进程内直调，不走 HTTP）→ 页 PNG 上画圈 + 规则编号 + ✓/✗ 色彩 → 每 doc 一张合成图（页可纵拼，cap 高度），`fit_image_for_agent` 预算内返回 ImageBlock 列表 + 文字图例（编号↔规则文本）。
- 画图引擎：加 `pillow` dep（fitz pixmap 不支持矢量叠绘；PIL 是纯轮子成本低）。
- **红线姿势**：圈活在像素里，坐标文本不进任何 prompt/result ✓；这是 agent 显式调用的 pull（非 auto-attach）✓；合成图是派生渲染产物（不落盘，即调即合成；或落 `audits/{run}/_board_render/` 派生缓存可 rmtree）。
- 三形对称：`@tool render_audit_board`（readOnly? 不——产出图、调 locate，标非 destructive 非 idempotent；**不进** `_TOUCHES_PROVIDER`，locate 是 LLM-free）+ HTTP twin `GET /lab/projects/{slug}/audit/board-render` + symmetry 登记；进 minimal surface（audit 套件同桶）。
- skill 渲染契约：headless 下用户说「圈给我看/在图上标出来」→ `render_audit_board`；browser 下一句摘要 + 提示开 board（`→ board`）。双分支齐全（interface-aware 红线）。
- Tests：mock locate → 合成图尺寸/张数/图例对齐；无 report → `audit_no_report` envelope；symmetry +1。

### B5 — MCP Apps（gate 后接入）

- **B5a hello-world gate（小件）**：`EMERGE_MCP_APPS=1` 开关下，`build_mcp_server` 给 `read_audit_report` 工具注 `_meta.ui.resourceUri="ui://emerge/hello.html"`（在现有 `_filtered_list_tools` 里补一行 `t.meta`），注册 `@server.list_resources()`/`@server.read_resource()` 返回内嵌十几行 hello HTML（mimeType `text/html;profile=mcp-app`）。部署 prod → **用户在 Claude Desktop（现有 connector）真机验证渲染**（`feedback_milestone_dogfood_handoff`：human dogfood）。不渲染/渲染坏 → B5b 不动，阶梯停在 B4。
- **B5b board app**（gate 通过后）：`ui://emerge/audit-board.html` = 单文件 bundle（vite-plugin-singlefile + `@modelcontextprotocol/ext-apps` App 类）。**精简只读 pan/zoom canvas 版**（不带 excalidraw——iframe 里不需要手绘编辑，1.5MB excalidraw 不值）：`app.ontoolresult` 收 report JSON → 页图走 **presigned view URL**（反向复用 `app/tools/upload_url.py` HMAC capability 模式：`GET /lab/view/{token}`，签 `{ws, slug, fn, page, exp}` 15min，无鉴权 redeem；mint 发生在 run_audit/read_audit_report 工具结果里附 URL 列表——纯 URL 文本，红线安全）→ rects 走 presigned locate URL（同 token 模式包 locate-quotes，**bbox 只进 iframe，不进 tool result**）。资源 `_meta.ui.csp.resourceDomains: [public_base_url]`。
- B5b 任务粒度在 gate 通过后细化（可能独立 plan）；本 plan 交付到 B5a。

---

## 红线（全程遵守）

- **bbox 永不进 prompt / tool result / agent context**：evidence 是纯文本引文；locate-quotes 是 render 路由非 @tool；B4 的圈在像素里；B5b 的 rects 只进 iframe（presigned render URL）。
- **doc vision pulled**：B4 合成图 = agent 显式 pull；不给任何路径加 auto-attach。
- **lab=prod 一致 / judge 直连不回 SDK**：B1 只动 judge 的 response_schema 与 system prompt，调用路径不变。
- **prompt 是真相**：规则仍只经 `write_audit_rules`；evidence 是 judge 输出不是规则输入。
- **不物理删用户数据**：`audits/` 派生缓存可重跑；`board_notes.json` 是用户批注（删除走 trash 语义，重跑 run 不抹）；`reviewed_audit.json` 不动。
- **任务类型无关 chrome**：board/check/rule/evidence，不出现报价单/红章。
- **三形对称**：`render_audit_board` tool+HTTP+symmetry；locate-quotes 是 route-without-tool（合法，注释注明理由，同 locate 先例）。
- **Tailwind 语义 token**；excalidraw 画布内 hex 从 token CSS var 取值（注释指回 token 名）。
- **新增依赖**：前端 `@excalidraw/excalidraw@0.18.1`（已装）；后端 `pillow`（B4）。无其它。

## Out of scope（明确不做，防 scope 爬）

- match 核对板（MatchResult 数据源接 board）——follow-up，等 audit board 表达力被真实用例检验。
- 板上涂鸦 → review note teaching signal 回路——follow-up。
- 1:N 分期付款、A1 自动凑齐批量审核、prod `/v1/{pid}/audit`——照旧后置。
- B5b 完整 board app——B5a gate 通过后再细化。
- excalidraw 协同/多人——无此需求。

## Verify

- 每 phase：`cd backend && uv run pytest -q` 全量绿 + `cd frontend && npm test && npx tsc -b --noEmit` 干净。
- B3 live dogfood（human，`feedback_milestone_dogfood_handoff`）：百胜audit1 真实组（prod 或本地迁移副本）开 board——5 条规则圈注落点、双向联动、手绘批注存取；截图存 `docs/screenshots/2026-06-11-board-*.png`。
- B4：Cowork 真机让 agent 圈图（用户驱动）。
- B5a：用户 Claude Desktop 验证 hello app 渲染。
