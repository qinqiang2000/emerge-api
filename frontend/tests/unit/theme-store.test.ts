import { beforeEach, describe, expect, it } from 'vitest'

import { useTheme } from '../../src/stores/theme'

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme')
  localStorage.clear()
  useTheme.setState({ mode: 'system' })
})

describe('useTheme', () => {
  it('default mode is system, no data-theme attribute set', () => {
    useTheme.getState().apply()
    expect(useTheme.getState().mode).toBe('system')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })

  it('setMode("dark") writes data-theme=dark and persists to localStorage', () => {
    useTheme.getState().setMode('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('emerge.theme')).toBe('dark')
  })

  it('setMode("light") writes data-theme=light and persists', () => {
    useTheme.getState().setMode('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(localStorage.getItem('emerge.theme')).toBe('light')
  })

  it('setMode("system") removes data-theme and stores "system"', () => {
    useTheme.getState().setMode('dark')
    useTheme.getState().setMode('system')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(localStorage.getItem('emerge.theme')).toBe('system')
  })

  it('hydrate() reads localStorage and applies', () => {
    localStorage.setItem('emerge.theme', 'dark')
    useTheme.getState().hydrate()
    expect(useTheme.getState().mode).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })

  it('hydrate() with missing key defaults to system', () => {
    useTheme.getState().hydrate()
    expect(useTheme.getState().mode).toBe('system')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })

  it('hydrate() with garbage value defaults to system (no throw)', () => {
    localStorage.setItem('emerge.theme', 'magenta')
    useTheme.getState().hydrate()
    expect(useTheme.getState().mode).toBe('system')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })
})
