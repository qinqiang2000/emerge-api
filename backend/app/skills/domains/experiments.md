<!-- domain skill: experiments / compare / eval / clone — pulled via read_skill("experiments") -->
# Experiments · Compare · Eval · Clone

## Prompt + model axes — operations

| intent | how |
|---|---|
| List variants | `Glob {CURRENT_PROJECT_DIR}/prompts/*.json` (or `models/`) — remote: `ws_list` |
| Read one variant | `Read {CURRENT_PROJECT_DIR}/prompts/{pid}.json` — remote: `ws_read` |
| **Edit active variant's schema or global_notes** | `write_schema(schema=[...], global_notes="...")` — red line; both fields optional but at least one must differ |
| Edit a non-active variant | `Edit {CURRENT_PROJECT_DIR}/prompts/{pid}.json` — remote: `ws_edit` |
| Create a new variant (A/B fork) | `Bash cp prompts/{src}.json prompts/{new}.json` then `Edit` for the diff — remote: `ws_move(copy=true)` + `ws_edit` |
| Switch active | `switch_active_prompt(pid)` / `set_model(role='extract', model_id=mid)` (ask first — affects every later extract) |
| Delete a variant | `Bash rm prompts/{pid}.json` (permission asks). Refuse if it's the active one — switch first. |
| Cross-project clone | `Bash cp {WORKSPACE_ROOT}/src_slug/prompts/{pid}.json {WORKSPACE_ROOT}/dst_slug/prompts/` |

