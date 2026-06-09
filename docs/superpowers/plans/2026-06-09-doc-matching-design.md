# 2026-06-09 — 文档匹配（两集对账）设计

> **Status**: 🧠 design（已与用户对齐 4 个分叉 + 1 个 tip）；待 go 后写实现 plan
> **Scope**: emerge 从「提取专用」扩成 slogan 说的真·**文档处理同事**。本设计只覆盖**匹配**；分类是提取特例（见下），不需要新设计。
> **北极星**: 每种文档能力 = 一个 **prompt 定义的任务**，user 改 prompt 来迭代。extract / match / classify 在同一条 prompt→run→review→eval→tune→publish 脊上。

---

## 定性（用户确认）

- **分类 = 提取特例，白送**。schema 加一个 `enum` 字段返回 `doc_type`（`SchemaField` 已支持 `enum`/`format`）。`/run` 出一个分类字段即分类，无新工具、无新数据模型。
- **匹配 = 提取之上的「关系层」**，是真正的新形态：第一次打破「单文档进、单记录出」。

## 对齐的设计决策

| 分叉 | 选定 |
|---|---|
| 形态 | **一锚多源核对**：一张发票（锚）↔ 一堆佐证单据（付款/采购单/收货单/报关单…），每种一份。**二元对账是 N=1 特例**（用户修正：现实对账不是 A↔B，是「一张发票和一堆其它单据」核对） |
| 数据模型 | **一个 anchor project + 一组 source project**（都引用已有 extract project，不重抽，最 SSU） |
| 判定引擎 | **规则优先 + LLM 兜底**（= 复用 eval 的 L1 normalize + L2 judge） |
| 配对基数 | **每个 source 类别内先做 1:1**（anchor 在每类佐证里配最佳一份）；同类多份（1:N，分期付款）下期 |
| **匹配规则载体** | **prompt**（用户 tip）——不是硬编码结构化配置，而是版本化的 match prompt |

---

## 数据流（复用 emerge 已有的 ~80%）

```
anchor = 发票项目            sources = 付款 / 采购单 / 收货单 …（一堆 extract 项目）
  每 doc extract 结果           每类每 doc extract 结果        ← 已有，不重做
  (predictions/_draft/*.json)   (同)
        └────────────┬──────────────────┘
        对每个 anchor 文档，对每个 source 项目分别配最佳一份：
              候选生成 (blocking：按该 source 的 key 粗分桶，避免 N×M)
                    ↓
              逐对判定 judge(anchor.字段 ↔ source.字段，按 match prompt)
                L1 规则：该 source 的 key_mappings 每对 normalize_equivalent + tolerance（确定性、免费）
                L2 兜底：模棱（部分 key 差/名称模糊）→ LLM judge(rules + 两份 extract)
                    ↓
              该 source 内 1:1 分配（候选对带分 → 贪心/匈牙利选最优）
                    ↓
  matches/{run}/result.json：以锚单据为中心的「核对卡」
    cards: [{
      anchor_doc: inv_001,
      pairs: { payment: {doc:pay_A, status:✓}, po: {doc:po_X, status:✓}, grn: {doc:—, status:缺失} },
      overall: 部分核对          ← 缺收货单
    }, …]
    orphans: { payment:[…], po:[…] }   ← 各 source 里没被任何 anchor 认领的（孤儿凭证）
```

一张发票的核对是**一组关系**（对各类佐证单据各配一份），不是单一 pair。**匹配必然两趟**（先 extract 每 doc → 字段，再在字段上 match）——与 INSIGHTS「inline-grounding 否决、坚持两趟」一致：保 lab=prod 一致、不重抽。

## 数据模型

**match project**（复用 project 脊，加引用 + kind）：
```jsonc
// project.json
{
  "name": "海信日本 发票核对",
  "slug": "duizhang-haixin",
  "kind": "match",                          // 新：区分 extract / match project
  "anchor_project": "invoice_海信日本",       // 锚：主单据（发票）
  "source_projects": ["payment_海信", "po_海信", "grn_海信"],  // 一堆佐证单据，各引用已有 extract project
  "active_match_prompt_id": "mpr_…",
  // active_model_id 仍在（L2 judge 用，复用五层 LLM 表的 judge tier）
}
```
> 二元对账 = `source_projects` 只有一个的特例。数据模型一开始就支持 N，实现可先做 N=1 把闭环跑透。

**MatchPromptVariant**（复用 `PromptVariant` 的版本化：`version` + `content_hash`，改了产新 experiment → 可 tune/compare/autoresearch）：
```jsonc
// match_prompts/{mpr_id}.json
{
  "prompt_id": "mpr_…",
  "mappings": {                             // 每个 source 项目各一组字段映射（keyed by source slug）
    "payment_海信": [
      {"anchor": "invoice_amount", "source": "payment_amount", "tol": {"type":"number","abs":0.01}},
      {"anchor": "order_no",       "source": "ref_no",         "tol": {"type":"exact"}},
      {"anchor": "invoice_date",   "source": "pay_date",       "tol": {"type":"date_days","days":3}}
    ],
    "po_海信": [
      {"anchor": "order_no", "source": "po_no", "tol": {"type":"exact"}}
    ]
    // grn_海信: …
  },
  "rules": "订单号是主键，必须精确对上；金额须在容差内一致；日期允许3天误差（跨月结算）；商户名不同写法但同一公司视为一致；无订单号时，金额+日期+商户名三者一致才算匹配。每张发票应集齐付款+采购单+收货单三类佐证。",
  // ↑ NL，= extract 的 global_notes 孪生：喂 L2 judge + 给人读。user 调匹配 = 改 mappings 或改 rules，与「改 description 教提取」同构。
  "version": 1, "content_hash": "…"
}
```

