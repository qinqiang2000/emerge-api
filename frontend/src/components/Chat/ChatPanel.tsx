// frontend/src/components/Chat/ChatPanel.tsx
import { useEffect, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { attachToChat, stageUpload } from '../../lib/api'
import { useProjects } from '../../stores/projects'
import { useChat, type SurfaceContext } from '../../stores/chat'
import { useDocs } from '../../stores/docs'
import { useReview } from '../../stores/review'
import { useSchema } from '../../stores/schema'
import { useJob } from '../../stores/jobs'
import Composer from './Composer'
import ConvHeader from './ConvHeader'
import ChatErrorBoundary from './ChatErrorBoundary'
import MessageList from './MessageList'
import EmptyHero from '../Empty/EmptyHero'
import ImproveBanner from '../Improve/ImproveBanner'

/**
 * One pending attachment as the user sees it before the chat turn fires.
 *
 * - In an *empty-project* state (no `selectedSlug`) the file is uploaded
 *   immediately to `/lab/uploads/staging` (no pid required) → `stage_token`.
 *   We hang onto the original `File` handle so a failed upload can be
 *   retried without asking the user to re-drag the file.
 * - In a *selected-project* state the file is uploaded straight to
 *   `/lab/projects/{slug}/chats/{chatId}/attach` (chat-scoped scratch — NOT
 *   `docs/`) and surfaces the post-dedupe `filename`. Promotion into `docs/`
 *   is a separate user-acked agent call (`promote_attachment_to_docs`).
 *
 * `originalName` is what the chip started with — kept so we can match a
 * chip back to its in-flight upload when the server-side filename differs
 * after dedupe (concurrent uploads of the same `foo.pdf` → `foo (1).pdf`).
 *
 * Filename is the only doc handle now; there is no `doc_id`.
 */
interface AttachInfo {
  /** Display + key for the chip. Starts as `file.name`; after upload
   *  resolves, reconciled to the dedupe filename returned by the server. */
  filename: string
  originalName: string
  file: File
  status: 'staging' | 'staged' | 'uploading' | 'uploaded' | 'failed'
  stage_token?: string
  error?: string
}

interface ChatPanelProps {
  /** Compact mode — used by ReviewChatColumn so the chat fits into a narrow
   *  third column. Hides ConvHeader (history popover is reachable from the main
   *  shell when you exit review) and swaps EmptyHero for a one-line placeholder
   *  since the hero's hero-text wouldn't survive a 360px-wide column. */
  compact?: boolean
}

export default function ChatPanel({ compact = false }: ChatPanelProps = {}) {
  const { selectedSlug, projects } = useProjects()
  const events = useChat(s => s.events)
  const send = useChat(s => s.send)
  const busy = useChat(s => s.busy)
  const chatId = useChat(s => s.chatId)
  const chatsByProject = useChat(s => s.chatsByProject)
  const chats = selectedSlug ? (chatsByProject[selectedSlug] ?? []) : []
  // Composer carve-out: a pending ask_user card means the agent is awaiting
  // structured input, but the user must still be able to redirect via free
  // text. The store's send() detects the pending card and converts the new
  // message into an implicit cancel of the question before opening the next
  // turn. Permission cards keep the strict block — there's no "type your own
  // permission" semantic.
  const pendingAskUser = events.some(
    e => e.type === 'ask_user_request' && !e.resolution,
  )

  // Reload-restore: when a real project becomes selected, bind to its persisted
  // chatId and hydrate the chat log. enterProject is a no-op for 'p_unset' and
  // when already on this project, so the create-project flow is safe.
  useEffect(() => {
    if (selectedSlug) useChat.getState().enterProject(selectedSlug)
    else useChat.getState().deselect()
  }, [selectedSlug])
  const docCount = useDocs(s => (s.byProject[selectedSlug ?? ''] ?? []).length)
  const fieldCount = useSchema(s => (s.byProject[selectedSlug ?? ''] ?? []).length)
  const [pending, setPending] = useState<AttachInfo[]>([])
  const convScrollRef = useRef<HTMLDivElement>(null)

  // Find any running improve job to show the banner.
  const byId = useJob(useShallow(s => s.byId))
  const runningImproveEntry = Object.entries(byId)
    .filter(([, slice]) => slice.status === 'running')
    .sort(([a], [b]) => (a > b ? -1 : a < b ? 1 : 0))[0] ?? null
  const improveJob = runningImproveEntry ? runningImproveEntry[1] : null

  function handleBannerOpen() {
    // Scroll to the most recent proposal card via data-attribute, or fall back to bottom.
    const jobId = improveJob?.jobId
    const card = jobId
      ? document.querySelector(`[data-improve-card="${jobId}"]`)
      : null
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' })
    } else {
      const el = convScrollRef.current
      if (el) el.scrollTop = el.scrollHeight
    }
  }

  const hasContent = events.length > 0 || docCount > 0 || fieldCount > 0

  const projectName = projects.find(p => p.slug === selectedSlug)?.name ?? ''

  /** Resolve a unique pending entry by filename + File identity (since two
   *  drops can share a name and we keep both rows visible). The File object
   *  identity uniquely identifies the drop. */
  function _matchPending(p: AttachInfo, filename: string, file: File): boolean {
    return p.filename === filename && p.file === file
  }

  async function _stageOne(file: File): Promise<void> {
    try {
      const info = await stageUpload(file)
      setPending(p => p.map(x => _matchPending(x, file.name, file)
        ? { ...x, status: 'staged', stage_token: info.stage_token, error: undefined }
        : x))
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setPending(p => p.map(x => _matchPending(x, file.name, file)
        ? { ...x, status: 'failed', error: msg }
        : x))
    }
  }

  async function _uploadOne(file: File, slug: string, cid: string): Promise<void> {
    try {
      const { filename } = await attachToChat(slug, cid, file)
      setPending(p => p.map(x => _matchPending(x, file.name, file)
        ? { ...x, status: 'uploaded', filename, error: undefined }
        : x))
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setPending(p => p.map(x => _matchPending(x, file.name, file)
        ? { ...x, status: 'failed', error: msg }
        : x))
    }
  }

  async function attach(files: File[]) {
    if (files.length === 0) return
    if (!selectedSlug) {
      // No project yet: stage each file under workspace/_staging/{token}/.
      // Chat turn will mint a project + claim the staged files into
      // chats/<chat_id>/attachments/ when the user submits.
      const initial = files.map<AttachInfo>(f => ({
        filename: f.name, originalName: f.name, file: f, status: 'staging',
      }))
      setPending(p => [...p, ...initial])
      await Promise.all(files.map(_stageOne))
      return
    }
    // Project selected: write to the current chat's attachments dir (NOT
    // docs/). Promotion to docs/ requires explicit user ack via the agent
    // tool `promote_attachment_to_docs`.
    const initial = files.map<AttachInfo>(f => ({
      filename: f.name, originalName: f.name, file: f, status: 'uploading',
    }))
    setPending(p => [...p, ...initial])
    await Promise.all(files.map(f => _uploadOne(f, selectedSlug, chatId)))
  }

  async function retry(index: number) {
    const target = pending[index]
    if (!target || target.status !== 'failed') return
    if (selectedSlug) {
      setPending(p => p.map((x, i) => i === index ? { ...x, status: 'uploading', error: undefined } : x))
      await _uploadOne(target.file, selectedSlug, chatId)
    } else {
      setPending(p => p.map((x, i) => i === index ? { ...x, status: 'staging', error: undefined } : x))
      await _stageOne(target.file)
    }
  }

  async function handleStarter(text: string) {
    await send(selectedSlug ?? 'p_unset', text)
  }

  return (
    <>
      {!compact && selectedSlug && (
        <ConvHeader
          activeProject={projectName}
          currentChatId={chatId}
          chats={chats}
          onNew={() => useChat.getState().newChat(selectedSlug)}
          onSwitch={(cid) => useChat.getState().switchChat(selectedSlug, cid)}
          onOpen={() => { void useChat.getState().listChats(selectedSlug) }}
        />
      )}
      {improveJob && (
        <ImproveBanner job={improveJob} onOpen={handleBannerOpen} />
      )}
      {hasContent ? (
        <div className="conv-scroll" ref={convScrollRef}>
          <div className="conv-inner">
            <ChatErrorBoundary key={`${selectedSlug ?? 'p_unset'}:${chatId}`}>
              <MessageList events={events} busy={busy} />
            </ChatErrorBoundary>
          </div>
        </div>
      ) : compact ? (
        <div className="chat-compact-empty" role="status">
          <span>start by asking about a field…</span>
        </div>
      ) : (
        <EmptyHero
          projectName={projectName}
          onAttach={(files: File[]) => { void attach(files) }}
          onStarter={(text) => { void handleStarter(text) }}
        />
      )}
      <Composer
        disabled={busy && !pendingAskUser}
        pending={pending.map(p => ({ filename: p.filename, status: p.status, error: p.error }))}
        focusOnMount={!compact}
        projectId={selectedSlug ?? undefined}
        onAttach={(files: File[]) => { void attach(files) }}
        onRemove={(i) => setPending(p => p.filter((_, idx) => idx !== i))}
        onRetry={(i) => { void retry(i) }}
        onSubmit={async (text) => {
          // Only carry attachments that landed somewhere the backend can act on.
          // Failed/in-flight chips are filtered — the chip stays visible so the
          // user knows it didn't go, but the chat turn doesn't reference it.
          // Filename is the only doc handle; stage_token is the timing-shift
          // bridge for pre-pid drops (chat_turn claims + rewrites to filename
          // on the backend before persisting the user event).
          const ready = pending
            .filter(p => p.status === 'uploaded' || p.status === 'staged')
            .map(p => ({
              filename: p.filename,
              source: 'chat' as const,
              ...(p.stage_token ? { stage_token: p.stage_token } : {}),
            }))
          // In compact mode we are rendered inside the review overlay's chat
          // column — snapshot the active surface state BEFORE awaiting send
          // so the agent's tool calls bind to what the user was looking at
          // when they hit Enter, not to whatever they navigate to mid-
          // response. Reading via `useReview.getState()` here (rather than
          // hook-derived values) is intentional — the hook would have
          // closed over render-time state.
          let surfaceContext: SurfaceContext | undefined
          if (compact) {
            const rev = useReview.getState()
            if (rev.activeFilename) {
              const idx = rev.activeEntityIdx ?? 0
              const entity = rev.entities[idx] ?? {}
              const currentValue = rev.activeField
                ? (entity as Record<string, unknown>)[rev.activeField] ?? null
                : null
              const tabKey = rev.activeTabKey
              surfaceContext = {
                surface: 'review',
                filename: rev.activeFilename,
                field: rev.activeField ?? null,
                current_value: currentValue,
                entity_index: idx,
                page: rev.page,
                page_count: rev.pageCount,
                entity_count: rev.entities.length,
                active_tab_key: tabKey,
                experiment_id: tabKey && tabKey !== 'active' ? tabKey : null,
              }
            }
          }
          await send(selectedSlug ?? 'p_unset', text, ready, surfaceContext)
          setPending([])
        }}
        onCancel={() => useChat.getState().cancel()}
      />
    </>
  )
}
