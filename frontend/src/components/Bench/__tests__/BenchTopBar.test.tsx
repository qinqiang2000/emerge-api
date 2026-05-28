// BenchTopBar — minimal modal header above the bench surface.
//
// Renders the `n = N reviewed` meta + a close affordance. The wider
// "Chat / Bench / Review" tab strip from the demo lives in the BenchOverlay
// shell (T6); this leaf only owns its own counters + close button so it can
// be re-used in any future surface that needs a bench-style top bar.
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import BenchTopBar from '../BenchTopBar'

describe('BenchTopBar', () => {
  it('renders the reviewed-doc count using the i18n template', () => {
    render(<BenchTopBar reviewedCount={56} onClose={() => {}} />)
    // i18n key 'bench.topbar.reviewed' is "n = {n} reviewed" — match liberally
    // so we don't tie the test to a literal hairspace.
    expect(screen.getByText(/n\s*=/)).toHaveTextContent(/56/)
    expect(screen.getByText(/reviewed/i)).toBeInTheDocument()
  })

  it('clicking the close button invokes onClose exactly once', () => {
    const onClose = vi.fn()
    render(<BenchTopBar reviewedCount={0} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('zero reviewed docs still renders the counter (not hidden)', () => {
    render(<BenchTopBar reviewedCount={0} onClose={() => {}} />)
    expect(screen.getByText(/n\s*=/)).toHaveTextContent(/0/)
  })
})