## 复用 vs 新增

**复用（不重写）**：
- `extract_one` —— 每个 source doc → 字段（已有）。
- `app/eval/normalize.py::normalize_equivalent` —— L1 字段比对（类型感知 + tolerance）。**核心复用**：eval 现在比「prediction vs ground truth」，match 比「A.field ↔ B.field」，同一原语换聚合。
- `app/eval/judge` —— L2 LLM judge（模棱兜底），prompt 改喂 match rules。
- `PromptVariant` 版本化 + experiment/eval/review 结构 —— match prompt 与 match eval 同构挂上。
- review 脊 / FSSpine / bench —— per-pair tab 复用 review 多 tab 模式。

**新增（关系这一层）**：
1. match project kind + 引用模型（`left/right_project`）。
2. `MatchPromptVariant`（key_mappings + rules）+ 其 CRUD 工具。
3. **配对引擎**：blocking（候选剪枝）+ 1:1 分配（贪心起步）。
4. per-pair 数据布局 `matches/{run}/result.json`。
5. match 的 review（确认一对该不该配）+ eval（匹配 precision/recall：漏配/错配）。

## review / eval 同构

- **review**：人看一张发票的**核对卡**（anchor 字段 | 各 source 的配对单据字段 | 每类判定 | 不一致/缺失项），确认「这张发票的整组核对对不对」→ 落 `reviewed_matches/`，成 ground truth。复用 review overlay 的多栏 + 字段高亮（各 source 一栏/一 tab）。
- **eval**：**per-source-type 的 precision / recall**（每类佐证配对的准确率）+ **整单核对完整率**（多少发票集齐了全部 source）。结构和现有 eval 层一模一样（判定 + 聚合指标），复用 `app/eval/` 的聚合脊。
- **tune**：改 match prompt（某 source 的 mappings / 全局 rules）→ 重 run → eval → compare。AutoResearch 可优化 match rules（就像优化 extract description）。

## 工具（tool ↔ HTTP ↔ MCP 三形对称，CLAUDE.md 强制）

`create_match_project(anchor, sources)` · `write_match_prompt(slug, mappings, rules)` · `run_match(slug)` · `save_reviewed_match(slug, anchor_doc, verdict)` · `score_match(slug)` —— 各配 HTTP twin + symmetry。chrome 用**通用动词**（anchor/source/reconcile/card），不硬编码 invoice/payment。

## 红线检查

- **lab=prod 一致**：同一 match 逻辑两趟；judge 走 provider 直连，不递归回 SDK。
- **bbox 永不进 prompt**：匹配在 extract 结果（字段）之上，不碰坐标/evidence 渲染层。
- **不物理删**：match run 产出走即删即重建的派生缓存或 trash，不 rmtree 用户数据。
- **任务类型无关 chrome**：match UI/工具用通用动词；`/v1/{pid}/extract` 固化不动，对账 prod 形态另起路由（见分期）。
- **prompt 是真相**：匹配规则只通过 match prompt 改（key_mappings + rules），不在工具里硬编码业务规则。

## 分期（实现时细化）

- **P0 — anchor + 1 source 最小闭环**（N=1 特例，把脊跑透）：create_match_project → write match prompt → run（L1 规则 + L2 兜底 + 1:1 分配）→ result.json（核对卡 + 孤儿）→ review → score。headless + 一个最小核对视图。
- **P0.5 — 扩到 anchor + N source**（星型核对卡）：mappings per-source、核对卡多栏、per-source eval + 整单完整率。数据模型 P0 已支持 N，这里补配对引擎遍历 + UX。
- **P1 — tune/compare**：match prompt 版本化挂 experiment，`/compare` 两套 match prompt，AutoResearch 优化 rules。
- **P2 — 对账 prod API**：`POST /v1/{pid}/reconcile`（输入一锚 + 多源文档，返回核对卡），freeze/issue_api_key 复用。
- **后续**：同类 1:N（分期付款，金额聚合 + 部分匹配）。

## 未决（实现 plan 要定）

- 候选 blocking 的默认 key（金额桶 + 日期窗？还是从 key_mappings 自动推）。
- 1:1 分配算法：贪心 vs 匈牙利（1:1 阶段贪心可能够；分数接近时再上最优）。
- match project 怎么定位 anchor/source 的 extract 结果：读 `predictions/_draft` 还是要求先 freeze？（倾向 draft，保 lab 灵活；prod reconcile 再说 published）。
- anchor/source schema 漂移：被引用的 extract project 改了 schema，mappings 引用的字段没了怎么办（校验 + 友好报错）。
- 一张发票该集齐哪些 source 才算「完整核对」：所有 source 必配，还是 rules 里声明哪些必备/哪些可选（如收货单可缺）。
