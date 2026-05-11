import { describe, it, expect } from 'vitest'
import { adaptReadiness } from './PublishStage'

const READINESS_JSON = JSON.stringify({
  checks: [
    { key: 'schema_non_empty', status: 'pass', detail: '7 fields' },
    { key: 'reviewed_and_f1', status: 'pass', detail: 'macro_f1=0.970 (threshold 0.7); n_reviewed=5' },
    { key: 'contract_diff_compat', status: 'fail', detail: 'breaking changes vs v4: removed=[currency]' },
  ],
  soft_warnings: [],
  hard_pass: false,
  macro_f1: 0.97,
  n_reviewed: 5,
})

describe('adaptReadiness', () => {
  it('parses a JSON string and humanizes keys', () => {
    const out = adaptReadiness(READINESS_JSON)
    expect(out).not.toBeNull()
    expect(out!).toHaveLength(3)
    expect(out![0]).toMatchObject({ key: 'schema_non_empty', label: 'Schema non-empty', ok: true, detail: '7 fields' })
    expect(out![2]).toMatchObject({ key: 'contract_diff_compat', label: 'Contract diff compat', ok: false })
  })
  it('also accepts an already-parsed object', () => {
    expect(adaptReadiness(JSON.parse(READINESS_JSON))).toHaveLength(3)
  })
  it('returns null for garbage', () => {
    expect(adaptReadiness('not json')).toBeNull()
    expect(adaptReadiness(42)).toBeNull()
  })
})
