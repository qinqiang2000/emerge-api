import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { useLocate } from './locate'
import type { FieldLocation } from '../lib/locate'

const sample: FieldLocation[] = [
  { entity_index: 0, path: 'invoice_number', rects: [[1, 2, 3, 4]], page: 1, status: 'exact', score: 1 },
]

beforeEach(() => {
  useLocate.getState().reset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useLocate', () => {
  it('focus sets focusedPath and toggles off when the same path is re-focused', () => {
    const { focus } = useLocate.getState()
    focus('a')
    expect(useLocate.getState().focusedPath).toBe('a')
    focus('b')
    expect(useLocate.getState().focusedPath).toBe('b')
    focus('b')
    expect(useLocate.getState().focusedPath).toBeNull()
  })

  it('loadFor fetches once per (filename, tabKey) and caches the result', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => sample })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ invoice_number: 'A' }], null)
    expect(useLocate.getState().byKey['f.pdf::active']).toEqual(sample)

    // Second call with the same key must not re-fetch.
    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ invoice_number: 'A' }], null)
    expect((fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1)
  })

  it('caches a 404 empty result so a missed doc is not re-requested', async () => {
    const fetchMock = vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ a: 1 }], null)
    expect(useLocate.getState().byKey['f.pdf::active']).toEqual([])
    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ a: 1 }], null)
    expect((fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1)
  })

  it('keys cache by tab so switching tabs resolves with that tab\'s values', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => sample })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)
    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ a: 1 }], null)
    await useLocate.getState().loadFor('s', 'f.pdf', 'exp_1', [{ a: 2 }], null)
    expect(useLocate.getState().byKey['f.pdf::active']).toEqual(sample)
    expect(useLocate.getState().byKey['f.pdf::exp_1']).toEqual(sample)
    expect((fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(2)
  })

  it('marks empty-entities loads as attempted without fetching', async () => {
    const fetchMock = vi.fn() as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)
    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [], null)
    expect(useLocate.getState().byKey['f.pdf::active']).toEqual([])
    expect((fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(0)
  })

  it('reset clears cache and focus', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => sample })) as unknown as typeof fetch)
    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ a: 1 }], null)
    useLocate.getState().focus('invoice_number')
    useLocate.getState().reset()
    expect(useLocate.getState().byKey).toEqual({})
    expect(useLocate.getState().focusedPath).toBeNull()
  })
})