When the user describes A/B-testing something ("试一下 Gemma 4", "改个描
述看看效果"), prefer creating a fresh variant + experiment over mutating
the active one. Keeps a known-good baseline for comparison.

## Experiment axis

Isolate a (prompt_variant, model_config) pair without touching the
active pair. Use when the user says "试试" / "A/B" / "对比 model X" /
"看看 prompt 改 description 的效果".

1. `create_experiment(prompt_id=None, model_id=None)` — upsert by axes
   pair; both default to active. Returns the experiment_id (existing if
   the pair was already minted, freshly minted otherwise). Label is
   auto-derived from prompt + model labels — don't pass a label argument.
2. `extract(filename, experiment_id=<experiment_id>)` — single-doc probe
   against that pair (leaving `experiment_id` out runs the active pair
   instead and writes `predictions/_draft`, not this experiment).
3. (optional) `run_experiment_eval(experiment_id)` — score against the
   full `reviewed/` set; emits per-field + per-doc breakdown. This calls
   the experiment's LLM N times where N = number of reviewed docs.
   Surface the count up front: "this will call <provider/model> N times".
   **Rendering (headless)**: after EACH eval print a one-line score
   (`model · overall% · this-doc%`) so the user gets incremental feedback —
   never leave an empty turn between back-to-back evals. When comparing
   several experiments, print those per-eval lines as you go, THEN a final
   comparison table once all evals finish (model | overall | per-doc), and
   call out which fields drove the gap.
4. `promote_experiment(experiment_id)` — flip active to the experiment's
   pair (ask first — re-seeds `predictions/_draft/` from the experiment's
   per-doc extracts).
5. Archive a rejected experiment: `Bash mv experiments/{exp_id}
   experiments/.archived_{exp_id}` (graveyard convention; rare — keep
   live unless asked). Delete with `Bash rm -r experiments/{exp_id}`
   (permission asks; never delete a promoted experiment — audit trail).

## Compare flow (`/compare <model_id>` or NL "对比 X / 试试 X 在我们数据上")

Sequence (all steps mandatory; never skip the pre-check):

1. **Pre-check reviewed coverage** — `Bash ls reviewed/*.json | wc -l`.
   **If 0, do NOT refuse and do NOT stop** — jump to `### 没有 GT` below.
   Without ground truth there is no accuracy to report, but there IS useful
   work: turn the two models' disagreements into ground truth.
2. **Ensure candidate model exists** — if `Bash ls models/m_*.json | grep <model_id>`
   has no hit, mint it via `add_model(slug, provider, provider_model_id)`.
3. **`create_experiment`** with `model_id=<m_short>` (defaults prompt to
   active). Idempotent — re-running returns the existing id.
4. **`score(slug)`** to produce the active-baseline eval (writes
   `metrics/eval_<ts_baseline>/`). The `ts` field in the returned blob is
   `<ts_baseline>` — keep it.
5. **`run_experiment_eval(experiment_id)`** to produce the candidate
   eval. The return blob has a `summary_ts` field — that IS the
   `<ts_candidate>` for the compare link. (The blob's older `ran_at` field
   is a separate audit timestamp and is NOT a valid eval ts.)
6. **`render_board(kind='compare', slug=…, a=<ts_baseline>, b=<summary_ts>)`**
   — this computes the 口径 + 判据 below and returns the headline, the four
   overall rows, the per-field rows that moved, and a forwardable report URL.
   **Do not hand-roll the numbers**; the board is the single implementation
   (口径 drift between chat and report is exactly how a stakeholder ends up
   quoting two different accuracies for the same run).
7. Render per the contract below, and **always forward the report URL** — a
   markdown table in chat cannot be sent to anyone else; the link can.
8. **Never** auto-`set_model(role='extract')`. Only suggest the command when
   判据 says the challenger actually won.

### 口径 — which number is the headline

Four numbers, in this order. **The first two are the hard ones; the fourth is
nearly meaningless on its own** and must always carry its caveat.

| 行 | summary key | 说明 |
|---|---|---|
| ★重要字段 · 有值格 | `required_cell_accuracy_nonempty` | schema 里 `required: true` 的字段，且 GT 该格有值 |
| 全字段 · 有值格 | `cell_accuracy_nonempty` | GT 有值的格子里对了多少 —— **最硬的指标** |
| 整篇零错文档 | `n_docs_perfect` / `n_docs_graded` | 直接回答「有几篇能免人工复核」 |
| 官方 macro | `field_accuracy_macro` | 灰字/脚注，**必须**标注「含两边都空的送分格」 |

Rules, no exceptions:

- **`n_required_fields == 0` → 整行省略★那一行**，不要报 0%，并在末尾加一句
  「给重要字段标 `required` 可以得到更硬的指标」。
- **不要报 `doc_accuracy`。** 它是「每篇内部对了多少格再across篇平均」，会出现
  「0 篇全对却 84.4%」这种自相矛盾的读数。用「整篇零错 n/N」代替。
- 官方 macro 的 `accuracy = (correct + absent_both) / total` 把「两边都空」算作
  预测正确。罕见字段（税号、PO 号）天然接近 100%，什么都没考出来。**永远不要把
  它单独作为结论依据。**
- `accuracy_nonempty is None` 的字段（GT 从来没有值）标 `n/a`,
  **绝不报成 0%**。

### 判据 — 差多少才算赢（最贵的一条规则）

同一配置重复跑会有跑批噪声，单轮数字的小幅领先常常只是运气。判赢需要**两个条件
同时成立**：

```
Δ格数 = 挑战者对的有值格数 − 在位对的有值格数
条件一：Δ格数 > 3
条件二：Δpp   > 9        （有值格口径的百分点差）
```

- 两条都满足 → 才可以写「建议换」，并给出 `set_model` 命令让用户自己执行。
- 任一条不满足 → **必须**写「分不出高下，维持现状」，**不许**给推荐、不许用
  「略优 / 倾向 / 看起来更好」这类措辞把噪声包装成结论。
- 差距**永远同时用两种单位**表达：`+5.3pp（≈ 19 格 / 349 格）`。用户读得懂
  「赢了 19 格」，读不懂 5.3pp 意味着什么。

**单轮就够，不要自作主张补轮次。** 重复跑同一配置很贵，而且多跑几轮通常不改变
结论。用户确实需要拍板而单轮又落在噪声带里时，**先问用户**要不要补第 2 轮。

### Rendering contract

- **browser**: 一句摘要 —— `render_board` 返回的 `headline` 那一句，然后指向白板
  （`→ 对比报告`）。**不要**在回复里重复整张表（白板已经渲染了）。附上报告链接。
- **headless**: 完整输出 —— 把 `render_board(kind='compare')` 返回的文本原样呈现
  （headline + 四行总体 + 逐字段表），末尾一句点名拉开差距的 1–2 个字段，
  再附报告链接。

### 没有 GT：分歧裁决，不是对比

`reviewed/` 为空时**没有准确率可报**。「A 和 B 有多一致」不是准确率 —— 在位模型
不是金标准。但两侧的分歧恰恰是**成本最低的标注采样**：几百格里通常只有几十格
有分歧，用户只需要看这几十格，而不是逐格标完整个数据集。

流程：

1. 先说清楚状态：「这个项目还没有 ground truth，所以现在无法判谁更准。
   但我可以把两个模型意见不一致的地方列出来 —— 你定夺一次，就同时得到了
   ground truth 和结论。」
2. 两侧都得先有预测。**用 `list_experiments(slug)` 拿实验 id**，别去 `Bash ls`
   实验目录挨个 `Read` meta —— 那是十来次工具调用换一件本该一次的事。
   活动配置写的那份是 `_draft`。
3. **`diff_predictions(slug, a, b)`** —— `a` / `b` 是 `_draft`（活动配置写的
   `predictions/_draft/`）或实验 id（`ex_…`）。等价归一已经复用打分器那套，
   `1,234.00` vs `1234` 不会被报成分歧。
4. **回复里必须附白板链接**，它是同一份分歧的可扫视形态（按字段聚合 + 逐格两侧
   原值，零百分比）。几十上百处分歧在对话里只能挑着说，白板能整片看完：

   ```
   {public_base_url}/p/{slug}?compareboard=1&a={a}&b={b}
   ```

   **直接拼这个字符串就行，不必为了拿链接再调一次工具。**
   （`render_board(kind='compare', slug=…, a=…, b=…)` 是同一张白板的文本形态，
   headless 下想把整张表打进终端时才用它。）
5. 呈现（rendering contract）：
   - **browser**：一句摘要（`N 处分歧待裁决，其中重要字段 M 处`）+ 最值得先看的
     2–3 个字段 + 白板链接。**不要**把几十行明细铺进对话——白板就是干这个的。
   - **headless**：按 `by_field` 聚合列出（**`required` 字段排最前**），再给
     重要字段的具体样本；`cells` 明细按用户点到的字段分批给，不要一次全倒。
6. 用户逐格/批量定夺（「这些取 A」「这格正确值是 X」）→ 写进 `reviewed/`。
   这就是 ground truth。
7. 裁完回到上面的 compare flow —— 现在有 GT 了，可以出真正的报告。

**红线：这一段的任何输出都不许出现百分比。** 不报一致率、不报「A 赢了几格」、
不给「建议用 X」。只报「N 处分歧待裁决 / 已裁 M」。一旦并排显示两个百分数，
读的人一定会把它当成准确率 —— 这个坑本项目栽过。

`entity_count_mismatch` 非空要单独说出来：某一侧在这些文档上实体切分失败
（比如金标准 3 个实体它只给 1 个）。静默按重叠部分对齐会**系统性偏袒缺失的
那一方**，必须点名。

### 判断陷阱 — 读数字之前先想一遍

这些是真金白银栽过的坑，**每次出对比结论前扫一遍**。它们是给你看的，不要抄给用户。

1. **别拿「与某模型的一致率」当准确率。** 在位模型不是金标准。没有 GT 就没有
   准确率，只有分歧 —— 见下面「没有 GT」一节。
2. **prompt 允许的事不能算错。** 若 prompt 对某类文档说了「其余字段可以留空」，
   而 GT 把它们全置空，那么填了内容的一方会因为做了 prompt 允许的事而失分 ——
   这会**系统性偏袒填得少的模型**。判定前先看失分是不是集中在这类格子上；是的话
   先把这件事说出来，别直接下结论。
3. **自洽性是证伪工具，不是定义来源。** 「净额 + 税额 = 总额」这类自检能揪出错
   值，但**不能**用来反推业务定义。领域口径（某项费用算不算税、进不进哪个字段）
   只能来自 prompt 或用户，不能从「这样加起来正好对得上」推出来。
4. **「留空」不是安全牌。** 正确值在原件上明明拿得到，一侧给了错值、另一侧留空 ——
   两边都不得分。留空同样是漏抽，不要因为「它至少没编」就判它赢。
5. **两侧都错的格子，换模型救不了。** 那是 prompt / 口径没说清。这类格占失分的
   比例高时，**结论应该是「改 prompt」而不是「换模型」** —— 说出来，它比换模型
   便宜得多。
6. **汇总分数稳 ≠ 单格稳。** 汇总分数差距更小的模型，格级「这轮对下轮错」的格子
   可能反而更多。用户问「能不能少做人工复核」时，回答要基于格级稳定性，不是
   汇总分。
7. **编造比留空更危险。** 值格式合法、算术自洽、schema 校验全过，但原件上根本
   没有这个值 —— 这类错误下游查不出来。发现某一侧有成规模的编造，即使它分数更
   高也要在结论里点名。


## Eval (`/eval` · "how am I doing" · "what's the score")

First check `Bash ls {CURRENT_PROJECT_DIR}/reviewed/*.json | wc -l`. If
zero, ask the user to review some docs first — don't call `score` (returns
`field_accuracy_macro=0.0`, which is misleading). Otherwise call `score`.
The result has `field_accuracy_macro` (headline), `doc_accuracy`,
`per_field` (each row carries `accuracy/correct/total/n_absent_both/
not_applicable`), `n_reviewed`, `errors`.

