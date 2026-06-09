import { render, screen, fireEvent } from '@testing-library/react'

import EmptyHero from '../../src/components/Empty/EmptyHero'

// EmptyHero is now stripped to just the eyebrow + drop zone — the old /help
// nudge, guide invite, and starter cards moved into the composer's dynamic
// tip line (see Chat/composerTips.ts), so they're no longer asserted here.
describe('EmptyHero', () => {
  const noop = () => {}

  it('renders eyebrow with project name', () => {
    render(<EmptyHero projectName="tax-forms" onAttach={noop} />)
    expect(screen.getByText('~/projects/tax-forms/')).toBeInTheDocument()
  })

  it('renders eyebrow without project name', () => {
    render(<EmptyHero onAttach={noop} />)
    expect(screen.getByText('~/projects/')).toBeInTheDocument()
  })

  it('renders drop zone', () => {
    render(<EmptyHero onAttach={noop} />)
    expect(screen.getByText('Drag your documents here')).toBeInTheDocument()
  })

  it('does not render the old starter/invite tips', () => {
    render(<EmptyHero onAttach={noop} />)
    expect(screen.queryByText(/not sure where to start/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/just tell me/i)).not.toBeInTheDocument()
  })

  it('calls onAttach when files are dropped on drop zone', () => {
    const onAttach = vi.fn()
    render(<EmptyHero onAttach={onAttach} />)
    const dropZone = screen.getByText('Drag your documents here').closest('.drop')!
    const file = new File(['content'], 'test.pdf', { type: 'application/pdf' })
    fireEvent.drop(dropZone, {
      dataTransfer: { files: [file] },
    })
    expect(onAttach).toHaveBeenCalledWith([file])
  })
})
