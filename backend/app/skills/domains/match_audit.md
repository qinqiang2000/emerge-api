<!-- domain skill: reconciliation + compliance audit — pulled via read_skill("match_audit") -->
# Document matching (reconciliation) + Audit（合规审核）

## Matching

Cross-check one **anchor** document set against one or more **source** sets —
e.g. invoices ↔ {payments, purchase orders, receipts}. Matching sits ON TOP of
extraction: it reads documents you've already extracted, it does not re-extract.
Use when the user says "对账" / "核对" / "发票和付款/采购单对一下" / "reconcile" /
"哪些发票没收款 / 缺单据".

1. `create_match_project(name, anchor, sources)` — `anchor` and each of
   `sources` must be slugs of EXISTING extract projects (both sides already
   have docs + extractions). Returns `{slug}`. The match project references
   them; it has no docs of its own.
2. `write_match_prompt(slug, mappings, rules)` — the **matching rules are a
   prompt** (key field-mappings + NL rules), versioned like an extract prompt.
   `mappings` is keyed by SOURCE slug; each entry lists `{anchor: <anchor
   field>, source: <source field>, tol}` where `tol.type` ∈ `exact` |
   `number` (abs tolerance, strips currency/commas) | `date_days` (±days).
   `rules` is NL guidance for the L2 judge (e.g. "订单号是主键，必须精确对上；
   商户名不同写法但同一公司视为一致"). To tune matching, edit mappings/rules —
   same as teaching extraction by editing description/global_notes.
3. `run_match(slug)` — judges candidate pairs (rules first; LLM tie-break only
   on the ambiguous middle), assigns 1:1 per source. Returns a summary
   `{cards, complete, partial, unmatched, orphans}`.
4. `save_reviewed_match(slug, anchor_doc, expected)` — confirm the true pairing
   for one anchor doc (`expected` = {source_slug: true_filename | null}; null =
   correctly unpaired). Ground truth for scoring.
5. `score_match(slug)` — per-source precision/recall + doc_completeness against
   the reviewed set.

**Rendering contract**:
- **headless** (`interface: headless`): render the **reconcile cards as a
  table** — one row per anchor doc, one column per source (✓ matched filename /
  ✗ missing / ~ mismatch), plus an `overall` column (complete/partial/unmatched).
  Then list **orphans** per source (source docs no anchor claimed = unexpected
  extras). When a card is `partial`/`unmatched`, name which source is missing.
  After `score_match`, print per-source precision/recall + 整单完整率 as a small
  table. Never dump raw JSON — the table IS the deliverable.
- **browser** (`interface: browser`): lead with a one-line summary ("对账完成：12
  张发票，9 全配 / 2 部分 / 1 未匹配，3 张孤儿凭证"), THEN — until the lab reconcile
  view (P0.5b) ships there is no UI card to fall back to — render the **same
  table as the headless branch** so the user sees the per-anchor detail in chat.
  (When the reconcile UI lands, this browser branch drops back to summary-only
  and the card UI takes over; the headless table is unaffected.)

## Audit（合规审核）— matching 之上的规则层

对**一个审核项目里的一组关联文档**跑一套审核规则（合规检查），逐条判 pass/fail。用在
"审核 / 核对合规 / 这笔业务过不过审 / 报价单和收货单/订单对一下规则"。规则是 NL（用户
列几条），judge **看文档原图**（含红章等视觉）逐条判。文档**类型开放**（报价单/收货单/
订单/发票/付款单/物料单… 任意），规则在文档之间，不绑类型。

**一个审核项目 = 一笔业务的一组文档**。把这一笔业务的所有相关文档（报价单+收货单+
订单+…）**全部上传进同一个项目**的 docs/——**绝不拆成多个项目**（"报价单一个项目、
收货单一个项目"是错的，再来文档就无限膨胀）。再来文档？往这个项目里加。

1. 建项目（普通项目即可），把这一笔业务的所有文档上传进它的 docs/（拖拽/附件→promote）。
   **提取不是前置**——审核 judge 直接看文档原图。文档碰巧 `/run` 提取过，字段会作为
   **辅助提示**附给 judge（数字更准），但没提取也能审核。
2. `write_audit_rules(slug, audit_rules)` — `audit_rules` 是规则列表，每条一句 NL
   （"报价单甲方为环胜电子商务（上海）"、"报价单加盖合同专用章（红章）"、"报价单费用总计
   ==收货单折扣后含税金额"、"项目抬头与备注关键字一致"、"项目周期含订单完成日期"）。规则
   是版本化 prompt——改规则就是调审核（同改 description 教提取）。
   **规则必须组不变（group-invariant）**：写的是文档角色之间的**关系**（"完工报告封面
   抬头与报价单项目抬头关键字一致"），不是当前这组文档的**字面值**（"需包含 Y25、
   2月疯四"——下组文档换了活动名这条就错误地 fail）。落笔前自问："这条对**下一组**
   文档还成立吗？" 实例值（具体抬头、金额、日期）是 judge 运行时从图里读的事实，
   不进规则。例外：用户明说的全局常量（固定甲方名、必须盖红章）本来就是组不变的，
   可以写死。你为了把用户的粗规则磨精确而 `read_doc_image` 看文档是合法的——但
   看到的实例值用来**理解规则意图**，不是用来钉进规则文本。
   每条也可以是对象 `{rule, level?, check?}`：
   - `level`: 默认 `critical`（fail 即整体不过）；用户表达"这条只是提醒/不卡审核"
     → `"warning"`（fail 只警告，不挂整体）。
   - `check`: 可选的**确定性判定 spec**——规则明显是 固定值断言 / 跨文档数值相等 /
     区间包含 时附上，引擎在字段已提取在手时直接判（不花 judge、理由可解释）：
     `{type:"eq", left:{doc,field}|常量, right:{doc,field}|常量, tol?}` 或
     `{type:"range", value, low, high}`（三处各可为 `{doc,field}` 或常量；`doc`
     按文件名或唯一子串认）。字段缺/认不出 doc 时该条自动整条交 judge，无须处理。
     **宁可全 judge，不可错 spec**——拿不准结构就写纯 NL 字符串；spec 写错会产生
     确定性误判，比多花一次 judge 贵得多。
3. `run_audit(slug)` — 审本项目 docs/ 里的**整组文档**（或 `run_audit(slug, filenames=[…])`
   只审指定几份）。带 `check` 且字段在手的规则先走确定性判定（报告里
   `decided_by:"l1"`），**剩余规则** judge **一趟**读每份原图（原文为准，含视觉如红章；
   多页文档全页进 judge，理由可引用页码）
   + 可选已抽字段（提示）→ 逐条 {pass/fail/unclear + 理由} + 整体三态：任一 critical
   fail → `fail`；仅 warning fail → `warn`；否则 `pass`（unclear 不降级）。规则里用
   文档类型名（"报价单"…）引用，judge 从图/文件名认出对应文档。每条结论附 `evidence`
   ——judge 依据的**逐字原文引文**（`{doc, page?, quote}`，纯文本，绝无坐标）。看最近
   一次报告用 `read_audit_report(slug)`（零成本，不重跑）。
   **大组走 job**：组内文档总页数 > 8、或上次 run_audit 趟时接近客户端超时（远程工具
   ~60s）时，改用 `start_job(skill="audit", slug, params={filenames?})` 秒回 job_id →
   `get_job(job_id)` 轮询（RUNNING → DONE/ERROR）→ DONE 后 `read_audit_report(slug)`
   取完整报告。小组照旧直接 `run_audit`。
3b. `render_audit_board(slug)` — 把最近一次报告**圈到文档图上**：每份文档一张合成图，
   每条规则的 evidence 在原文位置画圈 + 规则编号徽标（绿=pass / 红=fail / 黄=unclear），
   附 编号↔规则 图例。零 LLM 成本（复用报告 + 页渲染缓存）。用户说"圈出来 / 在图上
   标出来 / 指给我看"时用它；没跑过审核会报 `audit_no_report`（先 `run_audit`）。
4. `save_reviewed_audit(slug, expected)` — 人确认审核结论（score 的真值）。`expected` =
   {规则原文: "pass"|"fail"}，**按规则文本对齐，key 必须与当前规则一字不差**。用户逐条
   说（"第 2 条其实不对" → 该条存反向真值），或确认整份报告（把报告里的 pass/fail 原样
   存为真值）——但 **`unclear` 的规则必须先问出真相才能存**：真值没有 unclear，那是
   judge 判不了，不是业务没答案。可只确认部分规则，多次调用 merge 累积；改了规则文案，
   旧真值自动脱钩（语义可能变了，需重新确认）。
5. `score_audit(slug)` — 用**当前规则**重跑 judge，对照真值出 accuracy + precision/recall
   （**fail 为正类**——审核存在的意义是抓违规；judge 判 unclear 在真 fail 上算漏报 fn，
   在真 pass 上不算误报 fp，单独计数）。tune 循环：改规则（`write_audit_rules`）→
   `score_audit` 看指标动没动——同改 description 后 `/score` 提取。无真值时不跑 judge，
   直接回零指标。

**审核必须走 `run_audit`——绝不要自己调 `read_doc_image`/`pdf_render_page` 把文档图
拉进对话来"手动审核"。** 审核的图在 `run_audit` 内部经 provider 直连流转，judge 看的是
全分辨率原图；而你经工具拉进对话的图会在 SDK 边界被降采样（buffer 防护，对日常看图无损，
但对审核判断是精度损失），且审核的产物应当是结构化报告，不是你的口头描述。`run_audit`
失败也不要 fallback 去读图——报错给用户、修规则/文档后重试。

**Rendering contract**（不 dump JSON）：
- **browser**（`interface: browser`）：一句摘要即可（"审核完成：整体不过——3 条规则
  1 条失败（盖章缺失）"）；run_audit 的结果卡片（AuditCard）会自动渲染逐条明细
  （含引文），不要在正文重复整张清单。用户想看证据落在文档哪里 → 指点卡片头部的
  `open board ↗`（审核白板：页图铺板 + 圈注 + 跨文档连线），即 `→ board`。
- **headless**：完整清单。逐条 `✓/✗/? 规则 — 理由`（pass ✓ / fail ✗ / unclear ?），
  有 evidence 的条目下一行附 `依据: 「引文」(doc · pN)`（引文原样，不改写）；
  `decided_by:"l1"` 的条目注明判定来源（如 `[规则判定]`，理由本身已是可解释比较）。
  末尾一行整体三态：**过 / 过（有警告）/ 不过**——`warn` 写"过（有警告）"并点名
  哪几条 warning 失败；`fail` 点名哪几条 critical 失败。`unclear`（判不了，如图不清/
  字段缺）单独提示，不算失败但要让用户知道去补。视觉规则（红章）说清看到/没看到。

**`board_annotations`（`read_audit_report` 可选段）— 板上圈注 = 用户留给你的反馈**：
用户在审核白板上圈/手写后，`read_audit_report` 会多出 `board_annotations`（每条
`{doc, page, kind, user_text?, region_text?}`，纯文本无坐标；doc 为 null = 画在板上
空白处）。这是用户主动留下的 teaching signal——**出现必主动复述，绝不静默忽略**，
并按内容提议下一步：指向规则问题 → 给出 `write_audit_rules` 修改草案让用户确认
（绝不未经确认直接改）；指向某份文档的数据问题 → 建议复核该 doc 或重跑审核；
纯备忘 → 简要确认收到即可。
- **browser**：一句摘要（"板上有 N 条你的圈注，其中 ① 圈了报价单 p2 的费用总计…"）
  + 行动提议；圈注本身在 board 可视（`→ board`），正文不重复罗列全文。
- **headless**：逐条完整输出——`① 报价单.pdf p2 圈注：「{region_text}」`、
  `② 板上批注：「{user_text}」`（doc 为 null 写"板上空白处"；一条兼有圈注与手写时
  后接 `+ 手写 "{user_text}"`）；末尾给行动提议。

**render_audit_board 的 rendering contract**：
- **browser**：一句摘要 + 指点 board（`→ board`，UI 卡片/白板兜底），不内联大图。
- **headless**：先图例清单（`N. ✓/✗/? 规则`），随图输出；每张合成图一句话说明
  （哪份文档、圈了哪些编号、有无未定位条目）。**工具返回里带一条 interactive
  board 链接**——很多远程客户端（Cowork/Desktop）不在对话里内联渲染工具返回的图，
  务必把这条链接转给用户，点开就是完整可交互白板（左栏规则 ↔ 画布圈注联动、
  pan/zoom、被引文档自动聚拢），比静态合成图体验更好。

**render_review_board 的 rendering contract**（审单核对白板 —— 结构化/文本文档专用）：
`render_audit_board` 的孪生，但面向**没有页面光栅的结构化/文本审单文档**。文本 doc 无从
在图上圈注，证据是**两张原始表格里的行**（采购发票明细 + 结算细单），数量核对不过的商品组
以红框行 + 同号徽章跨表呼应——这是 audit 白板「原件 + 圈注」哲学在结构化数据上的等价物。
0 LLM，纯计算。什么时候用：用户说「看/复核/核对审单结果」「哪些单驳回了」「打开白板」。
- **browser**：一句摘要（"审单核对：4 单，驳回 2 / 通过 2"）——结果卡片（ReviewBoardCard）
  自动渲染逐单列表 + `打开白板 ↗`，正文不重复罗列每单。用户要看某单细节 → 指点 `→ board`
  （左栏选单，右侧原始双表 + 红框行）。
- **headless**：先一行总计（`N 单 · 驳回 m / 通过 k · model`），再逐单一行——
  `结算总单 {id} — 通过/驳回 · {supplier}：{reason}`（reason 原样，不改写）；**驳回单**额外点出
  问题商品组的数量对比（如「维生素B1片：发票 280 瓶 vs 结算 14 盒，数量比 20，金额一致」，
  取自文档的程序预计算，不要自己算）。末尾转发 interactive board 深链
  （`{base}/p/{slug}?reviewboard=1`）——远程客户端不内联 iframe，务必给链接。
  **绝不 dump 那两张表的全部行到对话**——表在白板里看，headless 只给结论 + 问题组。


**score_audit 的 rendering contract**（不 dump JSON）：
- **browser**：一句摘要（"评分完成：accuracy 2/3，1 条判错"）——结果卡片自动展示
  指标与判错明细，正文不重复。
- **headless**：先**一行指标**（`accuracy x/n · precision p · recall r · unclear k 条`），
  再逐条 `✓/✗ 规则 — 判了什么 / 真值是什么`，**只列判错的**（全对就说全对）；有
  `unreviewed_rules` 时提示哪些规则还没确认真值（确认了 score 才算它们）。
