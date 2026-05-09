export interface FieldScoreSummary {
  field: string
  tp: number
  fp: number
  fn: number
  support: number
  precision: number
  recall: number
  f1: number
}

export interface TurnEvent {
  type: 'turn'
  turn: number
  macro_f1: number
  per_field: FieldScoreSummary[]
  saved: boolean
  rationale?: string
}

export interface JobLifecycleEvent {
  type: 'started' | 'paused' | 'resumed' | 'proposer_failed' | 'ended'
  ts: string
  reason?: 'max_turn' | 'early_stop' | 'cancelled' | 'error'
  best_turn?: number
  best_macro_f1?: number
  error?: string
}

export type JobEvent = TurnEvent | JobLifecycleEvent

export type JobStatus = 'pending' | 'running' | 'paused' | 'done' | 'cancelled' | 'error'
