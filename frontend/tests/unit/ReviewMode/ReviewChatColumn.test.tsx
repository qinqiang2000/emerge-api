// tests/unit/ReviewMode/ReviewChatColumn.test.tsx
//
// Phase A contract for the third column in review mode:
//   1. Renders the active filename + field + value in its header chip
//   2. The close button calls onClose (parent toggles `rightHidden` via this)
//   3. The left splitter persists width to localStorage on drag
//   4. When `rightHidden` is true at the App level, ContextSurface stays hidden
//      (verified separately in App-level integration; here we test column-only)
//   5. NEW: when a project is selected, the header includes the compact
//      ChatHistoryActions chip cluster (Chat history + New chat); when no
//      project is selected, the cluster is hidden.

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ChatPanel pulls many stores; mock it out — we're testing the column's own
// chrome (header, splitter, close), not the chat surface.
vi.mock('../../../src/components/Chat/ChatPanel', () => ({
  default: ({ compact }: { compact?: boolean }) =>
    <div data-testid="mock-chatpanel" data-compact={compact ? '1' : '0'}>chat</div>,
}))

// Mock useChat / useProjects so the header's history-actions wiring is
// deterministic. Both are Zustand stores; the hook is called with a selector
// in production code, so the mock must call the selector with mocked state.
vi.mock('../../../src/stores/chat', () => ({ useChat: vi.fn() }))
vi.mock('../../../src/stores/projects', () => ({ useProjects: vi.fn() }))

import { useChat } from '../../../src/stores/chat'
import { useProjects } from '../../../src/stores/projects'

import ReviewChatColumn, {
  REV_CHAT_WIDTH_KEY,
  REV_CHAT_DEFAULT_W,
  readRevChatWidth,
  writeRevChatWidth,
} from '../../../src/components/ReviewMode/ReviewChatColumn'

const mockNewChat = vi.fn()
const mockSwitchChat = vi.fn()
const mockListChats = vi.fn()

function setupStores({
  selectedSlug = 'us-invoice' as string | null,
  chatId = 'c_test',
  chats = [] as Array<{ chat_id: string; label: string; kind: string; ts_iso: string; n_events: number }>,
} = {}) {
  const projectsState = {
    selectedSlug,
    projects: selectedSlug
      ? [{ project_id: 'p_a', slug: selectedSlug, name: selectedSlug, project_type: 'extraction', active_version_id: null }]
      : [],
  }
  ;(useProjects as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => selector ? selector(projectsState) : projectsState,
  )
  const chatState = {
    chatId,
    chatsByProject: selectedSlug ? { [selectedSlug]: chats } : {},
    newChat: mockNewChat,
    switchChat: mockSwitchChat,
    listChats: mockListChats,
  }
  ;(useChat as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => selector ? selector(chatState) : chatState,
  )
  ;(useChat as unknown as { getState: () => unknown }).getState = () => chatState
}

beforeEach(() => {
  localStorage.clear()
  mockNewChat.mockReset()
  mockSwitchChat.mockReset()
  mockListChats.mockReset()
  setupStores()
})

