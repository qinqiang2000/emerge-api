// frontend/src/types/review.ts

/** M14 — `_run` envelope mirroring `backend/app/schemas/run.py::RunStamp`.
 *  Every prediction blob (baseline `_draft`, experiment, pre-label `_pending`)
 *  self-stamps so the review tabstrip / matrix UI / score anchor read
 *  identity from the blob, not from project.json at consume time. */
export type RunKind = 'baseline' | 'experiment' | 'pre_label'

export interface RunStamp {
  run_id: string
  ts: string
  model_id?: string | null
  extract_model?: string | null
  model_label?: string | null
  prompt_id?: string | null
  prompt_label?: string | null
  kind: RunKind
}

export type DocStatus = 'reviewed' | 'pending' | 'new'

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
  _evidence?: Record<string, unknown>[]
  /** M14 — self-identifying envelope (model, prompt, kind). Optional so
   *  pre-M14 blobs still load; consumers gate the "baseline" tab on its
   *  presence. */
  _run?: RunStamp | null
}

export interface ReviewedPayload {
  entities: Record<string, unknown>[]
  source: 'manual' | 'feedback'
  _notes?: Record<string, string>
  _evidence?: Record<string, unknown>[]
  /** Phase B — per-field before/after for the fields the human changed this
   *  save pass, keyed by top-level field name. Backend body has
   *  `extra="forbid"`, so send exactly this key and nothing else extra.
   *  Omitted entirely when no field changed. */
  _corrections?: Record<string, { before: unknown; after: unknown }>
}

/** Pro-labeler draft sitting at `reviewed/_pending/{filename}.json`. Same
 *  shape as a Reviewed payload's entities/evidence — but `source` is absent
 *  (the pending zone is its own bucket, not a reviewed sub-type) and
 *  `labeler_model` + `created_at` record provenance. */
export interface PendingPayload {
  entities: Record<string, unknown>[]
  _evidence?: Record<string, unknown>[]
  labeler_model?: string
  created_at?: string
  /** M14 — same envelope as PredictionPayload, with `kind: 'pre_label'`. */
  _run?: RunStamp | null
}

export function docStatus(d: DocSummary): DocStatus {
  if (d.has_reviewed) return 'reviewed'
  if (d.has_prediction) return 'pending'
  return 'new'
}

export type ExperimentStatus = 'draft' | 'ran' | 'archived' | 'promoted'

export interface ExperimentSummary {
  experiment_id: string
  label: string
  prompt_id: string
  /** Content version of `prompt_id` pinned at experiment-creation time. The
   *  derived `label` already embeds it ("Baseline v2 × …"); this is the
   *  structured form. null for pre-versioning experiments. */
  prompt_version: number | null
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
