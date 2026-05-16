import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RawJsonTab from '../../src/components/QuickLook/RawJsonTab'
import { useQuickLook } from '../../src/stores/quicklook'

describe('RawJsonTab', () => {
  beforeEach(() => {
    useQuickLook.setState({
      target: { kind: 'prompt', pid: 'p_test' },
      rawJson: { value: null, loading: false, error: null },
    })
  })

  it('shows loading state initially and resolves to value', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('[\n  {"name":"x"}\n]', { status: 200, headers: { 'content-type': 'text/plain' } }),
    )
    render(<RawJsonTab />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/"name":\s*"x"/)).toBeInTheDocument())
  })

  it('shows error message and retry link on failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('{"detail":{"error_code":"prompt_not_found"}}', { status: 404 }),
    )
    render(<RawJsonTab />)
    await waitFor(() => expect(screen.getByText(/prompt_not_found/i)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })

  it('copy button writes value to clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    useQuickLook.setState({
      target: { kind: 'prompt', pid: 'p_test' },
      rawJson: { value: '[\n  "abc"\n]', loading: false, error: null },
    })
    render(<RawJsonTab />)
    await userEvent.click(screen.getByRole('button', { name: /copy/i }))
    expect(writeText).toHaveBeenCalledWith('[\n  "abc"\n]')
  })
})
