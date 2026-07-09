/**
 * The ✏ annotation (校订稿) carries an anchor to the prompt whose schema its
 * values belong to. Without it the review UI re-renders an adopted prediction
 * through the project's ACTIVE schema, and every field that schema doesn't
 * declare goes invisible — while `save()` still writes it to disk verbatim.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useReview } from '../../src/stores/review'
import * as api from '../../src/lib/api'
import { useDocs } from '../../src/stores/docs'

vi.mock('../../src/lib/api', () => ({
  getReviewed: vi.fn(),
  getPrediction: vi.fn().mockResolvedValue(null),
  getPending: vi.fn().mockResolvedValue(null),
  getExperimentPrediction: vi.fn(),
  runExperimentPrediction: vi.fn(),
  saveReviewed: vi.fn().mockResolvedValue(undefined),
}))

const LODGING = 'pr_0f7xsjph1ty9'

beforeEach(() => {
  useReview.getState().close()
  vi.clearAllMocks()
  vi.mocked(api.getPrediction).mockResolvedValue(null as never)
  vi.mocked(api.getPending).mockResolvedValue(null as never)
  vi.mocked(api.saveReviewed).mockResolvedValue(undefined as never)
  vi.spyOn(useDocs.getState(), 'refresh').mockResolvedValue(undefined as never)
})

describe('annotation prompt anchor', () => {
  it('open() seeds the anchor from the reviewed blob\'s _run stamp', async () => {
    vi.mocked(api.getReviewed).mockResolvedValue({
      entities: [{ checkInDate: '2025-06-18' }],
      source: 'manual',
      _run: { run_id: 'r1', ts: 't', kind: 'reviewed', prompt_id: LODGING },
    } as never)

    await useReview.getState().open('proj', 'westin.pdf')

    expect(useReview.getState().annotationPromptId).toBe(LODGING)
  })

  it('open() leaves the anchor null when the blob predates the stamp', async () => {
    vi.mocked(api.getReviewed).mockResolvedValue({
      entities: [{ a: 1 }], source: 'manual',
    } as never)

    await useReview.getState().open('proj', 'old.pdf')

    expect(useReview.getState().annotationPromptId).toBeNull()
  })

  it('a bulk adopt re-anchors the annotation to the adopted tab\'s prompt', async () => {
    vi.mocked(api.getReviewed).mockResolvedValue(null as never)
    await useReview.getState().open('proj', 'westin.pdf')
    expect(useReview.getState().annotationPromptId).toBeNull()

    useReview.getState().adoptPrediction(
      [{ checkInDate: '2025-06-18', guestName: 'Zhou' }], null, LODGING,
    )

    expect(useReview.getState().annotationPromptId).toBe(LODGING)
    expect(useReview.getState().activeTabKey).toBe('active')
  })

  it('save() ships the anchor so it survives a reload', async () => {
    vi.mocked(api.getReviewed).mockResolvedValue(null as never)
    await useReview.getState().open('proj', 'westin.pdf')
    useReview.getState().adoptPrediction([{ checkInDate: '2025-06-18' }], null, LODGING)

    await useReview.getState().save()

    const payload = vi.mocked(api.saveReviewed).mock.calls[0][2]
    expect(payload.prompt_id).toBe(LODGING)
    // The adopted field is persisted verbatim — the anchor is what makes it
    // visible again on reopen.
    expect(payload.entities).toEqual([{ checkInDate: '2025-06-18' }])
  })

  it('save() omits prompt_id for a hand-typed review (server uses active prompt)', async () => {
    vi.mocked(api.getReviewed).mockResolvedValue({
      entities: [{ a: 1 }], source: 'manual',
    } as never)
    await useReview.getState().open('proj', 'plain.pdf')

    await useReview.getState().save()

    const payload = vi.mocked(api.saveReviewed).mock.calls[0][2]
    expect('prompt_id' in payload).toBe(false)
  })
})
