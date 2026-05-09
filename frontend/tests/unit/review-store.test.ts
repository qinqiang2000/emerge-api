import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useReview } from '../../src/stores/review'

beforeEach(() => useReview.getState().close())

vi.mock('../../src/lib/api', () => ({
  getReviewed: vi.fn().mockResolvedValue({ entities: [{ a: 1 }, { a: 2 }], source: 'manual' }),
  getPrediction: vi.fn(),
  saveReviewed: vi.fn().mockResolvedValue(undefined),
}))

describe('useReview multi-entity', () => {
  it('open() loads all entities from reviewed payload', async () => {
    await useReview.getState().open('p_a', 'd_a')
    expect(useReview.getState().entities).toEqual([{ a: 1 }, { a: 2 }])
  })

  it('setField(idx, name, value) updates the specified entity only', async () => {
    await useReview.getState().open('p_a', 'd_a')
    useReview.getState().setField(1, 'a', 99)
    expect(useReview.getState().entities[0]).toEqual({ a: 1 })
    expect(useReview.getState().entities[1]).toEqual({ a: 99 })
  })

  it('addEntity() / removeEntity(idx) mutate the array', async () => {
    await useReview.getState().open('p_a', 'd_a')
    useReview.getState().addEntity()
    expect(useReview.getState().entities.length).toBe(3)
    useReview.getState().removeEntity(0)
    expect(useReview.getState().entities).toEqual([{ a: 2 }, {}])
  })
})
