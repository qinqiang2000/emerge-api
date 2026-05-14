// frontend/src/components/Chat/ChatPanel.tsx
import { useEffect, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { stageUpload, uploadDoc } from '../../lib/api'
import { useProjects } from '../../stores/projects'
import { useChat } from '../../stores/chat'
import { useDocs } from '../../stores/docs'
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
 * - In an *empty-project* state (no `selectedId`) the file is uploaded
 *   immediately to `/lab/uploads/staging` (no pid required) → `stage_token`.
 *   We hang onto the original `File` handle so a failed upload can be
 *   retried without asking the user to re-drag the file.
 * - In a *selected-project* state the file is uploaded straight to
 *   `/lab/projects/{pid}/upload` and surfaces the post-dedupe `filename`.
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

export default function ChatPanel() {
  const { selectedId, projects } = useProjects()
  const events = useChat(s => s.events)
  const send = useChat(s => s.send)
  const busy = useChat(s => s.busy)
  const chatId = useChat(s => s.chatId)
  const chatsByProject = useChat(s => s.chatsByProject)
  const chats = selectedId ? (chatsByProject[selectedId] ?? []) : []

  // Reload-restore: when a real project becomes selected, bind to its persisted
  // chatId and hydrate the chat log. enterProject is a no-op for 'p_unset' and
  // when already on this project, so the create-project flow is safe.
  useEffect(() => {
    if (selectedId) useChat.getState().enterProject(selectedId)
    else useChat.getState().deselect()
  }, [selectedId])
  const docCount = useDocs(s => (s.byProject[selectedId ?? ''] ?? []).length)
  const fieldCount = useSchema(s => (s.byProject[selectedId ?? ''] ?? []).length)
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

  const projectName = projects.find(p => p.project_id === selectedId)?.name ?? ''

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

  async function _uploadOne(file: File, projectId: string): Promise<void> {
    try {
      // Filename is the only doc handle now — reconcile the chip name to the
      // server-returned (post-dedupe) filename in case `foo.pdf` already
      // existed and we got `foo (1).pdf` back.
      const { filename } = await uploadDoc(projectId, file)
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
    if (!selectedId) {
      // No project yet: stage each file under workspace/_staging/{token}/.
      // Chat turn will mint a project + claim the staged files when the
      // user submits, so we don't need a pid to start uploading.
      const initial = files.map<AttachInfo>(f => ({
        filename: f.name, originalName: f.name, file: f, status: 'staging',
      }))
      setPending(p => [...p, ...initial])
      await Promise.all(files.map(_stageOne))
      return
    }
    // Project selected: upload straight into its docs/.
    const initial = files.map<AttachInfo>(f => ({
      filename: f.name, originalName: f.name, file: f, status: 'uploading',
    }))
    setPending(p => [...p, ...initial])
    await Promise.all(files.map(f => _uploadOne(f, selectedId)))
  }

  async function retry(index: number) {
    const target = pending[index]
    if (!target || target.status !== 'failed') return
    if (selectedId) {
      setPending(p => p.map((x, i) => i === index ? { ...x, status: 'uploading', error: undefined } : x))
      await _uploadOne(target.file, selectedId)
    } else {
      setPending(p => p.map((x, i) => i === index ? { ...x, status: 'staging', error: undefined } : x))
      await _stageOne(target.file)
    }
  }

  async function handleStarter(text: string) {
    await send(selectedId ?? 'p_unset', text)
  }

  return (
    <>
      {selectedId && (
        <ConvHeader
          activeProject={projectName}
          currentChatId={chatId}
          chats={chats}
          onNew={() => useChat.getState().newChat(selectedId)}
          onSwitch={(cid) => useChat.getState().switchChat(selectedId, cid)}
          onOpen={() => { void useChat.getState().listChats(selectedId) }}
        />
      )}
      {improveJob && (
        <ImproveBanner job={improveJob} onOpen={handleBannerOpen} />
      )}
      {hasContent ? (
        <div className="conv-scroll" ref={convScrollRef}>
          <div className="conv-inner">
            <ChatErrorBoundary key={`${selectedId ?? 'p_unset'}:${chatId}`}>
              <MessageList events={events} busy={busy} />
            </ChatErrorBoundary>
          </div>
        </div>
      ) : (
        <EmptyHero
          projectName={projectName}
          onAttach={(files: File[]) => { void attach(files) }}
          onStarter={(text) => { void handleStarter(text) }}
        />
      )}
      <Composer
        disabled={busy}
        pending={pending.map(p => ({ filename: p.filename, status: p.status, error: p.error }))}
        projectId={selectedId ?? undefined}
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
              ...(p.stage_token ? { stage_token: p.stage_token } : {}),
            }))
          await send(selectedId ?? 'p_unset', text, ready)
          setPending([])
        }}
        onCancel={() => useChat.getState().cancel()}
      />
    </>
  )
}
