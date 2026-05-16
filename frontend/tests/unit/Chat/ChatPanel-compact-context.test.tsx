// tests/unit/Chat/ChatPanel-compact-context.test.tsx
//
// Phase B contract: in compact mode, ChatPanel.onSubmit snapshots
// (filename, field, current_value, entity_index) from useReview.getState()
// AT SUBMIT TIME and threads it as the 4th argument to useChat.send.
// Submitting in non-compact mode passes undefined as the 4th arg.

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChatEvent } from '../../../src/types/chat'
import type { DocSummary } from '../../../src/types/review'
import type { SchemaField } from '../../../src/stores/schema'
import type { Project } from '../../../src/lib/api'

vi.mock('../../../src/stores/projects', () => ({ useProjects: vi.fn() }))
vi.mock('../../../src/stores/chat', () => ({ useChat: vi.fn() }))
vi.mock('../../../src/stores/docs', () => ({ useDocs: vi.fn() }))
vi.mock('../../../src/stores/schema', () => ({ useSchema: vi.fn() }))
vi.mock('../../../src/stores/jobs', () => ({ useJob: vi.fn() }))
vi.mock('../../../src/stores/review', () => ({ useReview: vi.fn() }))
vi.mock('../../../src/lib/api', () => ({
  uploadDoc: vi.fn(),
  attachToChat: vi.fn(),
  stageUpload: vi.fn(),
}))

import { useProjects } from '../../../src/stores/projects'
import { useChat } from '../../../src/stores/chat'
import { useDocs } from '../../../src/stores/docs'
import { useSchema } from '../../../src/stores/schema'
import { useJob } from '../../../src/stores/jobs'
import { useReview } from '../../../src/stores/review'
import ChatPanel from '../../../src/components/Chat/ChatPanel'

const mockSend = vi.fn()
const reviewState = {
  activeFilename: null as string | null,
  activeField: null as string | null,
  activeEntityIdx: 0,
  entities: [] as Record<string, unknown>[],
}

function setupStores({
  events = [] as ChatEvent[],
  docs = [] as DocSummary[],
  fields = [] as SchemaField[],
  selectedSlug = 'us-invoice' as string | null,
  projects = [
    { project_id: 'p_a', slug: 'us-invoice', name: 'us-invoice', project_type: 'extraction', active_version_id: null },
  ] as Project[],
} = {}) {
  ;(useProjects as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => {
      const state = { selectedSlug, projects }
      return selector ? selector(state) : state
    },
  )
  const chatState = {
    events,
    send: mockSend,
    busy: false,
    enterProject: vi.fn(),
    deselect: vi.fn(),
    chatId: 'c_test',
    chatsByProject: { [selectedSlug ?? '']: [] },
    listChats: vi.fn(),
    switchChat: vi.fn(),
    newChat: vi.fn(),
    cancel: vi.fn(),
  }
  ;(useChat as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => selector ? selector(chatState) : chatState,
  )
  ;(useChat as unknown as { getState: () => unknown }).getState = () => chatState
  ;(useDocs as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => {
      const state = { byProject: { [selectedSlug ?? '']: docs } }
      return selector ? selector(state) : docs
    },
  )
  ;(useSchema as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => {
      const state = { byProject: { [selectedSlug ?? '']: fields } }
      return selector ? selector(state) : fields
    },
  )
  ;(useJob as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => {
      const state = { byId: {} }
      return selector ? selector(state) : state
    },
  )
  // Review store: hook-call is unused inside ChatPanel; only getState() matters.
  ;(useReview as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    () => reviewState,
  )
  ;(useReview as unknown as { getState: () => typeof reviewState }).getState = () => reviewState
}

async function typeAndSubmit(text: string) {
  const ta = screen.getByPlaceholderText(/say something to the agent/i)
  fireEvent.change(ta, { target: { value: text } })
  // Composer submits the send button when there's text.
  const sendBtn = screen.getByLabelText(/send message/i)
  fireEvent.click(sendBtn)
}

