import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import Composer from '../../src/components/Chat/Composer'

const PLACEHOLDER = 'say something to the agent, or type / for a command…'

describe('Composer', () => {
  it('calls onSubmit on Enter', async () => {
    const onSubmit = vi.fn()
    render(<Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={onSubmit} />)
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, 'hello')
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('hello')
  })

  it('shows slash menu when text starts with /', async () => {
    render(<Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={() => {}} />)
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '/ext')
    // The slash menu renders a .cmd span; the row2 chips also show /extract as <b>.
    // getAllByText handles both; check at least one is in the slashmenu.
    const matches = screen.getAllByText('/extract')
    expect(matches.length).toBeGreaterThanOrEqual(1)
    // The .cmd span inside .slashmenu should be present
    expect(matches.some(el => el.className === 'cmd')).toBe(true)
  })

  it('shows pending attachment chips', () => {
    render(<Composer disabled={false} pending={[{ filename: 'a.pdf' }]} onAttach={(_files: File[]) => {}} onSubmit={() => {}} />)
    expect(screen.getByText('a.pdf')).toBeInTheDocument()
  })

  it('Enter picks the active command, closes the menu, then submits', async () => {
    const onSubmit = vi.fn()
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={onSubmit} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement
    await userEvent.type(input, '/ev')
    expect(container.querySelector('.slashmenu')).not.toBeNull()

    // First Enter: pick the active command (only /eval matches "/ev").
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
    expect(input.value).toBe('/eval ')
    expect(container.querySelector('.slashmenu')).toBeNull()   // menu closed

    // Second Enter: now the menu is gone, plain Enter submits.
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('/eval')
  })

  it('Tab picks the active command, same as Enter', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement
    await userEvent.type(input, '/ev')
    await userEvent.keyboard('{Tab}')
    expect(input.value).toBe('/eval ')
    expect(container.querySelector('.slashmenu')).toBeNull()
  })

  it('typing a full command name closes the menu; Enter then submits it', async () => {
    const onSubmit = vi.fn()
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={onSubmit} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '/eval')
    expect(container.querySelector('.slashmenu')).toBeNull()   // exact match → no menu
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('/eval')
  })

  it('Cmd/Ctrl+Enter submits even while the slash menu is open', async () => {
    const onSubmit = vi.fn()
    render(<Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={onSubmit} />)
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '/ev')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    expect(onSubmit).toHaveBeenCalledWith('/ev')
  })
})
