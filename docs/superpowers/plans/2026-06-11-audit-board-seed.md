# 2026-06-11 — Audit/Reconcile Board 种子（白板表达 + P0.5 + job 化）

> **Status**: 🌱 seed — 新会话从这里起一份正式 plan（先读本文 + 引用的 plans/memory，再 spike，再写 plan）。
> **User idea (2026-06-11, verbatim 意涵)**: 审核/对账结果用白板（excalidraw 类）表达——类似 doc view，点击每条规则结果，圈出**两个文档**各自的对应位置；多文档需要放大/拖动，嵌入白板可能是好的表达容器；若是好表达，Cowork 类客户端怎么承接（探索更丰富的展示接口）。
> **Scope 合并**: 原定 P0.5（对账核对卡前端 + N source 引擎遍历，见 `2026-06-10-matching-p0-impl.md` §Out + `2026-06-09-doc-matching-design.md` P0.5）+ 大组审计 job 化（`2026-06-09-filesystem-over-mcp.md` follow-up：judge 趟 ~70s 超 Cowork 客户端工具超时 ~60s）。白板想法**重塑** P0.5 的表达形态：核对"卡"→ 核对"板"。

## 三件已有资产连线（不是新发明）

1. **Grounding 机器复用**：`2026-05-29-field-source-grounding.md` + memory `project_grounding_eager_at_produce` / `project_locate_precision_pass`。文本→span 三档对齐、locate 无状态 render 路由、前端 `<BBoxRect>` 原语（TextLayer/TranslateGhost/LocateHighlight 三层共用，再加一层 board）。审计版 = judge 每条 verdict 附 evidence 引文 `[{doc, page?, quote}]`（**纯文本，红线安全**——同 grounding tier-2 `_source` 引文设计），render 层 locate 到各 doc bbox → 画圈 + 连线 + 规则标签。
2. **AuditCard/MatchCard 已存在**：board 是它们的空间形态。点规则行 ↔ board 高亮联动。
3. **红线步步合规**：bbox 只活渲染层（judge schema 只加文本引文）；doc vision pulled；`RuleCheck` 加 `evidence` 为 additive optional。

## 表达容器：excalidraw embed vs 自建 pan/zoom canvas（spike 定）

- excalidraw（MIT npm）白送：缩放拖动/选择、手绘风（贴 paper/ink token）、**人可在板上圈一笔** → 存回 review note = "correction as teaching signal" 延伸到审核（同事精神红利，超出查看器）。代价：scene 管理、图片走 dataURL/URL、与现有 review overlay 的状态桥。
- 自建：PDF viewer + BBoxRect + 多文档 pan/zoom 容器。单文档分页语义改多文档布局，工作量未必小。
- 倾向 excalidraw，spike 验证：多页 PDF 页图铺板性能、bbox 覆盖层对齐、点击联动。页图用 `pdf_render_page` 缓存。

## Cowork 承接阶梯（interface-aware 延伸）

1. **MCP Apps（已 GA 2026-01-26，MCP 首个官方扩展；Claude/Claude Desktop 已支持）**：tool result `_meta.ui.resourceUri` → `ui://` HTML 资源在聊天内渲染交互 UI；官方 ext-apps 示例有 pdf-server/map-server。emerge remote MCP（Streamable HTTP + OAuth 已就绪）加 apps 扩展：run_audit/run_match 结果带 board 视图，文档页图走 **presigned view URL**（上传 capability-URL 模式反向用：mint 短时效签名查看 URL）。Spike 注意：2026-05 有 Claude Desktop Windows 渲染 bug 报告（ext-apps#671）。
   - 参考：modelcontextprotocol.io/extensions/apps/overview · blog.modelcontextprotocol.io/posts/2026-01-26-mcp-apps · claude.com/blog/interactive-tools-in-claude · github.com/modelcontextprotocol/ext-apps
2. **服务端合成标注图**（v1 兜底，便宜且普适）：圈/连线直接合成到页面 PNG，作 image block 返回——所有客户端能显示图。
3. 文字表（现契约，已 ship）。

## 折入的 job 化（已批）

大组审计 `run_audit` 走 `start_job`/`get_job` 模式（工具秒回 job_id + agent 轮询），解 judge 趟时 > 客户端超时；与 in-flight 去重/幂等窗（已 ship `75f1322`/`0a9a9d7`）互补不冲突。小件，可先行。

## 新会话启动清单

1. 读本文 + `2026-06-09-doc-matching-design.md` + `2026-06-10-matching-p0-impl.md` + `2026-05-29-field-source-grounding.md` + INSIGHTS 组不变条目。
2. Spike A：excalidraw embed 可行性（页图铺板 + bbox 对齐 + 点击联动）。Spike B：MCP Apps 在 Claude Desktop 真机渲染验证（用 ext-apps 官方示例最小复现）。
3. 写正式 plan（P0.5 board + evidence 引文 schema + job 化 + Cowork 阶梯），按 ROADMAP 流程执行。
