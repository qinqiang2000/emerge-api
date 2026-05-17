// frontend/src/types/review.ts
export type DocStatus = 'reviewed' | 'draft' | 'pending'

export interface DocSummary {
  /** Final on-disk filename — the only doc handle. May include spaces /
   *  parens / unicode after dedupe. Use `encodeURIComponent` before stuffing
   *  it into a URL. */
  filename: string
  ext: string
  page_count: number
  sha256: string
  uploaded_at: string
  /** Pre-dedup name the user uploaded. Display-only; never used for routing. */
  original_name: string
  has_prediction: boolean
  has_reviewed: boolean
}

export interface PredictionPayload {
  entities: Record<string, unknown>[]
  _evidence?: Record<string, number | null>[]
}

export interface ReviewedPayload {
  entities: Record<string, unknown>[]
  source: 'manual' | 'feedback'
  _notes?: Record<string, string>
  _evidence?: Record<string, number | null>[]
}

/** Pro-labeler draft sitting at `reviewed/_pending/{filename}.json`. Same
 *  shape as a Reviewed payload's entities/evidence — but `source` is absent
 *  (the pending zone is its own bucket, not a reviewed sub-type) and
 *  `labeler_model` + `created_at` record provenance. */
export interface PendingPayload {
  entities: Record<string, unknown>[]
  _evidence?: Record<string, number | null>[]
  labeler_model?: string
  created_at?: string
}

export function docStatus(d: DocSummary): DocStatus {
  if (d.has_reviewed) return 'reviewed'
  if (d.has_prediction) return 'draft'
  return 'pending'
}

export type ExperimentStatus = 'draft' | 'ran' | 'archived' | 'promoted'

export interface ExperimentSummary {
  experiment_id: string
  label: string
  prompt_id: string
  model_id: string
  status: ExperimentStatus
  created_at: string
  score: number | null
}

export interface ExperimentEval {
  ran_at: string
  score: number
  per_field: Record<string, number>
  per_doc: Record<string, number>
  run_id: string
  coverage: number
}

export interface Experiment {
  experiment_id: string
  label: string
  prompt_id: string
  model_id: string
  status: ExperimentStatus
  created_at: string
  promoted_at: string | null
  notes: string
  eval: ExperimentEval | null
}

export interface ExperimentPredictionPayload {
  entities: Record<string, unknown>[]
  _evidence?: Record<string, number | null>[] | null
  _notes?: Record<string, string>
}
