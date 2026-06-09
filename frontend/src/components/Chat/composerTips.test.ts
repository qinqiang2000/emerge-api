import { describe, expect, it } from 'vitest'

import { pickTipKey, type TipCtx } from './composerTips'

// Sensible "settled project, idle" baseline; each test overrides the one
// dimension under examination so the priority order is exercised in isolation.
const base: TipCtx = {
  unbound: false,
  docCount: 5,
  fieldCount: 3,
  pendingReady: 0,
  pendingInFlight: 0,
  hasText: false,
  competent: true,
  hasEvents: true,
}

describe('pickTipKey priority', () => {
  it('in-flight upload wins over everything', () => {
    expect(pickTipKey({ ...base, pendingInFlight: 2, pendingReady: 1, unbound: true }))
      .toBe('tip.uploading')
  })

  it('staged files (no text typed) → filesReady', () => {
    expect(pickTipKey({ ...base, pendingReady: 2, hasText: false })).toBe('tip.filesReady')
  })

  it('staged files but user is typing → falls through to context', () => {
    expect(pickTipKey({ ...base, pendingReady: 2, hasText: true, unbound: true, competent: false }))
      .toBe('tip.unbound.new')
  })

  it('unbound newcomer → discovery tip (replaces old /help nudge)', () => {
    expect(pickTipKey({ ...base, unbound: true, competent: false })).toBe('tip.unbound.new')
  })

  it('unbound but competent → continue/start tip', () => {
    expect(pickTipKey({ ...base, unbound: true, competent: true })).toBe('tip.unbound.competent')
  })

  it('project with no fields → noFields', () => {
    expect(pickTipKey({ ...base, fieldCount: 0 })).toBe('tip.noFields')
  })

  it('project with fields but no docs → noDocs', () => {
    expect(pickTipKey({ ...base, docCount: 0 })).toBe('tip.noDocs')
  })

  it('docs + fields but no conversation yet → run', () => {
    expect(pickTipKey({ ...base, hasEvents: false })).toBe('tip.run')
  })

  it('settled project → one of the rotating power tips', () => {
    expect(['tip.review', 'tip.compare', 'tip.publish', 'tip.slash'])
      .toContain(pickTipKey(base))
  })
})
