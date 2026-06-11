// AuditCard adapters (A3) — strict recognition: audit JSON in, rows out;
// anything else (eval score results, error envelopes, garbage) → null so the
// generic ToolCall rendering is never hijacked.
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  adaptAuditReport,
  adaptAuditScore,
  AuditReportCard,
  overallToneClasses,
} from './AuditCard'

const REPORT = {
  run_id: 'au_123',
  created_at: '2026-06-10T08:00:00+00:00',
  group: { '报价单.jpg': '报价单.jpg' },
  checks: [
    { rule: '甲方为环胜', status: 'pass', reason: 'L1: 环胜 == 环胜', level: 'critical', decided_by: 'l1' },
    { rule: '盖红章', status: 'fail', reason: '未见红章', level: 'critical', decided_by: 'judge' },
    { rule: '附物料清单', status: 'fail', reason: '未附', level: 'warning', decided_by: 'judge' },
    { rule: '日期清晰', status: 'unclear', reason: '图不清', level: 'critical', decided_by: 'judge' },
  ],
  overall: 'fail',
}

const SCORE = {
  run_id: 'au_456',
  reviewed: 3,
  accuracy: 0.6667,
  precision: 1.0,
  recall: 0.5,
  tp: 1, fp: 0, fn: 1,
  unclear: 1,
  per_rule: [
    { rule: '甲方为环胜', truth: 'pass', predicted: 'pass', correct: true },
    { rule: '盖红章', truth: 'fail', predicted: 'pass', correct: false },
    { rule: '金额一致', truth: 'pass', predicted: 'unclear', correct: false },
  ],
  unreviewed_rules: ['附物料清单'],
}

// A real extract-eval score result — must NOT be claimed by the audit adapters.
const EVAL_SCORE = {
  field_accuracy_macro: 0.91,
  doc_accuracy: 0.88,
  per_field: [{ field: 'total', accuracy: 0.9, correct: 9, total: 10 }],
  scored_at: 'just now',
}

describe('adaptAuditReport', () => {
  it('adapts a run_audit report (object form)', () => {
    const d = adaptAuditReport(REPORT)
    expect(d).not.toBeNull()
    expect(d!.overall).toBe('fail')
    expect(d!.checks).toHaveLength(4)
    expect(d!.checks[0]).toEqual({
      rule: '甲方为环胜', status: 'pass', reason: 'L1: 环胜 == 环胜',
      level: 'critical', decidedBy: 'l1', evidence: [],
    })
    expect(d!.checks[2].level).toBe('warning')
    expect(d!.checks[3].status).toBe('unclear')
  })

  it('adapts a JSON-string tool_result', () => {
    const d = adaptAuditReport(JSON.stringify(REPORT))
    expect(d?.overall).toBe('fail')
    expect(d?.checks).toHaveLength(4)
  })

  it('tolerates legacy reports without level/decided_by (A0 era)', () => {
    const legacy = {
      ...REPORT,
      overall: 'pass',
      checks: [{ rule: '甲方为环胜', status: 'pass', reason: 'ok' }],
    }
    const d = adaptAuditReport(legacy)
    expect(d?.checks[0].level).toBe('critical')
    expect(d?.checks[0].decidedBy).toBe('judge')
  })

  it('supports the warn overall', () => {
    const d = adaptAuditReport({ ...REPORT, overall: 'warn' })
    expect(d?.overall).toBe('warn')
  })

  it('passes evidence through, dropping malformed entries (B1)', () => {
    const withEv = {
      ...REPORT,
      overall: 'pass',
      checks: [
        {
          rule: '甲方为环胜', status: 'pass', reason: 'ok',
          level: 'critical', decided_by: 'judge',
          evidence: [
            { doc: '报价单.jpg', page: 2, quote: '甲方：环胜' },
            { doc: '收货单.jpg', quote: '370815.56' },   // page absent → null
            { doc: 3, quote: 'bad doc type' },           // malformed → dropped
            { doc: 'x.pdf' },                            // missing quote → dropped
          ],
        },
        { rule: '盖红章', status: 'fail', reason: '未见', level: 'critical', decided_by: 'judge' },
      ],
    }
    const d = adaptAuditReport(withEv)
    expect(d!.checks[0].evidence).toEqual([
      { doc: '报价单.jpg', page: 2, quote: '甲方：环胜' },
      { doc: '收货单.jpg', page: null, quote: '370815.56' },
    ])
    // checks without an evidence key (every legacy report) default to []
    expect(d!.checks[1].evidence).toEqual([])
  })

  it('returns null for eval score results (no hijack)', () => {
    expect(adaptAuditReport(EVAL_SCORE)).toBeNull()
  })

  it('returns null for error envelopes / garbage / non-audit overall', () => {
    expect(adaptAuditReport({ error_code: 'audit_no_rules', error_message_en: 'x' })).toBeNull()
    expect(adaptAuditReport('not json')).toBeNull()
    expect(adaptAuditReport(null)).toBeNull()
    expect(adaptAuditReport(42)).toBeNull()
    expect(adaptAuditReport({ overall: 'complete', checks: [] })).toBeNull()
    expect(adaptAuditReport({ overall: 'pass', checks: [{ rule: 1, status: 'pass' }] })).toBeNull()
  })
})

