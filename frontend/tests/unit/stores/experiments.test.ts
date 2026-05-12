import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useExperiments } from '../../../src/stores/experiments'

describe('useExperiments', () => {
  beforeEach(() => {
    useExperiments.getState().reset()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('load fetches and caches per project', async () => {
    const rows = [{
      experiment_id: 'ex_a', label: 't', prompt_id: 'pr', model_id: 'm',
      status: 'draft' as const, created_at: '2026-05-13', score: null,
    }]
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => rows,
    })
    vi.stubGlobal('fetch', fetchMock)
    await useExperiments.getState().load('p_test12345678')
    const list = useExperiments.getState().list['p_test12345678']
    expect(list?.length).toBe(1)

    // a second load is a cache hit (no new fetch)
    await useExperiments.getState().load('p_test12345678')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('invalidate clears the cache so next load refetches', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    })
    vi.stubGlobal('fetch', fetchMock)
    await useExperiments.getState().load('p_x')
    useExperiments.getState().invalidate('p_x')
    await useExperiments.getState().load('p_x')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('reset clears all project caches', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    })
    vi.stubGlobal('fetch', fetchMock)
    await useExperiments.getState().load('p_x')
    await useExperiments.getState().load('p_y')
    useExperiments.getState().reset()
    expect(useExperiments.getState().list).toEqual({})
  })

  it('handles HTTP error gracefully (does not poison the cache)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 500, json: async () => ({}),
    })
    vi.stubGlobal('fetch', fetchMock)
    await expect(useExperiments.getState().load('p_err')).rejects.toThrow()
    // The list should NOT be set for the errored project, and loading flag must clear
    expect(useExperiments.getState().list['p_err']).toBeUndefined()
    expect(useExperiments.getState().loading['p_err']).toBeUndefined()
  })
})
