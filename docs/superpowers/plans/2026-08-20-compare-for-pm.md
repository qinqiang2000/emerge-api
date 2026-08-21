# 对比交给产品经理（口径进产品）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让不懂代码的产品经理在网页 chat 里发起「模型/prompt 对比」，得到一份**口径正确、不会误判、可以转发出去**的报告；没有 GT 的项目也不卡死，而是走「分歧裁决 → 造 GT → 再出报告」。

**Architecture:** 三段，按 PM 实际会撞上的顺序。① **噪声护栏**——纯 skill 改动，堵住最贵的误判（单轮差 2pp 就拍板）。② **口径 + 报告**——`_aggregate` 补格级计数，把「GT 有值格准确率」「整篇零错 n/N」升为头条，官方 macro 降级为灰字；报告做成 `render_board(kind='compare')` 的第三种白板（自含 HTML + iframe，可转发）。③ **无 GT 路径**——`diff_predictions` 产出分歧队列，chat 里逐格裁决，落 `save_reviewed` 成 GT，然后自动回到 ②。

**Tech Stack:** Python 3.12 / FastAPI / `claude_agent_sdk` `@tool` / pydantic v2 / pytest；前端 Vite + React 19 + TS + Zustand + vitest。

**Spec 来源:** 用户 2026-08 在 `~/Desktop/振兴_20260707_docs_and_results/_workbench/HANDOFF.md` 里手工积累的对比方法论 —— 本 plan 的作用就是把那份 HANDOFF 拆成两半：**数字进报告，方法论进 skill**，Desktop 上那堆一次性脚本不再是必需品。

---

## 0. 动手前量到的四个事实

**0.1 网页 chat 的权限不是瓶颈。** `app/chat/permissions.py:5` 起，agent 有 `Bash / Read / Write / Edit / Glob / Grep`；workspace 内 Bash 直接 allow（`permissions.py:319`），workspace 外只是 `ask`。硬 deny 只有 secrets 字面量、`.ssh/.aws/.git/config`、以及 `mv` 搬项目根。**PM 缺的不是权限，是口径。**

**0.2 产品现在的 `/compare` 用的正是 HANDOFF 已否决的口径。** `domains/experiments.md` 的 compare flow 第 6 步输出 `doc_accuracy` + `field_accuracy_macro`：

| HANDOFF 的结论 | 产品现状 |
|---|---|
| 「别只看官方 macro，两边都空算对是送分题」 | headline 就是它（`app/eval/score.py:88`） |
| 「**不再用**文档准确率，0 篇全对却 84.4% 自相矛盾」 | 第二头条（`experiments.md` compare flow） |
| 「单轮差距 <9pp 是噪声」 | 无噪声概念，单轮直接下结论 |
| 「整篇零错文档数才回答『几篇能免复核』」 | 有 `doc_accuracy_strict` 但被标为 legacy、不出现在 chat |

**0.3 `SchemaField.required` 是个没人消费的死字段** —— `app/tools/extract.py:54`：「`SchemaField.required` only documents intent and is not enforced at this layer」，全仓再无第二个语义消费者。因此把它激活成「★重要字段」标记**零冲突**，且 PM 标 required 这个动作本来就懂。

**0.4 「整篇零错」已经算好了，只是没暴露。** `app/eval/score.py::_aggregate` 里 `doc_strict`（分子）和 `n_reviewed_graded`（分母）都是现成的局部变量，只对外给了比值 `doc_accuracy_strict`。报告要的 `n/N` 是免费的。

---

## 1. 指标定义（本 plan 的唯一口径真相）

cell status 五档已在 `app/eval/types.py:8`：`correct / wrong / missing / spurious / absent_both`。

```
GT 有值格 = status ∈ {correct, wrong, missing}      ← 硬指标的分母
GT 空格   = status ∈ {absent_both, spurious}        ← 送分区，不进硬指标
有值格准确率 = correct / (correct + wrong + missing)
```

**微平均 vs 宏平均：报告用微平均（格级）。** HANDOFF 的头条「144 格里 91.0%」是格级微平均；产品现有 `field_accuracy_macro` 是字段级宏平均（罕见字段和高频字段等权，会被 22 格全空的 `salesOrderNumber` 这种拉偏）。两者都保留，但**报告头条是微平均**，宏平均留在原字段不动，保证既有 UI/publish gate 不回归。

报告四行（★行在无 required 时整行隐藏）：

| 行 | 数据来源 | 口径 |
|---|---|---|
| ★必填字段 · 有值格 | `required_cell_accuracy_nonempty` | 微平均 |
| 全字段 · 有值格 | `cell_accuracy_nonempty` | 微平均 |
| 整篇零错文档 | `n_docs_perfect` / `n_docs_graded` | 计数 |
| <sub>官方 macro（含两边都空的送分格）</sub> | `field_accuracy_macro`（已有） | 宏平均，灰字 |

