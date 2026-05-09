import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import ThemeToggle from '../../src/components/Theme/ThemeToggle'
import { useTheme } from '../../src/stores/theme'

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme')
  localStorage.clear()
  useTheme.setState({ mode: 'system' })
})

describe('ThemeToggle', () => {
  it('renders current mode label', () => {
    render(<ThemeToggle />)
    expect(screen.getByLabelText(/theme: system/i)).toBeInTheDocument()
  })

  it('cycles system -> light -> dark -> system on click', () => {
    render(<ThemeToggle />)
    const btn = screen.getByRole('button', { name: /theme:/i })
    fireEvent.click(btn)
    expect(useTheme.getState().mode).toBe('light')
    fireEvent.click(btn)
    expect(useTheme.getState().mode).toBe('dark')
    fireEvent.click(btn)
    expect(useTheme.getState().mode).toBe('system')
  })

  it('writes data-theme on html when set to dark', () => {
    render(<ThemeToggle />)
    const btn = screen.getByRole('button', { name: /theme:/i })
    fireEvent.click(btn)
    fireEvent.click(btn)
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })
})
