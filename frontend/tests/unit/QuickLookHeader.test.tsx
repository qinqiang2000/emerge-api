import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import QuickLookHeader from '../../src/components/QuickLook/QuickLookHeader'

describe('QuickLookHeader', () => {
  it('renders prompts/active title with active badge when activeVersionId is set', () => {
    render(<QuickLookHeader target={{ kind: 'prompt', pid: 'p_test' }} activeVersionId="v6" derivedFrom={null} onClose={() => {}} />)
    expect(screen.getByText('prompts/active')).toBeInTheDocument()
    expect(screen.getByText(/v6 · active/)).toBeInTheDocument()
  })

  it('renders v0 · draft when no active version', () => {
    render(<QuickLookHeader target={{ kind: 'prompt', pid: 'p_test' }} activeVersionId={null} derivedFrom={null} onClose={() => {}} />)
    expect(screen.getByText(/v0 · draft/)).toBeInTheDocument()
  })

  it('renders versions/v6 title with frozen badge for version target', () => {
    render(
      <QuickLookHeader
        target={{ kind: 'version', pid: 'p_test', versionId: 'v6' }}
        activeVersionId="v6"
        derivedFrom={null}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('versions/v6')).toBeInTheDocument()
    expect(screen.getByText(/v6 · frozen/)).toBeInTheDocument()
  })

  it('close button invokes onClose', async () => {
    const onClose = vi.fn()
    render(<QuickLookHeader target={{ kind: 'prompt', pid: 'p_test' }} activeVersionId={null} derivedFrom={null} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalled()
  })

  it('renders real derived_from when provided', () => {
    render(
      <QuickLookHeader
        target={{ kind: 'prompt', pid: 'p_abc' }}
        activeVersionId={null}
        derivedFrom="pr_baseline"
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('derived from: pr_baseline')).toBeInTheDocument()
  })

  it('renders cross-project derived_from string', () => {
    render(
      <QuickLookHeader
        target={{ kind: 'prompt', pid: 'p_abc' }}
        activeVersionId={null}
        derivedFrom="p_us_invoice/pr_baseline"
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('derived from: p_us_invoice/pr_baseline')).toBeInTheDocument()
  })

  it('falls back to em dash when derivedFrom is null', () => {
    render(
      <QuickLookHeader
        target={{ kind: 'prompt', pid: 'p_abc' }}
        activeVersionId={null}
        derivedFrom={null}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('derived from: —')).toBeInTheDocument()
  })
})