describe('adaptAuditScore', () => {
  it('adapts a score_audit result, keeping only wrong rows', () => {
    const d = adaptAuditScore(SCORE)
    expect(d).not.toBeNull()
    expect(d!.reviewed).toBe(3)
    expect(d!.accuracy).toBeCloseTo(0.6667)
    expect(d!.unclear).toBe(1)
    expect(d!.wrong).toEqual([
      { rule: '盖红章', truth: 'fail', predicted: 'pass' },
      { rule: '金额一致', truth: 'pass', predicted: 'unclear' },
    ])
    expect(d!.unreviewedRules).toEqual(['附物料清单'])
  })

  it('adapts a JSON-string tool_result', () => {
    expect(adaptAuditScore(JSON.stringify(SCORE))?.reviewed).toBe(3)
  })

  it('returns null for eval score results and run_audit reports (no hijack)', () => {
    expect(adaptAuditScore(EVAL_SCORE)).toBeNull()
    expect(adaptAuditScore(REPORT)).toBeNull()
  })

  it('returns null for error envelopes / garbage', () => {
    expect(adaptAuditScore({ error_code: 'audit_no_rules', error_message_en: 'x' })).toBeNull()
    expect(adaptAuditScore('not json')).toBeNull()
    expect(adaptAuditScore(undefined)).toBeNull()
  })
})

describe('overallToneClasses', () => {
  it('maps the tri-state to semantic tokens (moss/ochre/rose + soft fills)', () => {
    expect(overallToneClasses('pass')).toBe('text-moss bg-moss-soft')
    expect(overallToneClasses('warn')).toBe('text-ochre-2 bg-ochre-soft')
    expect(overallToneClasses('fail')).toBe('text-rose bg-rose-soft')
  })
})

describe('AuditReportCard evidence rendering (B1)', () => {
  it('renders quote sub-lines 「quote」 — doc · pN as muted text', () => {
    const data = adaptAuditReport({
      ...REPORT,
      overall: 'pass',
      checks: [
        {
          rule: '甲方为环胜', status: 'pass', reason: 'ok',
          level: 'critical', decided_by: 'judge',
          evidence: [
            { doc: '报价单.jpg', page: 2, quote: '甲方：环胜' },
            { doc: '收货单.jpg', quote: '370815.56' },
          ],
        },
      ],
    })!
    const { container } = render(<AuditReportCard data={data} />)
    const text = container.textContent ?? ''
    expect(text).toContain('「甲方：环胜」 — 报价单.jpg · p2')
    expect(text).toContain('「370815.56」 — 收货单.jpg')
    expect(text).not.toContain('370815.56」 — 收货单.jpg · p')  // no page → no suffix
    // muted sub-line uses the file's semantic ink-4 convention
    const sub = Array.from(container.querySelectorAll('div')).find(el =>
      el.textContent?.startsWith('「甲方：环胜」'))
    expect(sub?.className).toContain('text-ink-4')
  })

  it('renders no evidence sub-line when a check has none (legacy reports)', () => {
    const data = adaptAuditReport(REPORT)!
    const { container } = render(<AuditReportCard data={data} />)
    expect(container.textContent).not.toContain('「')
  })
})