---

## 2. P1 — 噪声护栏（skill only）

最便宜、最先上。PM 拿到第一份报告之前，这条必须在。

**阈值不硬编 HANDOFF 那张表**（那是振兴 19 篇/144 格量出来的，换项目就不成立）。改成随样本量自动缩放的双条件，两个都满足才算「赢」：

```
Δ格数 = 挑战者对的有值格数 − 在位对的有值格数
判定：Δ格数 > 3  且  Δpp > 9        → 允许下结论
      否则                            → 「分不出高下」，不许给推荐
```

报告与 chat 都必须把差距**同时用两种单位**说出来：`+5.3pp（≈ 19 格 / 349 格）`。PM 看得懂「赢了 19 格」，看不懂 5.3pp 意味着什么。

- [x] **T1** 重写 `backend/app/skills/domains/experiments.md` 的 `## Compare flow` 一节：
  - 判据段落（上面那个双条件），措辞用「不许下结论」而非「建议谨慎」
  - 口径优先级：头条=有值格微平均；`doc_accuracy` **从 compare 输出里删掉**（HANDOFF 明确废弃，理由一句带过）；官方 macro 标注「含两边都空的送分格」
  - 单轮即可，**不要自作主张补轮**；确需补轮先问用户（HANDOFF「判断陷阱 6」的结论）
  - 保留现有第 1 步 reviewed 覆盖率 pre-check，但把「refuse」改成**转 P3 分歧裁决**（T8 落地前先写成 TODO 指向 `/compare` 无 GT 分支）
  - rendering contract 双分支（browser 一句摘要 + 指向 board；headless 完整表格）—— CLAUDE.md 人格红线
  - 新增一段 `## 判断陷阱`（从 HANDOFF 搬家，PM 不读、agent 读）：别拿一致率当准确率、别把 `docType=other` 当错误、自洽性是证伪工具不是定义来源、留空不是安全牌
  - 验证：`cd backend && uv run pytest tests/ -k skill -v`（若无覆盖则新增一例断言 compare flow 不再出现 `doc_accuracy`）

---

## 3. P2 — 口径 + 对比报告

### 3.1 后端指标

- [x] **T2** `backend/app/eval/score.py::_aggregate`（当前 81–175 行）
  - `counts` 每字段的 dict 从 `{correct,total,absent_both}` 扩到含 `wrong / missing / spurious`；循环里按 status 分别累加（现在 `wrong/missing/spurious` 三档都只进 `total`，没有单独计数 —— 这正是现在**算不出有值格分母**的原因）
  - 每字段派生 `nonempty_total = correct + wrong + missing`、`accuracy_nonempty = correct / nonempty_total`（分母 0 → `None`，**不是 0.0**，避免和「真的 0%」混淆）
  - 全局微平均：`cell_accuracy_nonempty = Σcorrect / Σnonempty_total`；按 `f.required` 过滤出 `required_cell_accuracy_nonempty` 与 `n_required_fields`
  - 暴露已算好的 `n_docs_perfect = doc_strict`、`n_docs_graded = n_reviewed_graded`
  - 返回签名从 5-tuple 扩成 dataclass 或 7+ 字段 tuple —— **只有一个调用点**（`score.py:300`），改动封闭
- [x] **T3** `backend/app/schemas/score.py`
  - `FieldScore` 加 `n_wrong / n_missing / n_spurious: int = 0`、`accuracy_nonempty: Optional[float] = None`、`required: bool = False`
  - `ScoreResultSummary` 加 `cell_accuracy_nonempty / required_cell_accuracy_nonempty: Optional[float]`、`n_docs_perfect / n_docs_graded / n_required_fields: Optional[int]`
  - 全部 Optional 或带默认 —— 磁盘上的历史 `metrics/eval_*/summary.json` 必须继续 parse（`extra="forbid"` 只挡多余键，缺键靠默认值）
  - 新增测试 `backend/tests/unit/test_eval_score_nonempty.py`：① 构造含五种 status 的 cells，断言有值格分母排除 `absent_both` 与 `spurious`；② 全字段 required=False 时 `n_required_fields==0` 且 required 指标为 `None`；③ 旧 summary.json blob 仍能 `ScoreResultSummary.model_validate`
- [x] **T4** 回归确认：`app/services/bench.py`、`app/api/routes/eval.py`、autoresearch best-turn picker、publish gate 阈值（`field_accuracy_macro ≥ 0.75/0.90`）**一律不动** —— 新字段是纯增量，旧 headline 语义不变。跑 `uv run pytest -q` 确认零回归。

### 3.2 报告白板

