export interface FieldScoreSummary {
  field: string
  tp: number
  fp: number
  fn: number
  support: number
  precision: number
  recall: number
  f1: number
  accuracy: number | null
}

export interface ScoreResultSummary {
  n_docs: number
  n_reviewed: number
  macro_f1: number
  doc_accuracy: number | null
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
  macro_f1: number
  n_reviewed: number
}
