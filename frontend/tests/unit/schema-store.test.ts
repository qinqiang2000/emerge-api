import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSchema } from '../../src/stores/schema'

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  useSchema.getState().reset()
})
afterEach(() => { vi.unstubAllGlobals() })

describe('useSchema', () => {
  it('caches per project_id and skips network on hit', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => [{ name: 'x', type: 'string', description: '' }] })
    await useSchema.getState().load('p_a')
    await useSchema.getState().load('p_a')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('invalidate(pid) re-fetches on next load', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => [{ name: 'x', type: 'string', description: '' }] })
    await useSchema.getState().load('p_a')
    useSchema.getState().invalidate('p_a')
    await useSchema.getState().load('p_a')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
