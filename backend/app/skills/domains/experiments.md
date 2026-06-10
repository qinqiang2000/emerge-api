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
| Switch active | `switch_active_prompt(pid)` / `switch_active_model(mid)` (ask first — affects every later extract) |
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
2. `extract_with_experiment(experiment_id, filename)` — single-doc probe.
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
   If 0, refuse: "compare needs ground truth; reviewed/ is empty — run
   `/review` on a few docs first." Stop.
2. **Ensure candidate model exists** — if `Bash ls models/m_*.json | grep <model_id>`
   has no hit, mint it via `add_model(slug, provider, provider_model_id)`.
3. **`create_experiment`** with `model_id=<m_short>` (defaults prompt to
   active). Idempotent — re-running returns the existing id.
4. **`score(slug)`** to produce the active-baseline eval (writes
   `metrics/eval_<ts_baseline>/`). The `ts` field in the returned blob is
   `<ts_baseline>` — keep it.
5. **`run_experiment_eval(experiment_id)`** to produce the candidate
   eval. The return blob has a `summary_ts` field — that IS the
   `<ts_candidate>` for the compare link. The candidate's `metrics/eval_<ts_candidate>/`
   dir is also written. (The blob's older `ran_at` field is a separate
   audit timestamp and is NOT a valid eval ts — don't use it in the link.)
6. **Markdown delta table** in chat: per-field accuracy deltas sorted by
   `|Δ|`, doc_accuracy A→B, field_accuracy_macro A→B. End with a link:
   `/projects/<slug>/eval/compare?a=<ts_baseline>&b=<summary_ts>`.
7. **Never** auto-`switch_active_model`. Only suggest the command if B
   wins decisively.
8. If `doc_accuracy < 0.5` for either side, prepend "low ground-truth
   coverage — interpret cautiously" to the delta table.

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
  `extract_with_experiment` → review → `promote_experiment` if it wins.
