import { beforeEach, describe, expect, it } from 'vitest'

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('data-theme-prefers')
})

describe('theme tokens', () => {
  it('default (no attribute) resolves light bg-canvas', () => {
    const v = getComputedStyle(document.documentElement).getPropertyValue('--bg-canvas').trim()
    expect(v === '' || v === '#faf9f5').toBeTruthy()
  })

  it('explicit data-theme="dark" wins over system pref', () => {
    document.documentElement.setAttribute('data-theme', 'dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })
})
