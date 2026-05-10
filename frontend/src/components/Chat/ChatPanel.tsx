// frontend/src/components/Chat/ChatPanel.tsx
import { useState } from 'react'
import { RefreshCw } from 'lucide-react'

import { uploadDoc } from '../../lib/api'
import { useProjects } from '../../stores/projects'
import { useChat } from '../../stores/chat'
import Composer from './Composer'
import MessageList from './MessageList'

interface AttachInfo { filename: string; doc_id?: string; pending?: boolean }

export default function ChatPanel() {
  const { selectedId } = useProjects()
  const { events, send, busy } = useChat()
  const lastUserMsg = useChat(s => s.lastUserMessage())
  const hasErr = useChat(s => s.hasRecentToolError())
  const [pending, setPending] = useState<AttachInfo[]>([])

  async function attach(files: File[]) {
    if (!selectedId) {
      // Project not yet created: keep filenames pending; agent will create project then we upload.
      setPending(p => [...p, ...files.map(f => ({ filename: f.name, pending: true }))])
      return
    }
    setPending(p => [...p, ...files.map(f => ({ filename: f.name, pending: true }))])
    for (const f of files) {
      try {
        const { doc_id } = await uploadDoc(selectedId, f)
        setPending(p => p.map(x => x.filename === f.name ? { filename: f.name, doc_id, pending: false } : x))
      } catch {
        setPending(p => p.filter(x => x.filename !== f.name))
      }
    }
  }

  return (
    <div className="flex flex-col h-full">
      <header className="border-b border-subtle px-4 py-2 flex items-center gap-2">
        <span className="font-heading text-sm uppercase tracking-wide text-fg-muted">Chat</span>
        {hasErr && lastUserMsg && (
          <button
            type="button"
            onClick={() => { void send(selectedId ?? 'p_unset', lastUserMsg) }}
            className="ml-auto inline-flex items-center gap-1 px-2 py-1 text-xs font-mono text-accent-danger border border-accent-danger rounded hover:bg-subtle"
            aria-label="retry last user message"
          >
            <RefreshCw size={12} />
            重试上一条
          </button>
        )}
      </header>
      <div className="flex-1 overflow-auto">
        <MessageList events={events} busy={busy} />
      </div>
      <Composer
        disabled={busy}
        pending={pending.map(p => ({ filename: p.filename }))}
        onAttach={(files: File[]) => { void attach(files) }}
        onSubmit={async (text) => {
          await send(selectedId ?? 'p_unset', text, pending.map(p => ({ filename: p.filename, doc_id: p.doc_id })))
          setPending([])
        }}
      />
    </div>
  )
}