describe('ReviewChatColumn', () => {
  it('renders the filename + field + value in the header chip', () => {
    render(
      <ReviewChatColumn
        filename="inv-042.pdf"
        activeField="buyer_name"
        activeValue="ACME Sdn Bhd"
        width={REV_CHAT_DEFAULT_W}
        onWidthChange={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('inv-042.pdf')).toBeInTheDocument()
    expect(screen.getByText('buyer_name')).toBeInTheDocument()
    expect(screen.getByText('ACME Sdn Bhd')).toBeInTheDocument()
  })

  it('renders filename only when no field is active', () => {
    render(
      <ReviewChatColumn
        filename="inv-042.pdf"
        activeField={null}
        width={REV_CHAT_DEFAULT_W}
        onWidthChange={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('inv-042.pdf')).toBeInTheDocument()
    expect(screen.queryByText('buyer_name')).not.toBeInTheDocument()
  })

  it('shows a muted "no doc selected" chip when filename is null', () => {
    render(
      <ReviewChatColumn
        filename={null}
        activeField={null}
        width={REV_CHAT_DEFAULT_W}
        onWidthChange={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText(/no doc selected/i)).toBeInTheDocument()
  })

  it('calls onClose when the close button is clicked', () => {
    const onClose = vi.fn()
    render(
      <ReviewChatColumn
        filename="inv-042.pdf"
        activeField={null}
        width={REV_CHAT_DEFAULT_W}
        onWidthChange={() => {}}
        onClose={onClose}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /close chat/i }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('renders the chat surface in compact mode', () => {
    render(
      <ReviewChatColumn
        filename="inv-042.pdf"
        activeField={null}
        width={REV_CHAT_DEFAULT_W}
        onWidthChange={() => {}}
        onClose={() => {}}
      />,
    )
    const panel = screen.getByTestId('mock-chatpanel')
    expect(panel.getAttribute('data-compact')).toBe('1')
  })

  it('splitter drag updates width via onWidthChange and clamps to [280, 560]', () => {
    const onWidthChange = vi.fn()
    render(
      <ReviewChatColumn
        filename="inv-042.pdf"
        activeField={null}
        width={360}
        onWidthChange={onWidthChange}
        onClose={() => {}}
      />,
    )
    const splitter = document.querySelector('.rev-chat-split-v')!
    expect(splitter).toBeInTheDocument()
    // Start drag at x=1000, then move to x=900 → dx = startX - x = 100 → width = 360 + 100 = 460
    fireEvent.mouseDown(splitter, { clientX: 1000 })
    fireEvent.mouseMove(window, { clientX: 900 })
    expect(onWidthChange).toHaveBeenCalledWith(460)
    // Move way left → clamp to max 560
    fireEvent.mouseMove(window, { clientX: 100 })
    expect(onWidthChange).toHaveBeenLastCalledWith(560)
    // Move way right → clamp to min 280
    fireEvent.mouseMove(window, { clientX: 1500 })
    expect(onWidthChange).toHaveBeenLastCalledWith(280)
    fireEvent.mouseUp(window)
  })
})

describe('ReviewChatColumn — ChatHistoryActions in compact header', () => {
  it('renders Chat history + New chat buttons when a project is selected', () => {
    setupStores({ selectedSlug: 'proj_a', chats: [
      { chat_id: 'c_aaaaaaaaaaaa', label: 'tune', kind: 'tune', ts_iso: '2026-05-12T10:00:00+00:00', n_events: 3 },
    ] })
    render(
      <ReviewChatColumn
        filename="inv-042.pdf"
        activeField={null}
        width={REV_CHAT_DEFAULT_W}
        onWidthChange={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByLabelText('Chat history')).toBeInTheDocument()
    expect(screen.getByLabelText('New chat')).toBeInTheDocument()
  })

  it('clicking New chat calls useChat.newChat with the active slug', () => {
    setupStores({ selectedSlug: 'proj_a' })
    render(
      <ReviewChatColumn
        filename="inv-042.pdf"
        activeField={null}
        width={REV_CHAT_DEFAULT_W}
        onWidthChange={() => {}}
        onClose={() => {}}
      />,
    )
    fireEvent.click(screen.getByLabelText('New chat'))
    expect(mockNewChat).toHaveBeenCalledWith('proj_a')
  })

  it('opening the history popover calls listChats then shows rows', () => {
    setupStores({ selectedSlug: 'proj_a', chats: [
      { chat_id: 'c_aaaaaaaaaaaa', label: 'tune weak fields', kind: 'tune', ts_iso: '2026-05-12T14:08:00+00:00', n_events: 12 },
    ] })
    render(
      <ReviewChatColumn
        filename="inv-042.pdf"
        activeField={null}
        width={REV_CHAT_DEFAULT_W}
        onWidthChange={() => {}}
        onClose={() => {}}
      />,
    )
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(mockListChats).toHaveBeenCalledWith('proj_a')
    expect(screen.getByText('tune weak fields')).toBeInTheDocument()
  })

  it('does NOT render the ChatHistoryActions cluster when no project is selected', () => {
    setupStores({ selectedSlug: null })
    const { container } = render(
      <ReviewChatColumn
        filename={null}
        activeField={null}
        width={REV_CHAT_DEFAULT_W}
        onWidthChange={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.queryByLabelText('Chat history')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('New chat')).not.toBeInTheDocument()
    expect(container.querySelector('.rev-chat-hd-actions')).not.toBeInTheDocument()
  })

  it('does NOT render the cluster when slug is p_unset', () => {
    setupStores({ selectedSlug: 'p_unset' })
    render(
      <ReviewChatColumn
        filename={null}
        activeField={null}
        width={REV_CHAT_DEFAULT_W}
        onWidthChange={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.queryByLabelText('Chat history')).not.toBeInTheDocument()
  })
})

describe('readRevChatWidth / writeRevChatWidth', () => {
  it('returns DEFAULT_W when localStorage is empty', () => {
    expect(readRevChatWidth()).toBe(REV_CHAT_DEFAULT_W)
  })

  it('round-trips a valid width', () => {
    writeRevChatWidth(420)
    expect(localStorage.getItem(REV_CHAT_WIDTH_KEY)).toBe('420')
    expect(readRevChatWidth()).toBe(420)
  })

  it('falls back to DEFAULT_W on out-of-range stored value', () => {
    localStorage.setItem(REV_CHAT_WIDTH_KEY, '50')
    expect(readRevChatWidth()).toBe(REV_CHAT_DEFAULT_W)
    localStorage.setItem(REV_CHAT_WIDTH_KEY, '9000')
    expect(readRevChatWidth()).toBe(REV_CHAT_DEFAULT_W)
  })

  it('falls back to DEFAULT_W on garbage stored value', () => {
    localStorage.setItem(REV_CHAT_WIDTH_KEY, 'not-a-number')
    expect(readRevChatWidth()).toBe(REV_CHAT_DEFAULT_W)
  })
})
