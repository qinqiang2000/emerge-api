# Agent应用UI优化

_Started 2026-05-11 15:21 UTC_

---

## User

# 背景
本项目就是可纯agent驱动的应用
左侧边栏里面原设计是 项目和 项目对应的文件系统关键信息。

# 问题
1. 没有查看历史chat记录的地方，请判断有无必要
2左侧边栏 信息挺多，有无必要优化？
3. 文档不一定是Invoices，可以是任意文档（合同、小票、名片、报关单等等），怎么优化表达

请先给计划，我同意在执行

## Assistant

_[tool: list_files]_

_[tool: local_ls]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: read_file]_

# 改进计划

我已读完 `index.html`、`app.jsx`、`pieces.jsx`、`data.jsx`，理解了当前结构。下面是针对你三个问题的方案，等你确认再动手。

---

## 问题 1 ：是否需要"历史 chat 记录"

**判断：需要，但不应做成单独的大区域。**

理由：
- 当前左栏是「项目 + 文件树」，每个项目天然就是一段长对话的容器（agent 在持续与 schema/docs 互动）。
- 真实用户场景里，回看"上一次 /improve 跑了什么"、"两小时前我为什么改了 due_date"是高频需求。
- 但塞一个独立的"chat list"会让左栏更挤。

**方案：在左栏每个项目下、文件树上方插入一个轻量的「sessions / runs」时间轴**（折叠状态下只占 3-4 行）。每条 = 一次有意义的对话回合（init / extract / review batch / improve / publish），带时间戳和结果摘要。点击 = 滚动到 conv 中那段，或在中栏顶部加面包屑「viewing: 2h ago — /improve run」。
- 当前 active 项目展开 sessions；其它项目折叠。
- 不破坏现有 FS 视图，而是叠加一个"时间维度"的入口。

---

## 问题 2 ：左侧栏信息瘦身

当前左栏同时显示：5 个项目 + 当前项目所有文件（docs/、reviewed/、versions/、metrics/、schema.json、README.md），共 ~20 行。确实偏密。

**方案（分两层折叠 + 减字）：**
1. **项目列表**：去掉每行的 `meta`（"42 docs"）那种冗余尾巴 — 只在 active 项目上保留状态点（live/draft/empty 用一个小色点表达）。
2. **文件树**：默认只展开 `docs/`（用户最常看的），其它目录（`reviewed/`、`versions/`、`metrics/`）折叠为一行带 count。
3. **省略 README / schema.json 这种"系统文件"** 到一个底部 footer 区，用更弱的视觉权重。
4. 整体把 mono 字号从 12.5 → 12，行高收紧。
5. 加上问题 1 的 sessions 时间轴，整体行数反而能控制在 ~14 行内（看起来更轻）。

---

## 问题 3 ：文档不仅是 Invoice，要泛化表达

当前几乎所有 demo 文案都假定是 invoice（vendor_name / line_items / tax_id 等），这会让原型显得"只能做发票"。

**方案 —— 双管齐下：**

**A. 数据层泛化：** 把 5 个 PROJECTS 改成真正异构的样本：
- `invoices/` (发票) — 保留作主线
- `contracts/` (合同) — schema：parties, effective_date, term, renewal_clause, governing_law
- `receipts/` (小票) — schema：merchant, total, items[], date
- `business-cards/` (名片) — schema：name, title, company, email, phone
- `customs-declarations/` (报关单) — schema：HS_code, country_of_origin, declared_value, consignee

切换 active project 时，右侧 `schema.json` 和 conv 中的工具调用文案也跟着换（最少把第二个/第三个项目对应的 schema 也写出来作为 tweak 可切换）。

**B. 表达层去"invoice 化"：**
- Empty hero 里 starter 文案从"Extract invoices..."→"Extract any structured document..."加上 3 个跨类型示例（合同条款、名片信息、报关单）。
- Help popover、composer placeholder、顶栏 crumbs 改成"document"/"folder"中性词。
- Brand tagline（如果有）改为"agent-native document API"（项目标题已经是这个，强化它）。

**C. 视觉提示：** 在 FS spine 顶部加一行小字 "any document type — invoices, contracts, receipts, cards…"，让用户秒懂泛用性。

---

## 执行顺序（如果你批准）

1. 改 `data.jsx` — 多项目异构 schema + sessions 数据
2. 改 `pieces.jsx` — FSSpine 重构（折叠 + sessions + 瘦身）、Topbar/Composer 文案中性化
3. 改 `app.jsx` — 项目切换时联动 schema / conv 文案
4. 改 `index.html` 里 EmptyHero 和 conv 默认内容里的 invoice 措辞
5. 不新建文件，所有改动收敛在现有 4 个文件里

确认后我开始动手；若你只想做其中 1-2 项也告诉我。

## User

好。只实现
- 问题1
方案：中栏顶部增加claude design的 两个图标，Chat History和New 插图，如图。 只显示当前 active 项目有关的history
- 问题2
左侧栏信息瘦身，取你上面该问题方案的 1，2

## Assistant

_[tool: view_image]_

_[tool: snip]_

_[tool: str_replace_edit]_

执行：先加 sessions 数据，再加 ConvHeader 组件 + 历史下拉，最后瘦身 FSSpine。

_[tool: read_file]_

_[tool: grep]_

_[tool: snip]_

_[tool: str_replace_edit]_

_[tool: str_replace_edit]_

_[tool: snip]_

_[tool: str_replace_edit]_

_[tool: str_replace_edit]_

_[tool: snip]_

_[tool: done]_

_[tool: get_webview_logs]_

_[tool: snip]_

_[tool: fork_verifier_agent]_

完成。改动：

**问题 1（中栏顶部图标 + 历史）**
- 在 conv 区域左上角加了浮动的「⏱ Chat history」「+ New」两个图标按钮（Claude 风格，hover 显示 tooltip）。
- 点击 history 弹出气泡，列出**当前 active 项目**的 sessions（按时间倒序，含 kind 标签 / 标题 / 摘要 / 时间戳，当前会话高亮）。
- 数据放在 `data.jsx` 的 `SESSIONS` 里，按项目隔离。切换项目时弹窗自动关闭。
- 点 + 跳到 empty hero（开新对话）。Review 场景下不显示这两个按钮，避免遮挡。

**问题 2（左栏瘦身）**
- 项目列表去掉了「42 docs」之类的 meta 文字；只在 active 项目上保留一个状态色点（live=moss 绿 / draft=ochre 橙 / empty=灰）。
- 文件树默认只展开 `docs/`，其它目录（`reviewed/`、`versions/`、`metrics/`）折叠为一行带 count，点击展开。

## User

中栏顶部图标 + 历史：这个放到右上角，而不是左上角

## Assistant

_[tool: snip]_

_[tool: str_replace_edit]_

_[tool: str_replace_edit]_

_[tool: snip]_

_[tool: done]_

已移到右上角。