describe('ChatPanel compact mode — review_context snapshot', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSend.mockResolvedValue(undefined)
    reviewState.activeFilename = null
    reviewState.activeField = null
    reviewState.activeEntityIdx = 0
    reviewState.entities = []
  })

  it('compact + active field → send receives reviewContext at submit time', async () => {
    reviewState.activeFilename = '0017292f.pdf'
    reviewState.activeField = 'receipt_type'
    reviewState.activeEntityIdx = 0
    reviewState.entities = [{ receipt_type: '住宿发票' }]
    setupStores()
    render(<ChatPanel compact />)
    await typeAndSubmit('应该是 住宿账单')
    expect(mockSend).toHaveBeenCalledTimes(1)
    const args = mockSend.mock.calls[0]
    expect(args[0]).toBe('us-invoice')
    expect(args[1]).toBe('应该是 住宿账单')
    // 4th arg = reviewContext snapshot
    expect(args[3]).toEqual({
      filename: '0017292f.pdf',
      field: 'receipt_type',
      current_value: '住宿发票',
      entity_index: 0,
    })
  })

  it('compact + no active field → reviewContext carries filename only', async () => {
    reviewState.activeFilename = '0017292f.pdf'
    reviewState.activeField = null
    reviewState.activeEntityIdx = 0
    reviewState.entities = [{ receipt_type: '住宿发票' }]
    setupStores()
    render(<ChatPanel compact />)
    await typeAndSubmit('doc-level question')
    const args = mockSend.mock.calls[0]
    expect(args[3]).toEqual({
      filename: '0017292f.pdf',
      field: null,
      current_value: null,
      entity_index: 0,
    })
  })

  it('compact + no active filename → reviewContext is undefined', async () => {
    reviewState.activeFilename = null
    setupStores()
    render(<ChatPanel compact />)
    await typeAndSubmit('hello')
    const args = mockSend.mock.calls[0]
    expect(args[3]).toBeUndefined()
  })

  it('non-compact mode never sends reviewContext (chat-mode regression guard)', async () => {
    reviewState.activeFilename = '0017292f.pdf'
    reviewState.activeField = 'receipt_type'
    reviewState.activeEntityIdx = 0
    reviewState.entities = [{ receipt_type: '住宿发票' }]
    setupStores()
    render(<ChatPanel />)
    await typeAndSubmit('hello')
    const args = mockSend.mock.calls[0]
    expect(args[3]).toBeUndefined()
  })

  it('snapshot is taken BEFORE await — mutating the store mid-send does not leak into the in-flight call', async () => {
    reviewState.activeFilename = '0017292f.pdf'
    reviewState.activeField = 'receipt_type'
    reviewState.activeEntityIdx = 0
    reviewState.entities = [{ receipt_type: '住宿发票' }]
    setupStores()
    // Hold the send promise open so we can mutate the store between
    // submit-time and resolve-time.
    let resolveSend!: (v?: unknown) => void
    mockSend.mockImplementation(() => new Promise(r => { resolveSend = r as () => void }))
    render(<ChatPanel compact />)
    await typeAndSubmit('hello')
    // Snapshot already taken into the first call arg list.
    const argsBeforeMutate = mockSend.mock.calls[0][3]
    // Now mutate the store to simulate the user navigating to a different doc.
    reviewState.activeFilename = 'other.pdf'
    reviewState.activeField = 'other_field'
    reviewState.activeEntityIdx = 0
    reviewState.entities = [{ other_field: 'value' }]
    // Resolve and confirm the argument captured at submit time is unchanged.
    resolveSend()
    expect(argsBeforeMutate).toEqual({
      filename: '0017292f.pdf',
      field: 'receipt_type',
      current_value: '住宿发票',
      entity_index: 0,
    })
  })
})
