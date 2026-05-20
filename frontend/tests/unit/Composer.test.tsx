import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import Composer from '../../src/components/Chat/Composer'

const PLACEHOLDER = 'say something to the agent, or type / for a command…'

describe('Composer', () => {
  it('plain Enter does not submit — only ⌘/Ctrl+Enter does', async () => {
    const onSubmit = vi.fn()
    render(<Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={onSubmit} />)
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, 'hello')
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    // Enter inserted a newline before Ctrl+Enter; trimmed text is still "hello".
    expect(onSubmit).toHaveBeenCalledWith('hello')
  })

  it('shows slash menu when text starts with /', async () => {
    render(<Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={() => {}} />)
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '/ext')
    // The slash menu renders a .cmd span for the matched command.
    const matches = screen.getAllByText('/extract')
    expect(matches.length).toBeGreaterThanOrEqual(1)
    expect(matches.some(el => el.className === 'cmd')).toBe(true)
  })

  it('shows pending attachment chips', () => {
    render(<Composer disabled={false} pending={[{ filename: 'a.pdf' }]} onAttach={(_files: File[]) => {}} onSubmit={() => {}} />)
    expect(screen.getByText('a.pdf')).toBeInTheDocument()
  })

  it('Enter picks the active command and closes the menu; ⌘/Ctrl+Enter then submits', async () => {
    const onSubmit = vi.fn()
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={onSubmit} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement
    await userEvent.type(input, '/ev')
    expect(container.querySelector('.slashmenu')).not.toBeNull()

    // Enter inside the open menu picks the active command (only /eval matches "/ev").
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
    expect(input.value).toBe('/eval ')
    expect(container.querySelector('.slashmenu')).toBeNull()   // menu closed

    // Plain Enter no longer submits when the menu is closed — needs ⌘/Ctrl+Enter.
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
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

  it('typing a full command name closes the menu; ⌘/Ctrl+Enter then submits it', async () => {
    const onSubmit = vi.fn()
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={onSubmit} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '/eval')
    expect(container.querySelector('.slashmenu')).toBeNull()   // exact match → no menu
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
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

  it('typing a path like /Users/... closes the slash menu (treated as a path, not a command)', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement
    // Two gates collaborate here: (a) no command starts with `/u` → no-match
    // gate closes immediately; (b) the second `/` would also trigger the
    // path-shape gate. Either way the user never sees a popup for a path.
    await userEvent.type(input, '/Users/qinqiang02/file.json')
    expect(container.querySelector('.slashmenu')).toBeNull()
    expect(input.value).toBe('/Users/qinqiang02/file.json')
  })

  it('Esc inside the slash menu closes the menu but leaves text intact', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement
    await userEvent.type(input, '/ev')
    expect(container.querySelector('.slashmenu')).not.toBeNull()
    await userEvent.keyboard('{Escape}')
    expect(container.querySelector('.slashmenu')).toBeNull()
    // Text preserved (regression: previously cleared to '').
    expect(input.value).toBe('/ev')
  })

  it('typing a slash prefix with no command match auto-closes the menu (Claude Code CLI behavior)', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement
    // `/i` still has matches (/init, /improve) → menu open.
    await userEvent.type(input, '/i')
    expect(container.querySelector('.slashmenu')).not.toBeNull()
    // `/ix` has no command prefix match → menu closes, no all-commands fallback.
    await userEvent.type(input, 'x')
    expect(container.querySelector('.slashmenu')).toBeNull()
    expect(input.value).toBe('/ix')
    // CJK / non-matching prefix also auto-closes (e.g. /ac大法师).
    await userEvent.clear(input)
    await userEvent.type(input, '/ac大法师')
    expect(container.querySelector('.slashmenu')).toBeNull()
    expect(input.value).toBe('/ac大法师')
  })

  it('Esc on a path-shaped input does not wipe the textarea', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement
    await userEvent.type(input, '/Users/qinqiang02/file.json')
    // Menu already closed because of the second `/`.
    expect(container.querySelector('.slashmenu')).toBeNull()
    // Esc on a textarea with focus runs the "no menu" branch (blur), text intact.
    await userEvent.keyboard('{Escape}')
    expect(input.value).toBe('/Users/qinqiang02/file.json')
  })
})
