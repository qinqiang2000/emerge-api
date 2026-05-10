import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChatEvent } from '../../src/types/chat'
import type { DocSummary } from '../../src/types/review'
import type { SchemaField } from '../../src/stores/schema'
import type { Project } from '../../src/lib/api'

// Mock all stores before importing the component
vi.mock('../../src/stores/projects', () => ({
  useProjects: vi.fn(),
}))
vi.mock('../../src/stores/chat', () => ({
  useChat: vi.fn(),
}))
vi.mock('../../src/stores/docs', () => ({
  useDocs: vi.fn(),
}))
vi.mock('../../src/stores/schema', () => ({
  useSchema: vi.fn(),
}))
vi.mock('../../src/lib/api', () => ({
  uploadDoc: vi.fn(),
}))

import { useProjects } from '../../src/stores/projects'
import { useChat } from '../../src/stores/chat'
import { useDocs } from '../../src/stores/docs'
import { useSchema } from '../../src/stores/schema'
import ChatPanel from '../../src/components/Chat/ChatPanel'

const mockSend = vi.fn()
const mockBusy = false

const EMPTY_DOC: DocSummary = {
  doc_id: 'd1',
  filename: 'a.pdf',
  ext: 'pdf',
  page_count: 1,
  uploaded_at: '2026-01-01T00:00:00Z',
  has_prediction: false,
  has_reviewed: false,
}

const EMPTY_FIELD: SchemaField = { name: 'vendor', type: 'string', description: 'Vendor name' }

function setupStores({
  events = [] as ChatEvent[],
  docs = [] as DocSummary[],
  fields = [] as SchemaField[],
  selectedId = null as string | null,
  projects = [] as Project[],
} = {}) {
  ;(useProjects as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => {
      const state = { selectedId, projects }
      return selector ? selector(state) : state
    },
  )
  ;(useChat as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => {
      const state = { events, send: mockSend, busy: mockBusy }
      return selector ? selector(state) : state
    },
  )
  ;(useDocs as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => {
      const state = { byProject: { [selectedId ?? '']: docs } }
      return selector ? selector(state) : docs
    },
  )
  ;(useSchema as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector?: (s: unknown) => unknown) => {
      const state = { byProject: { [selectedId ?? '']: fields } }
      return selector ? selector(state) : fields
    },
  )
}

describe('ChatPanel branching', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSend.mockResolvedValue(undefined)
  })

  it('shows EmptyHero when events, docs, and fields are all empty', () => {
    setupStores({ events: [], docs: [], fields: [] })
    render(<ChatPanel />)
    // EmptyHero eyebrow renders ~/projects/ (no project selected)
    expect(screen.getByText('~/projects/')).toBeInTheDocument()
  })

  it('shows EmptyHero with project name when project is selected but empty', () => {
    setupStores({
      events: [],
      docs: [],
      fields: [],
      selectedId: 'p_abc',
      projects: [{ project_id: 'p_abc', name: 'tax-forms', project_type: 'extraction', active_version_id: null }],
    })
    render(<ChatPanel />)
    expect(screen.getByText('~/projects/tax-forms/')).toBeInTheDocument()
  })

  it('shows MessageList (not EmptyHero) when events exist', () => {
    setupStores({
      events: [{ type: 'user', text: 'hello' }],
      docs: [],
      fields: [],
    })
    render(<ChatPanel />)
    // EmptyHero eyebrow would be present if it rendered; absence means MessageList shown
    expect(screen.queryByText('~/projects/')).not.toBeInTheDocument()
  })

  it('shows MessageList (not EmptyHero) when docs exist', () => {
    setupStores({
      events: [],
      docs: [EMPTY_DOC],
      fields: [],
      selectedId: 'p_abc',
      projects: [{ project_id: 'p_abc', name: 'tax-forms', project_type: 'extraction', active_version_id: null }],
    })
    render(<ChatPanel />)
    expect(screen.queryByText('~/projects/tax-forms/')).not.toBeInTheDocument()
  })

  it('shows MessageList (not EmptyHero) when schema fields exist', () => {
    setupStores({
      events: [],
      docs: [],
      fields: [EMPTY_FIELD],
      selectedId: 'p_abc',
      projects: [{ project_id: 'p_abc', name: 'tax-forms', project_type: 'extraction', active_version_id: null }],
    })
    render(<ChatPanel />)
    expect(screen.queryByText('~/projects/tax-forms/')).not.toBeInTheDocument()
  })
})
