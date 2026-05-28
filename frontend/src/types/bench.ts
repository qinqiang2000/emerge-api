// TS mirror of `GET /lab/projects/{pid}/bench`.
//
// Bench is a project-level (prompt × model) leaderboard: one row per
// experiment plus an optional synthetic baseline (active prompt × active
// model anchored to the most recent `experiment_id is None` eval). Cells
// align with the active prompt's flat schema; the 6-tick strip is sampled
// from a single lex-sorted set of `reviewed/*.json` basenames shared across
// every row so a column read shows "which doc keeps tripping us up".
//
// `summary_ts` on each row is the audit handle for `?eval=<ts>` deep-link
// into EvalMatrixModal (row click → existing detail surface).

export interface BenchPromptAxisItem {
  id: string
  label: string
  is_active: boolean
  /** Cross-experiment usage count. Archived experiments don't contribute. */
  refs: number
}

export interface BenchModelAxisItem {
  id: string
  label: string
  /** The provider-level model identifier (e.g. `gemini-2.5-flash`). Shown
   *  under the chip label so users distinguish two aliases for the same
   *  provider model. */
  provider_model_id: string
  is_active: boolean
  /** Cross-experiment usage count. Archived experiments don't contribute. */
  refs: number
}

/** Discriminated union: axis chip rendering picks `provider_model_id` only
 *  off the model side. Useful for shared chip components that accept either. */
export type BenchAxisItem = BenchPromptAxisItem | BenchModelAxisItem

export interface BenchHeadline {
  /** Best `field_accuracy_macro` across all non-baseline rows. `null` when
   *  no experiment has been scored yet. */
  best_score: number | null
  best_prompt_id: string | null
  best_model_id: string | null
}

export interface BenchCell {
  /** Count of `correct` + `absent_both` verdicts across all reviewed docs
   *  for this (row, field). */
  correct: number
  /** Count of any non-skip verdicts (correct + wrong + missing + spurious +
   *  absent_both). */
  total: number
  /** Aligned with `BenchResponse.sample_filenames`. Each entry:
   *   - `1`  → every verdict on that filename × field was correct or
   *           absent_both
   *   - `0`  → at least one verdict was wrong / missing / spurious
   *   - `null` → no verdict for that doc (doc not in this eval, or field
   *             not applicable). Length ≤ 6. */
  strip: Array<0 | 1 | null>
}

export type BenchRowKind = 'experiment' | 'baseline'

export type BenchRowStatus = 'draft' | 'ran' | 'promoted' | 'baseline'

export interface BenchRow {
  /** `ex_<id>` for experiments, the literal `"_baseline"` for the synthetic
   *  baseline row. */
  id: string
  kind: BenchRowKind
  prompt_id: string
  model_id: string
  status: BenchRowStatus
  /** True when this row's (prompt_id, model_id) matches the project's
   *  active anchor. Used for the ⭐ chip + sort-to-top affordance. */
  is_active: boolean
  /** `field_accuracy_macro` for the row's eval. `null` when the experiment
   *  has not yet been scored. */
  score: number | null
  /** `row.score - baseline.score`. `null` on the baseline row itself, and
   *  `null` on every row when no baseline eval exists. */
  delta: number | null
  ran_at: string | null
  /** Audit handle into `metrics/eval_<ts>/`. Row click deep-links to
   *  `?eval=<summary_ts>` (EvalMatrixModal). `null` when the experiment
   *  has not been scored. */
  summary_ts: string | null
  /** Keyed by field name (mirrors `BenchResponse.fields`). */
  cells: Record<string, BenchCell>
}

export interface BenchResponse {
  prompts: BenchPromptAxisItem[]
  models: BenchModelAxisItem[]
  /** Flat schema field names from the currently active prompt. Matrix
   *  columns iterate this in order. */
  fields: string[]
  /** Up to 6 lex-sorted reviewed filenames, shared across every row so a
   *  user can scan a column and see which doc misbehaves. */
  sample_filenames: string[]
  headline: BenchHeadline
  rows: BenchRow[]
}
