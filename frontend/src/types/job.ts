// M12.x — turn-event payloads now carry `field_accuracy_macro` alongside
// the legacy `macro_f1` key (backend emits both with the same accuracy value
// during the transition). Frontend pickers prefer `field_accuracy_macro`.
export interface FieldScoreSummary {
  field: string

  // M12.x accuracy-first per-field shape.
  accuracy?: number | null
  correct?: number
  total?: number
  n_absent_both?: number
  not_applicable?: boolean

  // Legacy F1 family — optional, may still appear on older turn JSONL.
  tp?: number
  fp?: number
  fn?: number
  support?: number
  precision?: number
  recall?: number
  f1?: number
}

export interface TurnEvent {
  type: 'turn'
  turn: number
  // M12.x: new headline. Older turns may only emit `macro_f1` (legacy
  // semantics — actual F1 number); current backend emits both with the
  // same accuracy value.
  field_accuracy_macro?: number
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
  /** Focused-tune scope, stamped on the `started` event. Absent/null for a
   *  global `/improve` run. */
  target_fields?: string[] | null
}

export type JobEvent = TurnEvent | JobLifecycleEvent

export type JobStatus = 'pending' | 'running' | 'paused' | 'done' | 'cancelled' | 'error'