`render_board` 已经是「一个名词多种介质」（`app/tools/_merged.py:51`，现有 `audit` / `review` 两 kind），第三种同构。

- [x] **T5** 新建 `backend/app/tools/compare_board_render.py::render_compare_board(workspace, slug, a, b)`
  - 入参 `a` / `b` 是 eval ts 或 experiment id（沿用 `/eval/compare?a=&b=` 的既有约定）；读两侧 `metrics/eval_<ts>/{summary.json,cells.jsonl}`
  - 产出 `{"headline": str, "overall": [...4 行...], "per_field": [...], "verdict": "win"|"noise", "html": str}` —— 自含 HTML（无外链、内联 CSS），与 `review_board_render.py:317::_build_doc_html` 同风格
  - 逐字段表：`字段 | 在位 | 挑战者 | Δ | 对/有值格 | 错值·漏抽·多填`，按 |Δ| 降序；`nonempty_total==0` 的字段落到折叠区标 n/a（**永远不报成 0%** —— 既有 `not_applicable` 红线）
  - `verdict` 由 T1 的双条件算出，直接进 headline 那一句
  - 内容一律 `html.escape`（同 review board 红线）
- [x] **T6** 接线：`app/tools/__init__.py:2339` `_BOARD_KINDS` 加 `"compare"`；`t_render_board` 加分支；tool description 补 compare 段落（browser/headless 双渲染契约）；HTTP twin `app/api/routes/compare_board.py::GET /lab/projects/{slug}/compare/board-render?a=&b=`（照抄 `review_board.py` 结构，含 `safe_slug`）；`test_symmetry_invariant.py` 必须自动通过（不新增豁免）
- [x] **T7** 前端：`frontend/src/components/CompareBoard/CompareBoardOverlay.tsx`，复用 `ReviewBoardOverlay.tsx` 的 iframe srcdoc 模式；入口用 query flag（`?compareboard=1&a=&b=`）与 review board 对齐；只用语义 token（`paper`/`ink`/`ochre`/`rose`/`moss`），禁止直接 Tailwind color class
- [x] **T8** skill 收尾：`experiments.md` compare flow 末尾改为「跑完两侧 eval → `render_board(kind='compare', a=…, b=…)` → browser 分支一句话 + 指向 board；headless 分支打完整表格」，并给出可转发链接 `{public_base_url}/p/{slug}?compareboard=1&a=…&b=…`

---

## 4. P3 — 没有 GT 时：分歧裁决，不是对比

**红线：无 GT 的任何界面/输出都不允许出现百分比。** 两模型一致率不是准确率（HANDOFF 判断陷阱 1，用户第一版就栽在这）。无 GT 时只报「N 处分歧待裁决 / 已裁 M」。

- [x] **T9** 新 tool `backend/app/tools/diff_predictions.py::diff_predictions(workspace, slug, a, b)`
  - 逐 (filename, entity_idx, field) 对齐两侧预测；等价判定**复用** `app/eval/normalize.py:74::normalize_equivalent`（数字/日期/NFKC/array 结构化已经吃掉，`1,234.00` vs `1234` 不会误报）
  - 返回 `{n_cells, n_diff, n_diff_required, by_field: [{field, n_diff, required}], cells: [{filename, entity_idx, field, a, b, required}]}`
  - **不产任何分数**；实体数不一致时按重叠部分对齐并在返回里显式报 `entity_count_mismatch`（HANDOFF 里 terra 在两篇上实体切分失败，静默按重叠打分会偏袒它）
  - `@tool` + HTTP twin `GET /lab/projects/{slug}/compare/diff?a=&b=` + 单测（含等价归一不误报、实体数不齐、required 分组三例）
- [x] **T10** skill 无 GT 分支：`reviewed/` 为空 → 不 refuse，改为
  1. 说明「没有 GT，无法判准确率；先把两侧分歧裁决成 GT」
  2. `diff_predictions` → 按字段分组呈现，**required 字段优先**（PM 的时间该花在这）
  3. PM 在 chat 里逐格/批量裁决（「这些取 A」「这格正确值是 X」）→ agent 调 `save_reviewed`（`app/tools/reviewed.py:25`，带锁 + 原子写 + `_run` 戳）
  4. 裁完自动转 P2 出报告
  - 第一版**不做点选 UI** —— chat 能完成一切是红线，交互式点选留待后续（board 上只做只读清单，见 T11）
- [x] **T11** `render_compare_board` 加无 GT 态：只读分歧清单（分组、两侧值并排、零百分比），headline 是「N 处分歧待裁决」

---

## 5. 收尾

