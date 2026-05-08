// frontend/src/types/review.ts
export type DocStatus = 'reviewed' | 'predicted' | 'pending'

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
}

export function docStatus(d: DocSummary): DocStatus {
  if (d.has_reviewed) return 'reviewed'
  if (d.has_prediction) return 'predicted'
  return 'pending'
}
