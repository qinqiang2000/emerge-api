// frontend/tests/unit/DocItem.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import DocItem from '../../src/components/DocList/DocItem'
import type { DocSummary } from '../../src/types/review'

function makeDoc(overrides: Partial<DocSummary> = {}): DocSummary {
  return {
    doc_id: 'd_abc',
    filename: 'invoice.pdf',
    ext: 'pdf',
    page_count: 1,
    uploaded_at: '2026-05-09T00:00:00Z',
    has_prediction: false,
    has_reviewed: false,
    ...overrides,
  }
}

describe('DocItem', () => {
  it('shows filename + pending status when no prediction', () => {
    render(<DocItem doc={makeDoc()} onClick={() => {}} />)
    expect(screen.getByText('invoice.pdf')).toBeInTheDocument()
    expect(screen.getByText(/pending/i)).toBeInTheDocument()
  })

  it('shows draft when has_prediction but not reviewed', () => {
    render(<DocItem doc={makeDoc({ has_prediction: true })} onClick={() => {}} />)
    expect(screen.getByText(/draft/i)).toBeInTheDocument()
  })

  it('shows reviewed badge when has_reviewed', () => {
    render(<DocItem doc={makeDoc({ has_prediction: true, has_reviewed: true })} onClick={() => {}} />)
    expect(screen.getByText(/reviewed/i)).toBeInTheDocument()
  })

  it('calls onClick when clicked', async () => {
    const onClick = vi.fn()
    render(<DocItem doc={makeDoc()} onClick={onClick} />)
    await userEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledWith('d_abc')
  })
})