- [x] **T12** 全量测试：`cd backend && uv run pytest -q`（基线 1689 passed，见 HANDOFF）+ `cd frontend && npx tsc -b && npx vitest run`。前端已知既有失败（jsdom `scrollIntoView`、undici 相对 URL）不算回归，需逐条比对 `main` 确认
- [x] **T13** 部署：`./deploy.sh`（不覆盖 `backend/.env` 与 `backend/workspace`）
- [ ] **T14** dogfood —— **交回用户，不由 subagent 执行**（milestone dogfood handoff 惯例）。剧本：
  1. 振兴_20260707 已有 638 格 GT + 4 个实验，直接跑 `/compare`，核对报告四行数字与 HANDOFF 里的已知值对得上（★必填 · 有值格应接近 88.9/85.8 那一档；若该项目 schema 没标 required，★行应整行隐藏而不是报 0%）
  2. 找一个无 GT 的项目验 P3：`/compare` 不 refuse、不出百分比、分歧清单按 required 优先
  3. 报告链接转发给 PM，确认她不用任何解释就能读懂头条那一句

---

## 5.5 实际交付（2026-08-20）

commit `6aded08` + `f16227d`，已部署（`./deploy.sh` → healthz/index 200）。
backend **1908 passed / 0 failed**（净增 54 例）；frontend tsc clean、721 passed
（11 例既有 jsdom `scrollIntoView` 失败，数量未变）。

**生产 smoke 抓到一个真缺陷并已修**：振兴项目有 638 格 GT，拿 2026-08 那两次
eval 出报告时 headline 却说「先给一些文档做 review 造 ground truth」——因为那两个
`summary.json` 是 M12 时代写的，没有新口径的键，落到 `None`，和「真的没有 GT」
长得一样。按 `n_reviewed` 区分后：打过分就是 blob 旧了（提示重跑），真的是 0
才提示去 review。`f16227d`。

**T11 的形态比 plan 更省**：无 GT 态没有单开一个 board kind，而是靠 `a`/`b` 的
**形状**分流（eval ts → 报告态；`_draft`/`ex_…` → 裁决态，见 `is_eval_ts`）。
同一个问题的两种输入，不是两种语义；混着传会被 `compare_mixed_handles` 拒绝。

### 交给人 dogfood 前要知道的两件事

1. **振兴项目要看到硬指标必须重跑一次评测** —— 现存的 5 次 eval 全是 M12 blob，
   只有官方 macro 可读。重跑会调 LLM（19 篇 × 2 侧），是花钱的动作，由用户决定。
2. **振兴的 `required` 只标了 4 个**（`docType` / `page` / `invoiceType` /
   `currency`），而 HANDOFF 的「13 个重要字段」是另一套人工清单。★那一行现在
   反映的是 schema 的 required。要对齐 HANDOFF 口径，得把那 13 个字段标成
   required —— 这正是设计意图：★是 PM 自己能调的旋钮，不是写死的清单。

## 6. 明确不做

- **不产品化多轮重复跑** —— HANDOFF「判断陷阱 6」的结论是「默认单轮 + 查噪声表」，把补轮做进产品会诱导 PM 烧 token 买一个她读不懂的区间。`run_repeat.py` 留在用户的 Desktop 工具箱里。
- **不给打分器加通用格级 not-applicable** —— 「`docType=other` 的非必填格不计分」是振兴的领域口径，不是产品规则；本 plan 用 `required` 分档已经覆盖 PM 的实际需求（重要字段单独一行）。真要做，另开 plan。
- **不动 publish gate 阈值 / 不动 `field_accuracy_macro` 语义** —— 新指标纯增量，避免波及 autoresearch 与发布门槛。
- **不做裁决的点选 UI** —— 第一版走 chat（红线：chat 能完成一切）。

## 6.5 已知 follow-up（本次未做）

- **`diff_predictions` 的 `cells` 没有上限。** 几百篇 × 几十字段的项目，一次调用
  可能把上千行明细塞进 agent 上下文。白板侧已有 `_MAX_DETAIL_ROWS=300` 截断，
  tool 侧没有。修法是加 `field` 过滤 + `limit`（skill 已经写了「先看 by_field
  聚合、按字段分批要明细」，但工具层面没强制）。振兴规模（19 篇 × 29 字段）不会
  撞上，所以没有阻塞 dogfood。
- **`/eval` 单侧打分仍报 `doc_accuracy` 与官方 macro 头条。** 本次只改了 compare
  的口径，`## Eval` 那节原样未动（避免波及既有测试与 EvalCard 渲染契约）。两处
  口径不一致是已知的、有意的范围切分。

## 7. 排序说明

P1 → P2 → P3。振兴项目已有 GT，PM 的第一个任务走 P2 就能跑通；P3 是她接**新项目**时才卡。
**若 PM 第一个任务就是没有 GT 的新项目，P3 必须提到 P1 之后、P2 之前** —— 否则她在第一步就撞上 refuse。
