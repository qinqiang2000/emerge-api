// Store contract for the audit board cache (`useBoard`).
//
// load(slug) = one report fetch + ONE locate-quotes POST per group doc
// (evidence quotes aggregated across checks, page hints attached), results
// mapped back to their (checkIdx, evIdx) keys via the request-order index.
// Cache-first per slug like useBench; notes round-trip through a 1s debounce.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../lib/api'
import * as locate from '../../lib/locate'
import type { AuditLatestReport } from '../../lib/api'
import type { QuoteLocationResult } from '../../lib/locate'
import { evKey, useBoard } from '../board'

function mkReport(overrides: Partial<AuditLatestReport> = {}): AuditLatestReport {
  return {
    run_id: 'au_001',
    created_at: '2026-06-11T08:00:00+00:00',
    group: { 'a.pdf': 'a.pdf', 'b.jpg': 'b.jpg' },
    overall: 'fail',
    checks: [
      {
        rule: '金额一致', status: 'fail', reason: 'mismatch', level: 'critical', decided_by: 'judge',
        evidence: [
          { doc: 'a.pdf', page: 1, quote: '费用总计 370815.56' },
          { doc: 'b.jpg', page: null, quote: '370000.00' },
        ],
      },
      {
        rule: '甲方为环胜', status: 'pass', reason: 'ok', level: 'critical', decided_by: 'l1',
        evidence: [{ doc: 'a.pdf', page: 2, quote: '环胜电子商务' }],
      },
      // legacy check without evidence — must not break aggregation
      { rule: '盖红章', status: 'unclear', reason: '', level: 'warning', decided_by: 'judge' },
    ],
    ...overrides,
  }
}

function loc(index: number, over: Partial<QuoteLocationResult> = {}): QuoteLocationResult {
  return { index, rects: [[10, 10, 60, 20]], page: 1, status: 'exact', score: 1, ...over }
}

