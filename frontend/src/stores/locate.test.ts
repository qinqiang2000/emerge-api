import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { useLocate } from './locate'
import type { FieldLocation } from '../lib/locate'

const sample: FieldLocation[] = [
  { entity_index: 0, path: 'invoice_number', rects: [[1, 2, 3, 4]], page: 1, status: 'exact', score: 1 },
]

// URL-aware mock: /ground returns grounded evidence, /locate returns `sample`.
// Lets tests assert the ground-then-locate ordering distinctly.
function routedFetch(opts?: { groundEvidence?: unknown; locateOk?: boolean }) {
  const grounded = opts?.groundEvidence ?? [{ invoice_number: { page: 1, source: 'INV' } }]
  const locateOk = opts?.locateOk ?? true
  return vi.fn(async (url: string) => {
    if (typeof url === 'string' && url.includes('/ground')) {
      return { ok: true, json: async () => ({ evidence: grounded }) }
    }
    return locateOk
      ? { ok: true, json: async () => sample }
      : { ok: false, status: 404, json: async () => ({}) }
  }) as unknown as typeof fetch
}

function calls(fetchMock: typeof fetch): { url: string }[] {
  return (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls.map((c) => ({
    url: c[0] as string,
  }))
}

beforeEach(() => {
  useLocate.getState().reset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useLocate', () => {
  it('focus sets focusedPath/Entity and toggles off when the same (entity,path) is re-focused', () => {
    const { focus } = useLocate.getState()
    focus('a', 0)
    expect(useLocate.getState().focusedPath).toBe('a')
    expect(useLocate.getState().focusedEntity).toBe(0)
    focus('b', 0)
    expect(useLocate.getState().focusedPath).toBe('b')
    // same path on a DIFFERENT entity is a fresh focus, not a toggle-off
    focus('b', 1)
    expect(useLocate.getState().focusedPath).toBe('b')
    expect(useLocate.getState().focusedEntity).toBe(1)
    // re-focusing the exact (entity,path) pair clears it
    focus('b', 1)
    expect(useLocate.getState().focusedPath).toBeNull()
    expect(useLocate.getState().focusedEntity).toBeNull()
  })

  it('empty evidence locates directly — no ground LLM pass on the render path', async () => {
    const fetchMock = routedFetch()
    vi.stubGlobal('fetch', fetchMock)

    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ invoice_number: 'A' }], null)
    expect(useLocate.getState().byKey['f.pdf::active']).toEqual(sample)
    const urls = calls(fetchMock)
    // straight to locate; locate never blocks on a ground LLM call
    expect(urls.length).toBe(1)
    expect(urls.some((u) => u.url.includes('/ground'))).toBe(false)
    expect(urls[0].url).toContain('/locate')

    // Second call with the same key must not re-fetch.
    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ invoice_number: 'A' }], null)
    expect(calls(fetchMock).length).toBe(1)
  })

  it('non-empty evidence skips the ground pass and locates directly', async () => {
    const fetchMock = routedFetch()
    vi.stubGlobal('fetch', fetchMock)

    await useLocate.getState().loadFor(
      's', 'f.pdf', 'active', [{ invoice_number: 'A' }],
      [{ invoice_number: { page: 1, source: 'INV-1' } }],
    )
    const urls = calls(fetchMock)
    expect(urls.length).toBe(1)
    expect(urls[0].url).toContain('/locate')
  })

  it('experiment tabs do not ground (no groundable blob) but still locate', async () => {
    const fetchMock = routedFetch()
    vi.stubGlobal('fetch', fetchMock)
    await useLocate.getState().loadFor('s', 'f.pdf', 'ex_1', [{ a: 1 }], null)
    const urls = calls(fetchMock)
    expect(urls.length).toBe(1)
    expect(urls[0].url).toContain('/locate')
  })

  it('caches a 404 empty result so a missed doc is not re-requested', async () => {
    const fetchMock = routedFetch({ locateOk: false })
    vi.stubGlobal('fetch', fetchMock)

    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ a: 1 }], null)
    expect(useLocate.getState().byKey['f.pdf::active']).toEqual([])
    const after = calls(fetchMock).length
    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ a: 1 }], null)
    expect(calls(fetchMock).length).toBe(after)
  })

  it('keys cache by tab so switching tabs resolves with that tab\'s values', async () => {
    const fetchMock = routedFetch()
    vi.stubGlobal('fetch', fetchMock)
    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ a: 1 }], null)
    await useLocate.getState().loadFor('s', 'f.pdf', 'exp_1', [{ a: 2 }], null)
    expect(useLocate.getState().byKey['f.pdf::active']).toEqual(sample)
    expect(useLocate.getState().byKey['f.pdf::exp_1']).toEqual(sample)
  })

  it('marks empty-entities loads as attempted without fetching', async () => {
    const fetchMock = routedFetch()
    vi.stubGlobal('fetch', fetchMock)
    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [], null)
    expect(useLocate.getState().byKey['f.pdf::active']).toEqual([])
    expect(calls(fetchMock).length).toBe(0)
  })

  it('reset clears cache and focus', async () => {
    vi.stubGlobal('fetch', routedFetch())
    await useLocate.getState().loadFor('s', 'f.pdf', 'active', [{ a: 1 }], null)
    useLocate.getState().focus('invoice_number', 0)
    useLocate.getState().reset()
    expect(useLocate.getState().byKey).toEqual({})
    expect(useLocate.getState().focusedPath).toBeNull()
    expect(useLocate.getState().focusedEntity).toBeNull()
  })
})
