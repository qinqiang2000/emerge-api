// tests/unit/stores/review-active-field.test.ts
//
// Activates the new toggle-set on `activeField` (and `setActiveEntityIdx`)
// that landed when FieldEditor stopped owning local state.

import { beforeEach, describe, expect, it } from 'vitest'

import { useReview } from '../../../src/stores/review'

beforeEach(() => {
  useReview.setState({ activeField: null, activeEntityIdx: 0 })
})

describe('useReview.setActiveField', () => {
  it('defaults to null', () => {
    expect(useReview.getState().activeField).toBeNull()
  })

  it('sets the path on first call', () => {
    useReview.getState().setActiveField('buyer_name')
    expect(useReview.getState().activeField).toBe('buyer_name')
  })

  it('switches between different paths', () => {
    useReview.getState().setActiveField('buyer_name')
    useReview.getState().setActiveField('seller_name')
    expect(useReview.getState().activeField).toBe('seller_name')
  })

  it('clicking the same path again clears it (toggle semantics)', () => {
    useReview.getState().setActiveField('buyer_name')
    useReview.getState().setActiveField('buyer_name')
    expect(useReview.getState().activeField).toBeNull()
  })

  it('explicit null deselects', () => {
    useReview.getState().setActiveField('buyer_name')
    useReview.getState().setActiveField(null)
    expect(useReview.getState().activeField).toBeNull()
  })
})

describe('useReview.setActiveEntityIdx', () => {
  it('defaults to 0', () => {
    expect(useReview.getState().activeEntityIdx).toBe(0)
  })

  it('sets a non-negative idx', () => {
    useReview.getState().setActiveEntityIdx(2)
    expect(useReview.getState().activeEntityIdx).toBe(2)
  })

  it('clamps negatives to 0', () => {
    useReview.getState().setActiveEntityIdx(-3)
    expect(useReview.getState().activeEntityIdx).toBe(0)
  })
})

describe('useReview.close', () => {
  it('resets activeField and activeEntityIdx', () => {
    useReview.setState({
      activeProjectId: 'p_x',
      activeFilename: 'foo.pdf',
      activeField: 'buyer_name',
      activeEntityIdx: 3,
    })
    useReview.getState().close()
    expect(useReview.getState().activeField).toBeNull()
    expect(useReview.getState().activeEntityIdx).toBe(0)
  })
})