describe('useBoard store', () => {
  beforeEach(() => {
    useBoard.setState({ byProject: {}, loading: {}, errors: {}, notesByProject: {} })
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('load() aggregates quotes per doc → one locate POST per doc, mapped back by index', async () => {
    vi.spyOn(api, 'getAuditLatest').mockResolvedValue(mkReport())
    const locSpy = vi.spyOn(locate, 'fetchLocateQuotes').mockImplementation(
      async (_slug, filename, quotes) =>
        quotes.map((_, i) => loc(i, { page: filename === 'a.pdf' ? i + 1 : 1 })),
    )

    await useBoard.getState().load('proj-a')

    // ONE call per doc, quotes aggregated across checks in scan order
    expect(locSpy).toHaveBeenCalledTimes(2)
    expect(locSpy).toHaveBeenCalledWith('proj-a', 'a.pdf', [
      { page: 1, quote: '费用总计 370815.56' },
      { page: 2, quote: '环胜电子商务' },
    ])
    expect(locSpy).toHaveBeenCalledWith('proj-a', 'b.jpg', [
      { page: null, quote: '370000.00' },
    ])

    const entry = useBoard.getState().byProject['proj-a']
    expect(entry.report?.run_id).toBe('au_001')
    // a.pdf result #0 → check 0 evidence 0; result #1 → check 1 evidence 0
    expect(entry.locations[evKey(0, 0)]).toMatchObject({ page: 1, status: 'exact' })
    expect(entry.locations[evKey(1, 0)]).toMatchObject({ page: 2, status: 'exact' })
    // b.jpg result #0 → check 0 evidence 1
    expect(entry.locations[evKey(0, 1)]).toMatchObject({ page: 1, status: 'exact' })
    // evidence-less check has no location entries
    expect(entry.locations[evKey(2, 0)]).toBeUndefined()
  })

  it('load() is cache-first: a second call does NOT refetch', async () => {
    const repSpy = vi.spyOn(api, 'getAuditLatest').mockResolvedValue(mkReport())
    vi.spyOn(locate, 'fetchLocateQuotes').mockResolvedValue([])

    await useBoard.getState().load('proj-a')
    await useBoard.getState().load('proj-a')

    expect(repSpy).toHaveBeenCalledTimes(1)
  })

  it('invalidate(slug) drops the cache (and notes) so the next load refetches', async () => {
    const repSpy = vi.spyOn(api, 'getAuditLatest').mockResolvedValue(mkReport())
    vi.spyOn(locate, 'fetchLocateQuotes').mockResolvedValue([])
    vi.spyOn(api, 'getBoardNotes').mockResolvedValue({ run_id: 'au_001', elements: [] })

    await useBoard.getState().load('proj-a')
    await useBoard.getState().loadNotes('proj-a')
    useBoard.getState().invalidate('proj-a')

    expect('proj-a' in useBoard.getState().byProject).toBe(false)
    expect('proj-a' in useBoard.getState().notesByProject).toBe(false)

    await useBoard.getState().load('proj-a')
    expect(repSpy).toHaveBeenCalledTimes(2)
  })

  it('no report yet (audit_no_report → null) caches an empty entry, no locate calls', async () => {
    vi.spyOn(api, 'getAuditLatest').mockResolvedValue(null)
    const locSpy = vi.spyOn(locate, 'fetchLocateQuotes')

    await useBoard.getState().load('proj-a')

    expect(useBoard.getState().byProject['proj-a']).toEqual({ report: null, locations: {} })
    expect(locSpy).not.toHaveBeenCalled()
    expect(useBoard.getState().errors['proj-a']).toBeUndefined()
  })

  it('report fetch failure lands in errors[slug], leaves no cache entry, and clears on retry', async () => {
    const repSpy = vi.spyOn(api, 'getAuditLatest').mockRejectedValueOnce(new Error('boom 500'))
    vi.spyOn(locate, 'fetchLocateQuotes').mockResolvedValue([])

    await useBoard.getState().load('proj-a')
    expect(useBoard.getState().errors['proj-a']).toBe('boom 500')
    expect('proj-a' in useBoard.getState().byProject).toBe(false)

    repSpy.mockResolvedValue(mkReport())
    await useBoard.getState().load('proj-a')
    expect(useBoard.getState().errors['proj-a']).toBeUndefined()
    expect(useBoard.getState().byProject['proj-a'].report?.run_id).toBe('au_001')
  })

  it('a doc whose locate degrades to [] still leaves the other docs mapped', async () => {
    vi.spyOn(api, 'getAuditLatest').mockResolvedValue(mkReport())
    vi.spyOn(locate, 'fetchLocateQuotes').mockImplementation(async (_s, filename, quotes) =>
      filename === 'b.jpg' ? [] : quotes.map((_, i) => loc(i)),
    )

    await useBoard.getState().load('proj-a')

    const entry = useBoard.getState().byProject['proj-a']
    expect(entry.locations[evKey(0, 0)]).toBeDefined()
    expect(entry.locations[evKey(0, 1)]).toBeUndefined() // b.jpg degraded
  })

  it('concurrent load() for the same slug dedupes to a single fetch', async () => {
    let resolveFetch: ((r: AuditLatestReport | null) => void) | null = null
    const pending = new Promise<AuditLatestReport | null>((resolve) => { resolveFetch = resolve })
    const repSpy = vi.spyOn(api, 'getAuditLatest').mockReturnValue(pending)
    vi.spyOn(locate, 'fetchLocateQuotes').mockResolvedValue([])

    const p1 = useBoard.getState().load('proj-a')
    const p2 = useBoard.getState().load('proj-a')
    expect(repSpy).toHaveBeenCalledTimes(1)

    resolveFetch!(null)
    await Promise.all([p1, p2])
    expect(repSpy).toHaveBeenCalledTimes(1)
    expect('proj-a' in useBoard.getState().byProject).toBe(true)
  })

  it('loadNotes caches (null = none on the server) and skips refetch', async () => {
    const spy = vi.spyOn(api, 'getBoardNotes').mockResolvedValue(null)

    await useBoard.getState().loadNotes('proj-a')
    await useBoard.getState().loadNotes('proj-a')

    expect(spy).toHaveBeenCalledTimes(1)
    expect(useBoard.getState().notesByProject['proj-a']).toBeNull()
  })

  it('saveNotes debounces 1s — burst of edits collapses to ONE PUT with the last payload', async () => {
    vi.useFakeTimers()
    const putSpy = vi.spyOn(api, 'putBoardNotes').mockResolvedValue()

    useBoard.getState().saveNotes('proj-a', 'au_001', [{ id: 'x', version: 1 }])
    vi.advanceTimersByTime(400)
    useBoard.getState().saveNotes('proj-a', 'au_001', [{ id: 'x', version: 2 }])

    // local cache reflects the latest payload immediately (close→reopen restore)
    expect(useBoard.getState().notesByProject['proj-a']).toEqual({
      run_id: 'au_001',
      elements: [{ id: 'x', version: 2 }],
    })

    // nothing fired yet — still inside the debounce window
    vi.advanceTimersByTime(900)
    expect(putSpy).not.toHaveBeenCalled()

    vi.advanceTimersByTime(200)
    expect(putSpy).toHaveBeenCalledTimes(1)
    expect(putSpy).toHaveBeenCalledWith('proj-a', {
      run_id: 'au_001',
      elements: [{ id: 'x', version: 2 }],
    })
  })

  it('notes roundtrip: a saved payload is what a remount restores from the cache', async () => {
    vi.useFakeTimers()
    vi.spyOn(api, 'putBoardNotes').mockResolvedValue()
    const getSpy = vi.spyOn(api, 'getBoardNotes')

    useBoard.getState().saveNotes('proj-a', 'au_002', [{ id: 'scribble' }])
    vi.advanceTimersByTime(1100)

    // cache-first loadNotes: the saved payload short-circuits the GET
    await useBoard.getState().loadNotes('proj-a')
    expect(getSpy).not.toHaveBeenCalled()
    expect(useBoard.getState().notesByProject['proj-a']).toEqual({
      run_id: 'au_002',
      elements: [{ id: 'scribble' }],
    })
  })
})
