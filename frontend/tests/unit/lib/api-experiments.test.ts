import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getExperiment,
  getExperimentExtract,
  listExperiments,
  runExperimentExtract,
} from '../../../src/lib/api'

describe('experiment api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('listExperiments calls the right URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    })
    vi.stubGlobal('fetch', fetchMock)
    await listExperiments('p_test12345678')
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/lab/projects/p_test12345678/experiments'),
      expect.anything(),
    )
  })

  it('listExperiments passes include_archived as query param', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    })
    vi.stubGlobal('fetch', fetchMock)
    await listExperiments('p_test12345678', { includeArchived: true })
    const calledUrl = String(fetchMock.mock.calls[0][0])
    expect(calledUrl).toContain('include_archived=true')
  })

  it('getExperimentExtract returns null on 404', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 404, json: async () => ({
        detail: { error_code: 'experiment_extract_not_found' },
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const out = await getExperimentExtract('p_x', 'ex_y', 'd_z')
    expect(out).toBeNull()
  })

  it('runExperimentExtract POSTs and returns payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ entities: [{ x: 1 }] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const out = await runExperimentExtract('p_x', 'ex_y', 'd_z')
    expect((out.entities[0] as Record<string, unknown>).x).toBe(1)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/lab/projects/p_x/experiments/ex_y/extracts/d_z'),
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('getExperiment returns full meta blob', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({
        experiment_id: 'ex_abc', label: 't', prompt_id: 'pr', model_id: 'm',
        status: 'draft', created_at: '2026-05-13', notes: '', eval: null,
        promoted_at: null,
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const meta = await getExperiment('p_x', 'ex_abc')
    expect(meta.label).toBe('t')
    expect(meta.status).toBe('draft')
  })
})
