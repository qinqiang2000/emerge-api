// BenchSelectionBar — floating action strip that surfaces when ≥1 row is
// selected in the matrix. Two callbacks: onCompare (only when exactly 2 are
// selected) and onClear. Compare is disabled but still rendered with helper
// copy when fewer than 2 — the demo's "compare (need 2)" affordance.
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import BenchSelectionBar from '../BenchSelectionBar'

describe('BenchSelectionBar', () => {
  it('renders nothing (returns null) when selectedIds is empty', () => {
    const { container } = render(
      <BenchSelectionBar
        selectedIds={new Set()}
        onClear={() => {}}
        onCompare={() => {}}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('with 1 selection: shows count, clear, and a disabled "compare (need 2)" CTA', () => {
    render(
      <BenchSelectionBar
        selectedIds={new Set(['r1'])}
        onClear={() => {}}
        onCompare={() => {}}
      />,
    )
    expect(screen.getByText(/1/)).toBeInTheDocument()
    expect(screen.getByText(/selected/i)).toBeInTheDocument()
    const cta = screen.getByRole('button', { name: /need 2/i })
    expect(cta).toBeDisabled()
  })

  it('with 2 selections: compare CTA is enabled and click invokes onCompare', () => {
    const onCompare = vi.fn()
    render(
      <BenchSelectionBar
        selectedIds={new Set(['r1', 'r2'])}
        onClear={() => {}}
        onCompare={onCompare}
      />,
    )
    const cta = screen.getByRole('button', { name: /compare/i })
    expect(cta).not.toBeDisabled()
    fireEvent.click(cta)
    expect(onCompare).toHaveBeenCalledTimes(1)
  })

  it('with 3+ selections: compare CTA stays disabled (only 2-way diff supported)', () => {
    render(
      <BenchSelectionBar
        selectedIds={new Set(['r1', 'r2', 'r3'])}
        onClear={() => {}}
        onCompare={() => {}}
      />,
    )
    const cta = screen.getByRole('button', { name: /need 2/i })
    expect(cta).toBeDisabled()
  })

  it('clicking clear invokes onClear once', () => {
    const onClear = vi.fn()
    render(
      <BenchSelectionBar
        selectedIds={new Set(['r1', 'r2'])}
        onClear={onClear}
        onCompare={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /clear/i }))
    expect(onClear).toHaveBeenCalledTimes(1)
  })

  it('disabled compare button does not invoke onCompare when clicked', () => {
    const onCompare = vi.fn()
    render(
      <BenchSelectionBar
        selectedIds={new Set(['r1'])}
        onClear={() => {}}
        onCompare={onCompare}
      />,
    )
    const cta = screen.getByRole('button', { name: /need 2/i })
    fireEvent.click(cta)
    expect(onCompare).not.toHaveBeenCalled()
  })
})
