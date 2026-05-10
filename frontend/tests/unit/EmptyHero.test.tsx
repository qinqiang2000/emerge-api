import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import EmptyHero from '../../src/components/Empty/EmptyHero'

describe('EmptyHero', () => {
  const noop = () => {}

  it('renders eyebrow with project name', () => {
    render(<EmptyHero projectName="tax-forms" onAttach={noop} onStarter={noop} />)
    expect(screen.getByText('~/projects/tax-forms/')).toBeInTheDocument()
  })

  it('renders eyebrow without project name', () => {
    render(<EmptyHero onAttach={noop} onStarter={noop} />)
    expect(screen.getByText('~/projects/')).toBeInTheDocument()
  })

  it('renders headline with emphasis', () => {
    render(<EmptyHero onAttach={noop} onStarter={noop} />)
    expect(screen.getByRole('heading')).toBeInTheDocument()
    const h1 = screen.getByRole('heading')
    expect(h1.textContent).toContain('An empty folder, a willing agent,')
    expect(h1.textContent).toContain('and a stack of PDFs.')
    const em = h1.querySelector('em')
    expect(em).toBeTruthy()
    expect(em?.textContent).toBe('and a stack of PDFs.')
  })

  it('renders drop zone', () => {
    render(<EmptyHero onAttach={noop} onStarter={noop} />)
    expect(screen.getByText('drop PDFs or images here')).toBeInTheDocument()
  })

  it('renders three starter buttons', () => {
    render(<EmptyHero onAttach={noop} onStarter={noop} />)
    const buttons = screen.getAllByRole('button')
    // 3 starter buttons (invite chip uses role="button" too)
    const starterButtons = buttons.filter(b => b.classList.contains('starter'))
    expect(starterButtons).toHaveLength(3)
  })

  it('calls onStarter with correct text when starter clicked', async () => {
    const onStarter = vi.fn()
    render(<EmptyHero onAttach={noop} onStarter={onStarter} />)
    const starters = screen.getAllByRole('button').filter(b => b.classList.contains('starter'))
    await userEvent.click(starters[0])
    expect(onStarter).toHaveBeenCalledWith(
      'Extract invoices from these PDFs — vendor, totals, line items',
    )
  })

  it('calls onStarter with second starter text', async () => {
    const onStarter = vi.fn()
    render(<EmptyHero onAttach={noop} onStarter={onStarter} />)
    const starters = screen.getAllByRole('button').filter(b => b.classList.contains('starter'))
    await userEvent.click(starters[1])
    expect(onStarter).toHaveBeenCalledWith(
      "Build me a schema, then I'll edit it before extraction",
    )
  })

  it('calls onStarter with third starter text', async () => {
    const onStarter = vi.fn()
    render(<EmptyHero onAttach={noop} onStarter={onStarter} />)
    const starters = screen.getAllByRole('button').filter(b => b.classList.contains('starter'))
    await userEvent.click(starters[2])
    expect(onStarter).toHaveBeenCalledWith(
      'Pull contract terms — parties, effective date, renewal clause',
    )
  })

  it('calls onStarter with /init when invite chip is clicked', async () => {
    const onStarter = vi.fn()
    render(<EmptyHero onAttach={noop} onStarter={onStarter} />)
    const inviteChip = screen.getByRole('button', { name: /\/init/i })
    await userEvent.click(inviteChip)
    expect(onStarter).toHaveBeenCalledWith('/init')
  })

  it('calls onAttach when files are dropped on drop zone', () => {
    const onAttach = vi.fn()
    render(<EmptyHero onAttach={onAttach} onStarter={noop} />)
    const dropZone = screen.getByText('drop PDFs or images here').closest('.drop')!
    const file = new File(['content'], 'test.pdf', { type: 'application/pdf' })
    fireEvent.drop(dropZone, {
      dataTransfer: { files: [file] },
    })
    expect(onAttach).toHaveBeenCalledWith([file])
  })
})
