// frontend/src/types/review.ts
export type DocStatus = 'reviewed' | 'draft' | 'pending'

export interface DocSummary {
  doc_id: string
  filename: string
  ext: string
  page_count: number
  uploaded_at: string
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

export interface ExperimentExtractPayload {
  entities: Record<string, unknown>[]
  _evidence?: Record<string, number | null>[] | null
  _notes?: Record<string, string>
}
