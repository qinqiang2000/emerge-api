// tests/unit/stores/review-pending-fallback.test.ts
//
// useReview.open() chains reviewed → pending → prediction. When reviewed is
// absent and a pending Pro-labeler draft exists, the form prefills from
// pending and the store records `isPending: true` + `labelerModel`.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../../src/lib/api'
import { useReview } from '../../../src/stores/review'

beforeEach(() => {
  useReview.setState({
    activeProjectId: null,
    activeFilename: null,
    entities: [],
    evidence: null,
    notes: {},
    isPending: false,
    labelerModel: null,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useReview.open with pending fallback', () => {
  it('uses reviewed entities when both reviewed and pending exist', async () => {
    vi.spyOn(api, 'getReviewed').mockResolvedValue({
      entities: [{ a: 'reviewed' }], source: 'manual',
    })
    vi.spyOn(api, 'getPrediction').mockResolvedValue(null)
    const pendingSpy = vi.spyOn(api, 'getPending')
    await useReview.getState().open('p1', 'inv.pdf')
    expect(useReview.getState().entities).toEqual([{ a: 'reviewed' }])
    expect(useReview.getState().isPending).toBe(false)
    expect(useReview.getState().labelerModel).toBeNull()
    // Reviewed wins → pending must not be fetched.
    expect(pendingSpy).not.toHaveBeenCalled()
  })

  it('falls back to pending when reviewed is absent', async () => {
    vi.spyOn(api, 'getReviewed').mockResolvedValue(null)
    vi.spyOn(api, 'getPrediction').mockResolvedValue(null)
    vi.spyOn(api, 'getPending').mockResolvedValue({
      entities: [{ a: 'pending' }],
      labeler_model: 'gemini-pro-latest',
    })
    await useReview.getState().open('p1', 'inv.pdf')
    expect(useReview.getState().entities).toEqual([{ a: 'pending' }])
    expect(useReview.getState().isPending).toBe(true)
    expect(useReview.getState().labelerModel).toBe('gemini-pro-latest')
  })

  it('falls back to prediction when neither reviewed nor pending exists', async () => {
    vi.spyOn(api, 'getReviewed').mockResolvedValue(null)
    vi.spyOn(api, 'getPrediction').mockResolvedValue({
      entities: [{ a: 'pred' }],
    })
    vi.spyOn(api, 'getPending').mockResolvedValue(null)
    await useReview.getState().open('p1', 'inv.pdf')
    expect(useReview.getState().entities).toEqual([{ a: 'pred' }])
    expect(useReview.getState().isPending).toBe(false)
    expect(useReview.getState().labelerModel).toBeNull()
  })
})
