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

  it('saveActive PUTs and updates byProject on success', async () => {
    const next = [{ name: 'vendor_name', type: 'string', description: 'vendor' }]
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ schema: next }) })
    const err = await useSchema.getState().saveActive('p_a', next, 'notes')
    expect(err).toBeNull()
    expect(useSchema.getState().byProject['p_a']).toEqual(next)
    expect(fetchMock).toHaveBeenCalledWith('/lab/projects/p_a/prompts/active', expect.objectContaining({
      method: 'PUT',
    }))
  })

  it('saveActive surfaces backend error envelope without touching cache', async () => {
    useSchema.setState({ byProject: { p_a: [{ name: 'orig', type: 'string', description: '' }] } })
    fetchMock.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: { error_code: 'invalid_schema_field', error_message_en: 'name must be snake_case' } }),
    })
    const err = await useSchema.getState().saveActive('p_a', [{ name: 'BadCase', type: 'string', description: '' }])
    expect(err?.error_code).toBe('invalid_schema_field')
    // Cache must remain untouched on failure so the UI can keep showing the persisted state.
    expect(useSchema.getState().byProject['p_a']).toEqual([{ name: 'orig', type: 'string', description: '' }])
  })
})
