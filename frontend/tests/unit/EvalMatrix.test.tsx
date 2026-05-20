import { describe, expect, it } from 'vitest'

import { applyFilter, groupCellsIntoRows, pct } from '../../src/components/EvalMatrix/filters'
import type { CellVerdict } from '../../src/types/eval'


const C: CellVerdict[] = [
  {
    filename: 'a.pdf', entity_idx: 0, field: 'x', status: 'correct',
    truth: '1', pred: '1', verdict_source: 'exact',
    normalizer: null, judge_reason: null, judge_model: null,
  },
  {
    filename: 'a.pdf', entity_idx: 0, field: 'y', status: 'wrong',
    truth: '2', pred: '3', verdict_source: 'normalize',
    normalizer: null, judge_reason: null, judge_model: null,
  },
  {
    filename: 'b.pdf', entity_idx: 0, field: 'x', status: 'correct',
    truth: '5', pred: '5', verdict_source: 'exact',
    normalizer: null, judge_reason: null, judge_model: null,
  },
  {
    filename: 'b.pdf', entity_idx: 0, field: 'y', status: 'absent_both',
    truth: null, pred: null, verdict_source: 'presence',
    normalizer: null, judge_reason: null, judge_model: null,
  },
]


describe('EvalMatrix filters', () => {
  it('groupCellsIntoRows groups cells by (filename, entity_idx)', () => {
    const g = groupCellsIntoRows(C)
    expect(g.size).toBe(2)
    expect(g.get('a.pdf|0')?.length).toBe(2)
    expect(g.get('b.pdf|0')?.length).toBe(2)
  })

  it('applyFilter "all" returns every row', () => {
    expect(applyFilter(C, 'all').size).toBe(2)
  })

  it('applyFilter "errors_only" drops rows where every cell is correct/absent_both', () => {
    const f = applyFilter(C, 'errors_only')
    expect(f.size).toBe(1)
    expect(f.has('a.pdf|0')).toBe(true) // has the wrong cell
  })

  it('pct formats with one decimal and falls back to em-dash', () => {
    expect(pct(0.92)).toBe('92.0%')
    expect(pct(null)).toBe('—')
    expect(pct(undefined)).toBe('—')
  })
})
