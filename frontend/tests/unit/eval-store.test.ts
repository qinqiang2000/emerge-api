import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useEval } from '../../src/stores/eval'

const fetchMock = vi.fn()

const SNAPSHOT = {
  n_docs: 6, n_reviewed: 5, macro_f1: 0.971, errors: [],
  ts: '2026-05-11T07-04-00Z', schema_field_count: 7,
  per_field: [
    { field: 'invoice_number', tp: 5, fp: 0, fn: 0, support: 5, precision: 1, recall: 1, f1: 1 },
    { field: 'customer_name', tp: 4, fp: 0, fn: 1, support: 5, precision: 1, recall: 0.8, f1: 0.889 },
  ],
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  useEval.getState().reset()
})
afterEach(() => { vi.unstubAllGlobals() })

describe('useEval', () => {
  it('caches per project_id and skips network on hit', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => SNAPSHOT })
    await useEval.getState().load('p_a')
    await useEval.getState().load('p_a')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(useEval.getState().byProject['p_a']?.macro_f1).toBeCloseTo(0.971)
  })

  it('refresh(pid) bypasses cache and re-fetches', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => SNAPSHOT })
    await useEval.getState().load('p_a')
    await useEval.getState().refresh('p_a')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('stores null when backend returns 404 (no eval yet)', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: 'eval_not_found' }) })
    await useEval.getState().load('p_a')
    expect(useEval.getState().byProject['p_a']).toBeNull()
    // Second load still re-tries (null is "known empty" — but a follow-up
    // refresh after /eval should not be required to set the key first).
    await useEval.getState().load('p_a')
    expect(fetchMock).toHaveBeenCalledTimes(1)  // null counts as cached
  })

  it('invalidate(pid) clears the slice', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => SNAPSHOT })
    await useEval.getState().load('p_a')
    useEval.getState().invalidate('p_a')
    expect(useEval.getState().byProject['p_a']).toBeUndefined()
  })
})
