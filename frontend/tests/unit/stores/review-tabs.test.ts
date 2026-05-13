import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useReview } from '../../../src/stores/review'

describe('useReview tab state', () => {
  beforeEach(() => {
    useReview.setState({
      activeProjectId: null, activeDocId: null,
      page: 1, pageCount: 1, loading: false, saving: false, err: null,
      entities: [], evidence: null, notes: {},
      activeTabKey: 'active', predictionsByExp: {},
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('loadExperimentPrediction caches the GET result keyed by experiment_id', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ entities: [{ supplier: 'EX' }] }),
    }))
    useReview.setState({ activeProjectId: 'p_x', activeDocId: 'd_y' })
    await useReview.getState().loadExperimentPrediction('ex_a')
    const s = useReview.getState()
    expect(s.predictionsByExp['ex_a']).toBeTruthy()
    expect(s.predictionsByExp['ex_a']?.entities[0]).toEqual({ supplier: 'EX' })
  })

  it('loadExperimentPrediction is idempotent (does not refetch the same id)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ entities: [{}] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    useReview.setState({ activeProjectId: 'p_x', activeDocId: 'd_y' })
    await useReview.getState().loadExperimentPrediction('ex_a')
    await useReview.getState().loadExperimentPrediction('ex_a')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('setActiveTab switches between active and an experiment tab without losing active data', () => {
    useReview.setState({
      activeTabKey: 'active',
      entities: [{ supplier: 'ACTIVE_VAL' }],
      predictionsByExp: { 'ex_a': { entities: [{ supplier: 'EXP_VAL' }] } },
    })
    useReview.getState().setActiveTab('ex_a')
    expect(useReview.getState().activeTabKey).toBe('ex_a')
    // entities (active tab data) untouched
    expect(useReview.getState().entities[0]).toEqual({ supplier: 'ACTIVE_VAL' })
  })

  it('open() resets tab state when doc changes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 404, json: async () => ({}),
    }))
    useReview.setState({
      activeProjectId: 'p_x', activeDocId: 'd_old',
      activeTabKey: 'ex_a',
      predictionsByExp: { ex_a: { entities: [{}] } },
    })
    await useReview.getState().open('p_x', 'd_new')
    const s = useReview.getState()
    expect(s.activeTabKey).toBe('active')
    expect(s.predictionsByExp).toEqual({})
  })

  it('runExperimentPrediction POSTs and overrides cached extract', async () => {
    let postCalled = false
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url: string, opts?: { method?: string }) => {
      if (opts?.method === 'POST') {
        postCalled = true
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ entities: [{ supplier: 'FRESH' }] }),
        })
      }
      return Promise.resolve({
        ok: true, status: 200, json: async () => ({ entities: [{ supplier: 'OLD' }] }),
      })
    }))
    useReview.setState({ activeProjectId: 'p_x', activeDocId: 'd_y' })
    await useReview.getState().loadExperimentPrediction('ex_a')  // GET → OLD
    await useReview.getState().runExperimentPrediction('ex_a')   // POST → FRESH
    expect(postCalled).toBe(true)
    const cached = useReview.getState().predictionsByExp['ex_a']
    expect((cached?.entities[0] as Record<string, unknown>)?.supplier).toBe('FRESH')
  })
})