**Rendering contract**:
- **browser** (`interface: browser`): the lab UI renders the full
  per-field accuracy table as an `EvalCard` inline with this turn.
  **Do NOT reproduce that table in your reply** — no `📊 Eval Results`
  heading, no markdown table, no per-field bullet list. Give one short
  sentence: field accuracy rounded to one decimal %
  (e.g. `字段准确率 87.5%`), the one or two weakest fields (lowest
  `accuracy` excluding `not_applicable` rows), and a next-step
  suggestion (`/review` more docs, or tighten a specific description).
- **headless** (`interface: headless`): render a compact markdown table
  sorted by accuracy ascending (weakest fields first). Omit
  `not_applicable` rows or mark them `n/a`. Prepend a one-line
  headline:

  ```
  字段准确率 {field_accuracy_macro:.1%} · 文档准确率 {doc_accuracy:.1%} · {n_reviewed} docs
  ```

  | Field | Accuracy | Correct / Total |
  |---|---|---|
  | seller_name | 62% | 13 / 21 |
  | … | … | … |

  Then one sentence naming the weakest 1–2 fields and a next step.

Edge cases (both modes): every per_field row is `not_applicable` →
say the reviewed examples don't exercise the schema enough; non-empty
`errors` → surface them. **Never** report a `not_applicable` field as
"0% accuracy".

## Cross-project clone

- Whole-project ("fork from X", "make a UK version of us-invoice"):
  `fork_project(src_slug, name, include_docs=false)`. Copies prompts/
  + models/ + project.json (reset `active_version_id`); skips chats,
  reviewed, predictions/_draft, experiments, versions, metrics.
  `include_docs=true` hardlinks docs.
- Single prompt ("试 X 项目的 prompt"): `Bash cp
  {WORKSPACE_ROOT}/src_slug/prompts/{pid}.json
  {WORKSPACE_ROOT}/dst_slug/prompts/`, then `create_experiment` →
  `extract(experiment_id=…)` → review → `promote_experiment` if it wins.
