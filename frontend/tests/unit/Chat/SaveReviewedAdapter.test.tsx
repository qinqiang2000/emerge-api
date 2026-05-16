// tests/unit/Chat/SaveReviewedAdapter.test.tsx
//
// Phase B contract for the hoisted `save_reviewed` chip row:
//   1. Renders given a save_reviewed tool_call event with notes
//   2. Chip click triggers useChat.send with the saved (slug, filename, field)
//      bound as reviewContext — regardless of current review selection
//   3. "忽略" chip dismisses locally without an agent call

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../../src/stores/chat', () => ({ useChat: vi.fn() }))

import { useChat } from '../../../src/stores/chat'
import SaveReviewedAdapter from '../../../src/components/Chat/SaveReviewedAdapter'
import type { ChatEvent } from '../../../src/types/chat'

const mockSend = vi.fn()

function setupChat() {
  const chatState = { send: mockSend }
  ;(useChat as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => selector ? selector(chatState) : chatState,
  )
  ;(useChat as unknown as { getState: () => unknown }).getState = () => chatState
}

function makeCall(overrides: Partial<Extract<ChatEvent, { type: 'tool_call' }>['tool_input']> = {}) {
  return {
    type: 'tool_call' as const,
    tool_use_id: 'tu_save_reviewed',
    tool_name: 'mcp__emerge_tools__save_reviewed',
    tool_input: {
      slug: 'us-invoice',
      filename: '0017292f.pdf',
      entities: [{ receipt_type: '住宿账单' }],
      notes: { receipt_type: 'should be 住宿账单 not 住宿发票' },
      ...overrides,
    },
    tool_result: 'ok',
    ok: true,
  }
}

describe('SaveReviewedAdapter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSend.mockResolvedValue(undefined)
    setupChat()
  })

  it('renders the badge + three chips for a valid save_reviewed call', () => {
    render(<SaveReviewedAdapter call={makeCall()} />)
    // Field + filename surface in the badge.
    expect(screen.getByText('receipt_type')).toBeInTheDocument()
    expect(screen.getByText('0017292f.pdf')).toBeInTheDocument()
    // All three escalation chips.
    expect(screen.getByRole('button', { name: /upgrade note to description/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /upgrade note to global_notes/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /dismiss escalation chips/i })).toBeInTheDocument()
  })

  it('"升级到 description" chip calls send with reviewContext bound to the saved doc/field', () => {
    render(<SaveReviewedAdapter call={makeCall()} />)
    fireEvent.click(screen.getByRole('button', { name: /upgrade note to description/i }))
    expect(mockSend).toHaveBeenCalledTimes(1)
    const args = mockSend.mock.calls[0]
    expect(args[0]).toBe('us-invoice')  // slug from tool_input
    expect(args[1]).toMatch(/description/)
    expect(args[1]).toMatch(/receipt_type/)
    // 4th arg = reviewContext snapshot
    expect(args[3]).toEqual({
      filename: '0017292f.pdf',
      field: 'receipt_type',
      current_value: null,
      entity_index: 0,
    })
  })

  it('"升级到 global_notes" chip calls send with the global-rules prompt', () => {
    render(<SaveReviewedAdapter call={makeCall()} />)
    fireEvent.click(screen.getByRole('button', { name: /upgrade note to global_notes/i }))
    expect(mockSend).toHaveBeenCalledTimes(1)
    const args = mockSend.mock.calls[0]
    expect(args[0]).toBe('us-invoice')
    expect(args[1]).toMatch(/global_notes/)
    expect(args[1]).toMatch(/receipt_type/)
    expect(args[3]).toMatchObject({ filename: '0017292f.pdf', field: 'receipt_type' })
  })

  it('"忽略" chip dismisses locally without calling send', () => {
    render(<SaveReviewedAdapter call={makeCall()} />)
    fireEvent.click(screen.getByRole('button', { name: /dismiss escalation chips/i }))
    expect(mockSend).not.toHaveBeenCalled()
    // After dismiss the chip row is gone.
    expect(screen.queryByRole('button', { name: /upgrade note to description/i })).not.toBeInTheDocument()
  })

  it('renders nothing when tool_input has no notes (e.g. value-correction only call)', () => {
    const callWithoutNotes = makeCall({ notes: {} })
    const { container } = render(<SaveReviewedAdapter call={callWithoutNotes} />)
    // No chip row — nothing to escalate.
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when slug or filename is missing', () => {
    const callMissingSlug = makeCall({ slug: '' })
    const { container } = render(<SaveReviewedAdapter call={callMissingSlug} />)
    expect(container.firstChild).toBeNull()
  })

  it('escalation is bound to the SAVED doc, not the currently-active review selection', () => {
    // Even if some other doc were now active in the review store, the
    // adapter extracts scope from the tool_call's own tool_input — so the
    // escalation prompt stays bound to what the agent actually saved.
    render(<SaveReviewedAdapter call={makeCall()} />)
    fireEvent.click(screen.getByRole('button', { name: /upgrade note to description/i }))
    const args = mockSend.mock.calls[0]
    expect(args[3].filename).toBe('0017292f.pdf')  // saved doc, not whatever store says
  })
})
