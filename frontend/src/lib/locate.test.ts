import { describe, it, expect, vi, afterEach } from 'vitest'
import { fetchLocate, evidencePageOf, type FieldLocation } from './locate'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('fetchLocate', () => {
  it('POSTs entities+evidence to the locate endpoint and returns the result', async () => {
    const result: FieldLocation[] = [
      { entity_index: 0, path: 'invoice_number', rects: [[1, 2, 3, 4]], page: 1, status: 'exact', score: 1 },
    ]
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => result,
    })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    const out = await fetchLocate(
      'my-slug',
      'inv 1.pdf',
      [{ invoice_number: 'A-100' }],
      [{ invoice_number: 1 }],
    )
    expect(out).toEqual(result)

    // URL is encoded, carries lang, no `page` query param, POST + JSON body.
    const [url, init] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toContain('/lab/projects/my-slug/docs/by-name/inv%201.pdf/locate')
    expect(url).toContain('lang=zh')
    expect(url).not.toContain('page=')
    expect(init.method).toBe('POST')
    const body = JSON.parse(init.body as string)
    expect(body).toEqual({
      entities: [{ invoice_number: 'A-100' }],
      evidence: [{ invoice_number: 1 }],
    })
  })

  it('honours an explicit lang argument', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => [] })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)
    await fetchLocate('s', 'f.pdf', [{}], null, 'en')
    const [url] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toContain('lang=en')
  })

  it('returns [] on a 404 (graceful — locate is an enhancement, never crashes review)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })) as unknown as typeof fetch)
    const out = await fetchLocate('s', 'missing.pdf', [{ a: 1 }], null)
    expect(out).toEqual([])
  })

  it('returns [] when the network throws', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down') }) as unknown as typeof fetch)
    const out = await fetchLocate('s', 'f.pdf', [{ a: 1 }], null)
    expect(out).toEqual([])
  })

  it('returns [] when the response body is not an array', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ error_code: 'bad_request' }) })) as unknown as typeof fetch)
    const out = await fetchLocate('s', 'f.pdf', [{ a: 1 }], null)
    expect(out).toEqual([])
  })
})

// Regression: field-source-grounding evolved _evidence from {field: int} to
// {field: {page, source}}. evidencePageOf must resolve both forms and never
// return "[object Object]" as a string.
describe('evidencePageOf', () => {
  it('extracts page from new-form {page, source} — regression for p[object Object] bug', () => {
    expect(evidencePageOf({ page: 2, source: 'Inv #123' })).toBe(2)
  })
  it('extracts page from legacy bare-integer form', () => {
    expect(evidencePageOf(3)).toBe(3)
  })
  it('returns null for null', () => {
    expect(evidencePageOf(null)).toBeNull()
  })
  it('returns null for undefined', () => {
    expect(evidencePageOf(undefined)).toBeNull()
  })
  it('returns null when page is null inside the object (derived field)', () => {
    expect(evidencePageOf({ page: null, source: null })).toBeNull()
  })
})
