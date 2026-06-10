# 2026-06-10 — 文档审核（audit）设计：matching 的演进

> **Status**: 🧠 design（用户真实用例触发：报价单/收货单/订单的 5 条合规规则）
> **认知更新**: 用户要的"匹配"核心是 **审核（合规检查）**，"配对"只是前置。matching（凑齐关联文档）保留，在它之上加"审核规则层"——judge 从「配对判定器」升级成「审核判定器」（看字段 + 看图，逐条 NL 规则判 pass/fail），产出从「核对卡」变成「**审核报告**」。
> **基础**: `2026-06-09-doc-matching-design.md` + 已落地的 matching P0/P0.5a（`2026-06-10-matching-p0-impl.md`）。

---

## 触发用例（用户原话）

> 匹配更多为了**审核**。加入一个/多个项目，有：报价单、收货单、订单。规则：
> 1. 报价单甲方为「环胜电子商务（上海）有限公司」
> 2. 报价单需乙方加盖合同专用章（红章）
> 3. 报价单「费用总计」== 收货单「折扣后收货含税总金额」
> 4. 报价单项目抬头 与 收货单备注摘要关键字 一致
> 5. 报价单项目周期 ∈ 订单服务完成日期区间

## 真实数据验证（2026-06-10，看了三份真实文档）

`audit_demo/{报价单.pdf, 收货单.pdf, 订单.png}`（一笔真实业务：KFC Y25 2月疯四 social）。**5 条规则的两侧字段全部对得上**：

| # | 取自 | 实际值 | 判定 |
|---|---|---|---|
| 1 | 报价单 Brand客户 | 环胜电子商务（上海）有限公司 | == 常量 ✓ |
| 2 | 报价单右下角 | 乙方"上海科翼文化传播有限公司 合同专用章"红色印章（甲方签字栏空） | 视觉存在 ✓ |
| 3 | 报价单费用总计 / 收货单折扣后含税 | 370815.56 / 370,815.56 | 数值一致 ✓ |
| 4 | 报价单抬头 / 收货单备注 | "KFC Y25 2月疯狂星期四social" / "2月疯四全套social物料" | 模糊关键字 ✓ |
| 5 | 报价单项目周期 / 订单完成日期 | [2025.1.15, 2025.2.28] / 2025-02-28 | 区间包含 ✓ |

**三点实证**：
- **强凑齐 key 存在**：三件套共享 订单号 `AMPPO202502020678`、合同号 `20240500717`、金额 `370815.56`、项目名"2月疯四…social物料"——**自动凑齐完全可行**（A0 仍先人工指定一组把审核判定跑透，A1 复用 matching 自动凑齐）。
- **判定必须 judge-centric**：#4 模糊关键字、#5 区间包含（点 2.28 落在 [1.15,2.28]）、#1 同实体不同写法——确定性 L1 做不好，靠 LLM judge 读字段判。#2 必须看图。
- **格式无关**：扫描 pdf / 文字 pdf / 截图 png 三态俱全，emerge extract 已覆盖（用户确认"和发票一样，图片或 pdf"）。审核层只吃**提取字段 + 按需文档图**。

## 文档类型开放（用户补充 2026-06-10）

参与审核的文档**类型不固定**：anchor 一类（如报价单），source 是 N 个**任意类型**项目——订单、发票、付款单、物料单（含微信文案/小红书推文/主视觉画面）… 一笔业务凑哪几类、跑哪些规则，全由用户用 NL 规则定义。**audit 永不硬编码文档类型**（强化红线：chrome 用 anchor/source/rule/check，不出现 报价单/订单/红章 等具体词）。

这引出一类更丰富的规则——**交付核对**：报价单列的项目（5 篇微信推文、1 张主视觉…）vs 物料单的实际交付物，核对数量/内容/（主视觉的）视觉一致。比字段断言复杂（列表对齐 + 内容/视觉判定），**A1+ 再做**；A0 先覆盖字段断言（#1/#3/#4/#5）+ 单文档视觉断言（#2）。

## 规则的能力分解（这是设计的骨架）

| # | 规则 | 类型 | 判定方式 | 现状 |
|---|---|---|---|---|
| 3 | 报价单金额 == 收货单金额 | 跨文档·数值一致（容差） | 字段比较 | ✅ number tol |
| 4 | 报价单抬头 ~ 收货单备注关键字 | 跨文档·模糊/包含 | L2 judge（NL） | 🟡 部分 |
| 1 | 甲方 == "环胜电子商务（上海）" | 单文档·固定值断言 | 字段==常量 / judge | ❌ 新 |
| 5 | 报价单周期 ∈ 订单完成日期区间 | 跨文档·区间匹配 | 区间判定 | ❌ 新 tol |
| 2 | 乙方盖了合同专用章（红章） | 单文档·**视觉**存在性 | judge **看图** | ❌ 新（vision） |

**两个核心洞察**：
- **规则本质是 prompt**。用户就是用自然语言列的 5 条——印证「匹配规则用 prompt 定义」的 tip。`rules`（NL）从兜底升级成**主角**（#1/#2/#5 结构化字段映射根本表达不了）。
- **#2 红章 = 视觉审核**。judge 要看文档图（报价单上有无红章），经已有的 `read_doc_image` 把图喂给 judge。**不碰红线**：不是 image few-shot，不是 bbox 进 prompt，是 doc-vision-pulled。

## 形态：两步链条

