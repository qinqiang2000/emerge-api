// M12.x — accuracy-first eval shape.
//
// Headline: `field_accuracy_macro` (mean of per-field accuracy across
// applicable fields). Per-field score carries `accuracy` + `correct/total/
// n_absent_both/not_applicable`. F1 family is optional — legacy summaries
// on disk still carry it, M12.x writes emit nulls.
export interface FieldScoreSummary {
  field: string

  // M12.x accuracy-first fields.
  accuracy: number | null
  correct: number
  total: number
  n_absent_both: number
  not_applicable: boolean

  // Legacy F1 family — optional, null on new writes.
  tp?: number | null
  fp?: number | null
  fn?: number | null
  support?: number | null
  precision?: number | null
  recall?: number | null
  f1?: number | null
}

export interface ScoreResultSummary {
  n_docs: number
  n_reviewed: number
  // M12.x: new headline. Old summaries on disk synthesize this on read via
  // `synthesizeAccuracyMacro()` from per_field.
  field_accuracy_macro: number | null
  // Legacy: only present on pre-M12.x summaries.
  macro_f1: number | null
  // M12.x.c — semantics shifted to smooth (mean of per-doc accuracy) on
  // new writes. Old summaries on disk still carry the strict value here.
  doc_accuracy: number | null
  // M12.x.c — legacy "all cells correct" view; presence implies the
  // sibling `doc_accuracy` is the new smooth definition.
  doc_accuracy_strict?: number | null
  per_field: FieldScoreSummary[]
  errors: string[]
  ts: string
  schema_field_count: number
  judge_used: number
  judge_skipped_budget: number
}

export type CellStatus =
  | 'correct'
  | 'wrong'
  | 'missing'
  | 'spurious'
  | 'absent_both'

export type VerdictSource = 'exact' | 'normalize' | 'llm_judge' | 'presence'

export interface CellVerdict {
  filename: string
  entity_idx: number
  field: string
  status: CellStatus
  truth: string | null
  pred: string | null
  verdict_source: VerdictSource
  normalizer: string | null
  judge_reason: string | null
  judge_model: string | null
}

export interface EvalListEntry {
  ts: string
  meta: {
    prompt_id?: string | null
    model_id?: string | null
    experiment_id?: string | null
    legacy?: boolean
  }
  doc_accuracy: number | null
  field_accuracy_macro?: number | null
  macro_f1?: number | null
  n_reviewed: number
}

// M12.x back-compat synthesis: when a legacy summary doesn't carry
// `field_accuracy_macro`, derive it from per_field accuracy. M12 cells.jsonl
// already encodes the per-cell verdict so per_field.accuracy is correct on
// disk; legacy `macro_f1` is no longer used as a headline.
export function synthesizeAccuracyMacro(
  s: Pick<ScoreResultSummary, 'field_accuracy_macro' | 'per_field'>,
): number | null {
  if (s.field_accuracy_macro != null) return s.field_accuracy_macro
  const applicable = (s.per_field ?? []).filter(
    (p) => !p.not_applicable && typeof p.accuracy === 'number',
  )
  if (applicable.length === 0) return null
  return applicable.reduce((a, p) => a + (p.accuracy ?? 0), 0) / applicable.length
}
