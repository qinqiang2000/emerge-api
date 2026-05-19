// tests/unit/Chat/ChatHistoryActions.test.tsx
//
// Contract for the shared chip cluster + history popover used by both the
// main shell ConvHeader and the review overlay's compact header. Variants
// only affect chrome: `full` renders `.tip` labels on the chips, `compact`
// renders icon-only. Both variants expose the same aria-labels and call
// the same callbacks.

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ChatHistoryActions from '../../../src/components/Chat/ChatHistoryActions'
import type { ChatSummary } from '../../../src/lib/api'

const CHATS: ChatSummary[] = [
  { chat_id: 'c_aaaaaaaaaaaa', label: 'tune weak fields', kind: 'tune', ts_iso: '2026-05-12T14:08:00+00:00', n_events: 12 },
  { chat_id: 'c_bbbbbbbbbbbb', label: 'run batch', kind: 'run', ts_iso: '2026-05-12T14:02:00+00:00', n_events: 5 },
]

describe('ChatHistoryActions — full variant', () => {
  it('renders both chips with `.tip` labels and no popover initially', () => {
    render(<ChatHistoryActions activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.getByLabelText('Chat history')).toBeInTheDocument()
    expect(screen.getByLabelText('New chat')).toBeInTheDocument()
    // `.tip` labels are present in full mode (the rendered text appears
    // adjacent to the chip even though it's visually hidden until hover).
    expect(screen.getAllByText('Chat history').length).toBeGreaterThan(0)
    expect(screen.queryByText('in project')).not.toBeInTheDocument()
  })

  it('opens the popover on history-chip click, calls onOpen, lists rows, highlights the active one', () => {
    const onOpen = vi.fn()
    render(<ChatHistoryActions activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={onOpen} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(onOpen).toHaveBeenCalled()
    expect(screen.getByText('in project')).toBeInTheDocument()
    expect(screen.getByText('us-invoice')).toBeInTheDocument()
    expect(screen.getByText('tune weak fields')).toBeInTheDocument()
    expect(screen.getByText('run batch')).toBeInTheDocument()
    const activeRow = screen.getByText('tune weak fields').closest('.h-row')
    expect(activeRow).toHaveClass('active')
  })

  it('clicking a row calls onSwitch with that chat id and closes the popover', () => {
    const onSwitch = vi.fn()
    render(<ChatHistoryActions activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={vi.fn()} onSwitch={onSwitch} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    fireEvent.click(screen.getByText('run batch'))
    expect(onSwitch).toHaveBeenCalledWith('c_bbbbbbbbbbbb')
    expect(screen.queryByText('in project')).not.toBeInTheDocument()
  })

  it('clicking the new-chat chip calls onNew', () => {
    const onNew = vi.fn()
    render(<ChatHistoryActions activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={onNew} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('New chat'))
    expect(onNew).toHaveBeenCalled()
  })

  it('shows the empty state when there are no chats', () => {
    render(<ChatHistoryActions activeProject="us-invoice" currentChatId="c_x" chats={[]} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('No sessions yet.')).toBeInTheDocument()
  })

  it('Escape closes the popover', () => {
    render(<ChatHistoryActions activeProject="us-invoice" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('in project')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByText('in project')).not.toBeInTheDocument()
  })

  it('outside click closes the popover', () => {
    render(
      <>
        <ChatHistoryActions activeProject="us-invoice" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />
        <div data-testid="outside">outside</div>
      </>,
    )
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('in project')).toBeInTheDocument()
    // The mousedown listener is attached on a setTimeout(_, 0); flush the
    // microtask queue so the listener is live before we dispatch.
    return new Promise<void>(resolve => {
      setTimeout(() => {
        fireEvent.mouseDown(screen.getByTestId('outside'))
        expect(screen.queryByText('in project')).not.toBeInTheDocument()
        resolve()
      }, 0)
    })
  })

  it('closes the popover when activeProject changes', () => {
    const { rerender } = render(<ChatHistoryActions activeProject="us-invoice" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('in project')).toBeInTheDocument()
    rerender(<ChatHistoryActions activeProject="contracts" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.queryByText('in project')).not.toBeInTheDocument()
  })

  it('shows the UNBOUND scope label when scope="unbound"', () => {
    render(
      <ChatHistoryActions
        scope="unbound"
        activeProject=""
        currentChatId="c_x"
        chats={CHATS}
        onNew={vi.fn()}
        onSwitch={vi.fn()}
        onOpen={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('unbound')).toBeInTheDocument()
    // Project name slot is intentionally blank for unbound scope.
    expect(screen.queryByText('us-invoice')).not.toBeInTheDocument()
  })

  it('shows the unbound empty-state copy when scope="unbound" and chats=[]', () => {
    render(
      <ChatHistoryActions
        scope="unbound"
        activeProject=""
        currentChatId="c_x"
        chats={[]}
        onNew={vi.fn()}
        onSwitch={vi.fn()}
        onOpen={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('No conversations yet.')).toBeInTheDocument()
  })

  it('wraps with `.conv-hd` in full variant', () => {
    const { container } = render(<ChatHistoryActions activeProject="p" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} />)
    expect(container.querySelector('.conv-hd')).toBeInTheDocument()
    expect(container.querySelector('.rev-chat-hd-actions')).not.toBeInTheDocument()
    // chips use the `.chip` class
    expect(container.querySelectorAll('.conv-hd .chip').length).toBe(2)
  })
})

describe('ChatHistoryActions — compact variant', () => {
  it('renders the same aria-labels and wraps with `.rev-chat-hd-actions`', () => {
    const { container } = render(
      <ChatHistoryActions variant="compact" activeProject="us-invoice" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />,
    )
    expect(screen.getByLabelText('Chat history')).toBeInTheDocument()
    expect(screen.getByLabelText('New chat')).toBeInTheDocument()
    expect(container.querySelector('.rev-chat-hd-actions')).toBeInTheDocument()
    expect(container.querySelector('.conv-hd')).not.toBeInTheDocument()
  })

  it('renders icon-only — no `.tip` labels', () => {
    const { container } = render(
      <ChatHistoryActions variant="compact" activeProject="p" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />,
    )
    expect(container.querySelector('.tip')).not.toBeInTheDocument()
    expect(screen.queryByText('Chat history')).not.toBeInTheDocument()
  })

  it('opens the popover INSIDE the cluster (so absolute positioning anchors to it)', () => {
    const { container } = render(
      <ChatHistoryActions variant="compact" activeProject="p" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />,
    )
    fireEvent.click(screen.getByLabelText('Chat history'))
    const cluster = container.querySelector('.rev-chat-hd-actions')!
    expect(cluster.querySelector('.hist-pop')).toBeInTheDocument()
  })

  it('clicking new-chat calls onNew', () => {
    const onNew = vi.fn()
    render(<ChatHistoryActions variant="compact" activeProject="p" currentChatId="c_x" chats={CHATS} onNew={onNew} onSwitch={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('New chat'))
    expect(onNew).toHaveBeenCalled()
  })

  it('clicking a row calls onSwitch and closes the popover', () => {
    const onSwitch = vi.fn()
    render(<ChatHistoryActions variant="compact" activeProject="p" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={onSwitch} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    fireEvent.click(screen.getByText('run batch'))
    expect(onSwitch).toHaveBeenCalledWith('c_bbbbbbbbbbbb')
    expect(screen.queryByText('in project')).not.toBeInTheDocument()
  })

  it('Escape closes the popover', () => {
    render(<ChatHistoryActions variant="compact" activeProject="p" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('in project')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByText('in project')).not.toBeInTheDocument()
  })

  it('calls onOpen when popover toggles open', () => {
    const onOpen = vi.fn()
    render(<ChatHistoryActions variant="compact" activeProject="p" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={onOpen} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(onOpen).toHaveBeenCalledTimes(1)
  })
})
