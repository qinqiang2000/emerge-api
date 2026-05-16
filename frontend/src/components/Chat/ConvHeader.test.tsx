// Co-located ConvHeader smoke test. The deep chip + popover assertions live
// in tests/unit/Chat/ChatHistoryActions.test.tsx now; ConvHeader is just a
// thin pass-through that forces `variant="full"`.

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ConvHeader from './ConvHeader'
import type { ChatSummary } from '../../lib/api'

const CHATS: ChatSummary[] = [
  { chat_id: 'c_aaaaaaaaaaaa', label: 'tune weak fields', kind: 'tune', ts_iso: '2026-05-12T14:08:00+00:00', n_events: 12 },
]

describe('ConvHeader', () => {
  it('renders the chat-history + new-chat chips (full variant)', () => {
    const { container } = render(
      <ConvHeader activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />,
    )
    // Full variant uses the `.conv-hd` wrapper (main shell positioning).
    expect(container.querySelector('.conv-hd')).toBeInTheDocument()
    expect(screen.getByLabelText('Chat history')).toBeInTheDocument()
    expect(screen.getByLabelText('New chat')).toBeInTheDocument()
  })

  it('passes activeProject through to the popover header', () => {
    render(
      <ConvHeader activeProject="us-invoice" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />,
    )
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('us-invoice')).toBeInTheDocument()
  })
})
