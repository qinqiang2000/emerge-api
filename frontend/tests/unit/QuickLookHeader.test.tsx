import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import QuickLookHeader from '../../src/components/QuickLook/QuickLookHeader'

describe('QuickLookHeader', () => {
  it('renders schema.json title with active badge when activeVersionId is set', () => {
    render(<QuickLookHeader target={{ kind: 'schema', pid: 'p_test' }} activeVersionId="v6" onClose={() => {}} />)
    expect(screen.getByText('schema.json')).toBeInTheDocument()
    expect(screen.getByText(/v6 · active/)).toBeInTheDocument()
  })

  it('renders v0 · draft when no active version', () => {
    render(<QuickLookHeader target={{ kind: 'schema', pid: 'p_test' }} activeVersionId={null} onClose={() => {}} />)
    expect(screen.getByText(/v0 · draft/)).toBeInTheDocument()
  })

  it('renders versions/v6 title with frozen badge for version target', () => {
    render(
      <QuickLookHeader
        target={{ kind: 'version', pid: 'p_test', versionId: 'v6' }}
        activeVersionId="v6"
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('versions/v6')).toBeInTheDocument()
    expect(screen.getByText(/v6 · frozen/)).toBeInTheDocument()
  })

  it('lineage row shows em-dash placeholder', () => {
    render(<QuickLookHeader target={{ kind: 'schema', pid: 'p_test' }} activeVersionId={null} onClose={() => {}} />)
    expect(screen.getByText(/derived from: —/)).toBeInTheDocument()
  })

  it('close button invokes onClose', async () => {
    const onClose = vi.fn()
    render(<QuickLookHeader target={{ kind: 'schema', pid: 'p_test' }} activeVersionId={null} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalled()
  })
})
