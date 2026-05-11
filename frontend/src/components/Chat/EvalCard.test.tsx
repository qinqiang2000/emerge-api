import { describe, it, expect } from 'vitest'
import { adaptScoreResult } from './EvalCard'

const SCORE_JSON = JSON.stringify({
  n_docs: 6, n_reviewed: 5, macro_f1: 0.971, errors: [], ts: '2026-05-11T07-04-00Z', schema_field_count: 7,
  per_field: [
    { field: 'invoice_number', tp: 5, fp: 0, fn: 0, support: 5, precision: 1, recall: 1, f1: 1 },
    { field: 'customer_name', tp: 4, fp: 0, fn: 1, support: 5, precision: 1, recall: 0.8, f1: 0.889 },
  ],
})

describe('adaptScoreResult', () => {
  it('parses the score JSON string from the tool result', () => {
    const out = adaptScoreResult(SCORE_JSON)
    expect(out).not.toBeNull()
    expect(out!.overall).toBeCloseTo(0.971)
    expect(out!.rows).toHaveLength(2)
    expect(out!.rows[1]).toMatchObject({ f: 'customer_name', p: 1, r: 0.8, f1: 0.889 })
    expect(out!.scoredAt).toBe('2026-05-11T07-04-00Z')   // reads `ts`, not just `scored_at`
  })
})
