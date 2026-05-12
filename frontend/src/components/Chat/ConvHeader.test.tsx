import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ConvHeader from './ConvHeader'
import type { ChatSummary } from '../../lib/api'

const CHATS: ChatSummary[] = [
  { chat_id: 'c_aaaaaaaaaaaa', label: 'tune weak fields', kind: 'tune', ts_iso: '2026-05-12T14:08:00+00:00', n_events: 12 },
  { chat_id: 'c_bbbbbbbbbbbb', label: 'run batch', kind: 'run', ts_iso: '2026-05-12T14:02:00+00:00', n_events: 5 },
]

describe('ConvHeader', () => {
  it('renders two chips and no popover initially', () => {
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.getByLabelText('Chat history')).toBeInTheDocument()
    expect(screen.getByLabelText('New chat')).toBeInTheDocument()
    expect(screen.queryByText('history')).not.toBeInTheDocument()
  })

  it('opens the popover on history-chip click, calls onOpen, lists rows, highlights the active one', () => {
    const onOpen = vi.fn()
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={onOpen} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(onOpen).toHaveBeenCalled()
    expect(screen.getByText('history')).toBeInTheDocument()
    expect(screen.getByText('us-invoice')).toBeInTheDocument()
    expect(screen.getByText('tune weak fields')).toBeInTheDocument()
    expect(screen.getByText('run batch')).toBeInTheDocument()
    const activeRow = screen.getByText('tune weak fields').closest('.h-row')
    expect(activeRow).toHaveClass('active')
  })

  it('clicking a row calls onSwitch with that chat id and closes the popover', () => {
    const onSwitch = vi.fn()
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={vi.fn()} onSwitch={onSwitch} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    fireEvent.click(screen.getByText('run batch'))
    expect(onSwitch).toHaveBeenCalledWith('c_bbbbbbbbbbbb')
    expect(screen.queryByText('history')).not.toBeInTheDocument()
  })

  it('clicking the new-chat chip calls onNew', () => {
    const onNew = vi.fn()
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={onNew} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('New chat'))
    expect(onNew).toHaveBeenCalled()
  })

  it('shows the empty state when there are no chats', () => {
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_x" chats={[]} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('No sessions yet.')).toBeInTheDocument()
  })

  it('Escape closes the popover', () => {
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('history')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByText('history')).not.toBeInTheDocument()
  })

  it('closes the popover when activeProject changes', () => {
    const { rerender } = render(<ConvHeader activeProject="us-invoice" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('history')).toBeInTheDocument()
    rerender(<ConvHeader activeProject="contracts" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.queryByText('history')).not.toBeInTheDocument()
  })
})