```
1. 凑齐（grouping）：把同一笔业务的 报价单 + 收货单 + 订单 关联成一组
   —— 复用已有 matching（anchor + sources，靠 key 配对），或人工指定一组。
2. 审核（audit）：对凑齐的一组，跑 NL 规则逐条判 pass/fail
   —— judge 升级：看组内各文档字段 + 可选看图，逐条规则给 {status, reason}。
        ↓
   AuditReport（每组一份）：
     group: {anchor: 报价单doc, sources: {收货单:doc, 订单:doc}}
     checks: [{rule: "甲方为环胜…", status: pass|fail|unclear, reason}]
     overall: pass | fail   ← 任一关键规则 fail → fail
```

## 一趟，不是两趟（用户修正 2026-06-10，A0 已改）

**审核 judge 直接吃文档原图（图/pdf），一趟出逐条结果——提取不是前置。** 原设计把 audit 焊在 extract 之上（两趟：先提取字段 → 再判规则）是惯性错误。理由：① 审核规则**开放**，提取 schema 覆盖不全 → 字段是信息瓶颈；② 视觉规则（红章）提取根本抽不出，**无论如何要看图**；③ 审核是**独立任务**，不共享 extract 的 draft，所以"坚持两趟"的 lab=prod 论据（inline-grounding 否决）**不适用**。
- **文档图 = 必须**（原文为准，read_doc_image→ImageBlock；A0 page 1，多页 A1）。
- **已提取字段 = 可选辅助**（若 draft 存在则附给 judge 当 hint，数字更准；没提取也能审核）。
- 返回格式（response_schema）+ 规则（audit_rules）复用 emerge prompt/schema 机制——输入端改原文，输出端不变。

## judge 升级：配对判定器 → 审核判定器

- 现在 `judge_pair(anchor, source, mappings, rules) → match/mismatch`（用于凑齐）。
- 新增 `audit_group(group_docs, rules, *, images?) → list[CheckResult]`：
  - 输入：组内各文档的已提取字段 + （当规则需要时）文档图像。
  - 规则主要靠 **L2 LLM judge**（#1/#2/#4/#5 结构化做不了/不自然）；能结构化的（#3 金额、#5 区间）可走 L1 确定性快路 + 进报告。
  - 输出：逐条 `{rule, status: pass|fail|unclear, reason}`。
  - 视觉规则：judge 调用附上相关文档图（`_load_image_blocks` / `read_doc_image`）。`unclear`（判不了/图不清）是一等状态，不硬判 fail。
- 红线：provider 直连不回 SDK；图是 pulled（规则触发才附），不 auto-attach；无 few-shot；bbox 不进 prompt。

## 数据模型（扩展 match prompt）

match prompt 现有 `{mappings, rules}`。审核扩展：
- `mappings`：保留，**仅用于凑齐**（把三件套配上的 key）。
- `rules`：升级为审核规则的载体。倾向**保持 NL 大段**（用户就这么写），judge 输出结构化逐条结果——最 SSU，贴用户写法。（结构化 `list[AuditRule]` 是备选，更精细但要用户结构化，P1 再说。）
- 新增：每条规则可选 `needs_vision`/涉及文档提示，帮 judge 决定附哪张图（也可让 judge 自己从规则文本判断）。

产出落 `audits/{run}/report.json`（派生缓存，可重跑）。review/score 同构：人确认审核结论 → ground truth → 审核准确率（per-rule + 整笔 pass/fail 的 precision/recall）。

## 复用 vs 新增

**复用**：matching 的凑齐（anchor+source 配对）、match prompt 版本化、extract 结果、`read_doc_image`/`_load_image_blocks`（视觉）、provider 直连 judge、review/eval 聚合脊。

**新增**：
1. `audit_group` judge（NL 规则逐条判 + 视觉）。
2. 区间 tol（#5）+ 固定值断言（#1）的 L1 快路（可选；judge 也能做）。
3. `run_audit` + AuditReport 数据布局。
4. audit 的 review + score。
5. 审核报告的渲染契约（browser/headless）。

## 红线
- **视觉不碰 few-shot / bbox**：图 pulled、规则触发才附；judge 只为判规则看图，不存坐标、不进结构化 prompt。
- **lab=prod 一致**：审核两趟（extract → 凑齐 → 审核）；judge 直连不回 SDK。
- **prompt 是真相**：审核规则只经 match/audit prompt 改，不硬编码业务规则进 judge。
- **不物理删**：audit 产物派生缓存可 rmtree。
- **任务类型无关 chrome**：用 group/check/rule/audit，不硬编码 报价单/红章。

## 关键开放决策（实现 plan 前要定）

1. **凑齐怎么做**？审核是「一笔一笔审」（人工指定/强业务号把三件套凑齐）还是「批量自动配」（靠 key）？这决定数据流入口。
2. **规则载体**：NL 大段（judge 解析）vs 结构化规则列表？倾向 NL（贴用户写法），但失败定位/逐条 review 时结构化更好。
3. **视觉触发**：judge 自己从规则文本判断要不要看图，还是规则显式标 `needs_vision`？
4. **L1 快路范围**：#3 金额 / #5 区间走确定性 L1 进报告，还是全交 judge？（确定性的省钱 + 可解释，但 judge 统一更简单。）
5. **overall pass/fail 口径**：所有规则必过，还是规则分「关键/警告」级（如 #2 红章必过，#4 抬头警告）？

## 分期（草案）
- **A0 — 单组审核最小闭环**：给一组凑齐的文档（先人工指定 group）+ NL 规则 → `audit_group` judge（含视觉 #2）→ AuditReport → 渲染。把「审核判定」这个新核心跑透。
- **A1 — 凑齐 + 批量**：复用 matching 自动凑齐三件套，批量审核。
- **A2 — review/score**：审核准确率，tune 审核规则（prompt）。
- **A3 — 区间/固定值 L1 快路** + 规则分级 + lab 前端审核报告视图。
- **prod**：`POST /v1/{pid}/audit`。
