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

  it('renders drop zone', () => {
    render(<EmptyHero onAttach={noop} onStarter={noop} />)
    expect(screen.getByText('Drag your documents here')).toBeInTheDocument()
  })

  it('renders three starter buttons', () => {
    render(<EmptyHero onAttach={noop} onStarter={noop} />)
    const buttons = screen.getAllByRole('button')
    // 3 starter buttons (invite chip uses role="button" too)
    const starterButtons = buttons.filter(b => b.classList.contains('starter'))
    expect(starterButtons).toHaveLength(3)
  })

  it('calls onStarter with the fork text when first starter clicked', async () => {
    const onStarter = vi.fn()
    render(<EmptyHero onAttach={noop} onStarter={onStarter} />)
    const starters = screen.getAllByRole('button').filter(b => b.classList.contains('starter'))
    await userEvent.click(starters[0])
    expect(onStarter).toHaveBeenCalledWith(
      "Start from one of my existing projects — I don't want to define every field from scratch",
    )
  })

  it('calls onStarter with the invoices text when second starter clicked', async () => {
    const onStarter = vi.fn()
    render(<EmptyHero onAttach={noop} onStarter={onStarter} />)
    const starters = screen.getAllByRole('button').filter(b => b.classList.contains('starter'))
    await userEvent.click(starters[1])
    expect(onStarter).toHaveBeenCalledWith(
      'Pull invoices out of these PDFs — vendor, totals, line items',
    )
  })

  it('calls onStarter with the draft-fields text when third starter clicked', async () => {
    const onStarter = vi.fn()
    render(<EmptyHero onAttach={noop} onStarter={onStarter} />)
    const starters = screen.getAllByRole('button').filter(b => b.classList.contains('starter'))
    await userEvent.click(starters[2])
    expect(onStarter).toHaveBeenCalledWith(
      "Draft the fields first, I'll tweak them before we extract",
    )
  })

  it('calls onStarter with the guide prompt when the invite is clicked', async () => {
    const onStarter = vi.fn()
    render(<EmptyHero onAttach={noop} onStarter={onStarter} />)
    const invite = screen.getByRole('button', { name: /not sure where to start/i })
    await userEvent.click(invite)
    expect(onStarter).toHaveBeenCalledWith(
      "I'm new here — I've got some documents to process but I'm not sure where to begin. Walk me through it.",
    )
  })

  it('calls onAttach when files are dropped on drop zone', () => {
    const onAttach = vi.fn()
    render(<EmptyHero onAttach={onAttach} onStarter={noop} />)
    const dropZone = screen.getByText('Drag your documents here').closest('.drop')!
    const file = new File(['content'], 'test.pdf', { type: 'application/pdf' })
    fireEvent.drop(dropZone, {
      dataTransfer: { files: [file] },
    })
    expect(onAttach).toHaveBeenCalledWith([file])
  })
})
