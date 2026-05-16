// tests/unit/Chat/ChatPanel-compact.test.tsx
//
// Compact-mode contract: ChatPanel must
//   1. hide ConvHeader (the history popover lives in the main shell only),
//   2. swap EmptyHero for a short single-line placeholder.
// Composer + ImproveBanner + MessageList behavior is unchanged.

import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChatEvent } from '../../../src/types/chat'
import type { DocSummary } from '../../../src/types/review'
import type { SchemaField } from '../../../src/stores/schema'
import type { Project } from '../../../src/lib/api'

// Same mock surface as the main ChatPanel.test — store interactions are not
// the subject under test here.
vi.mock('../../../src/stores/projects', () => ({ useProjects: vi.fn() }))
vi.mock('../../../src/stores/chat', () => ({ useChat: vi.fn() }))
vi.mock('../../../src/stores/docs', () => ({ useDocs: vi.fn() }))
vi.mock('../../../src/stores/schema', () => ({ useSchema: vi.fn() }))
vi.mock('../../../src/stores/jobs', () => ({ useJob: vi.fn() }))
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
import ChatPanel from '../../../src/components/Chat/ChatPanel'

const mockSend = vi.fn()
const mockEnterProject = vi.fn()

function setupStores({
  events = [] as ChatEvent[],
  docs = [] as DocSummary[],
  fields = [] as SchemaField[],
  selectedSlug = 'us-invoice' as string | null,
  projects = [{ project_id: 'p_a', slug: 'us-invoice', name: 'us-invoice', project_type: 'extraction', active_version_id: null }] as Project[],
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
    enterProject: mockEnterProject,
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
}

describe('ChatPanel compact mode', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSend.mockResolvedValue(undefined)
  })

  it('hides ConvHeader (chat history + new chat chips) when compact', () => {
    setupStores()
    render(<ChatPanel compact />)
    // ConvHeader exposes the history button via aria-label "Chat history".
    expect(screen.queryByLabelText('Chat history')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('New chat')).not.toBeInTheDocument()
  })

  it('renders ConvHeader normally when not compact', () => {
    setupStores()
    render(<ChatPanel />)
    expect(screen.getByLabelText('Chat history')).toBeInTheDocument()
    expect(screen.getByLabelText('New chat')).toBeInTheDocument()
  })

  it('replaces EmptyHero with the compact placeholder when empty + compact', () => {
    setupStores({ events: [], docs: [], fields: [] })
    render(<ChatPanel compact />)
    // EmptyHero's signature copy ("An empty folder…") should be absent.
    expect(screen.queryByText(/An empty folder/i)).not.toBeInTheDocument()
    // Single-line placeholder is present in its place.
    expect(screen.getByText(/start by asking about a field/i)).toBeInTheDocument()
  })

  it('does NOT render the compact placeholder when not compact (EmptyHero shows instead)', () => {
    setupStores({ events: [], docs: [], fields: [] })
    render(<ChatPanel />)
    expect(screen.queryByText(/start by asking about a field/i)).not.toBeInTheDocument()
    // EmptyHero's eyebrow copy.
    expect(screen.getByText('~/projects/us-invoice/')).toBeInTheDocument()
  })

  it('renders MessageList (not the placeholder) when events exist + compact', () => {
    setupStores({ events: [{ type: 'user', text: 'hi' }] })
    render(<ChatPanel compact />)
    expect(screen.queryByText(/start by asking about a field/i)).not.toBeInTheDocument()
  })
})
