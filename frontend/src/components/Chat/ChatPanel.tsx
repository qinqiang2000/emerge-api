// frontend/src/components/Chat/ChatPanel.tsx
import { useEffect, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { uploadDoc } from '../../lib/api'
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

interface AttachInfo {
  /** Display + key for the chip. Starts as `file.name`; after upload resolves,
   *  reconciled to the dedupe filename returned by the server (e.g. the
   *  second `foo.pdf` becomes `foo (1).pdf`). */
  filename: string
  /** The name the chip started with — kept so we can match the chip back to
   *  its in-flight upload when the server-side filename differs after dedupe. */
  originalName: string
  pending?: boolean
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

  async function attach(files: File[]) {
    if (!selectedId) {
      // Project not yet created: keep filenames pending; agent will create project then we upload.
      setPending(p => [...p, ...files.map(f => ({ filename: f.name, originalName: f.name, pending: true }))])
      return
    }
    setPending(p => [...p, ...files.map(f => ({ filename: f.name, originalName: f.name, pending: true }))])
    for (const f of files) {
      try {
        const { filename } = await uploadDoc(selectedId, f)
        // Reconcile the chip to the server-returned name — may differ from
        // `f.name` after dedupe (e.g. "foo.pdf" → "foo (1).pdf"). Match by
        // originalName so concurrent uploads of the same name don't collide.
        setPending(p => {
          let consumed = false
          return p.map(x => {
            if (!consumed && x.originalName === f.name && x.pending) {
              consumed = true
              return { filename, originalName: f.name, pending: false }
            }
            return x
          })
        })
      } catch {
        // Drop the first matching pending chip on failure (best-effort; rare).
        setPending(p => {
          let dropped = false
          return p.filter(x => {
            if (!dropped && x.originalName === f.name && x.pending) {
              dropped = true
              return false
            }
            return true
          })
        })
      }
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
        pending={pending.map(p => ({ filename: p.filename }))}
        projectId={selectedId ?? undefined}
        onAttach={(files: File[]) => { void attach(files) }}
        onRemove={(i) => setPending(p => p.filter((_, idx) => idx !== i))}
        onSubmit={async (text) => {
          // Only send chips that finished uploading (pending=false → filename
          // is the dedupe-resolved on-disk name). The store also re-filters,
          // but this keeps the wire format clean.
          const ready = pending.filter(p => !p.pending).map(p => ({ filename: p.filename }))
          await send(selectedId ?? 'p_unset', text, ready)
          setPending([])
        }}
        onCancel={() => useChat.getState().cancel()}
      />
    </>
  )
}
