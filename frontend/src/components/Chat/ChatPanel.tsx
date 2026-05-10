// frontend/src/components/Chat/ChatPanel.tsx
import { useState } from 'react'

import { uploadDoc } from '../../lib/api'
import { useProjects } from '../../stores/projects'
import { useChat } from '../../stores/chat'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'
import Composer from './Composer'
import MessageList from './MessageList'
import EmptyHero from '../Empty/EmptyHero'

interface AttachInfo { filename: string; doc_id?: string; pending?: boolean }

export default function ChatPanel() {
  const { selectedId, projects } = useProjects()
  const events = useChat(s => s.events)
  const { send, busy } = useChat()
  const docs = useDocs(s => s.byProject[selectedId ?? ''] ?? [])
  const fields = useSchema(s => s.byProject[selectedId ?? ''] ?? [])
  const [pending, setPending] = useState<AttachInfo[]>([])

  const hasContent = events.length > 0 || docs.length > 0 || fields.length > 0

  const projectName = projects.find(p => p.project_id === selectedId)?.name ?? ''

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

  async function handleStarter(text: string) {
    await send(selectedId ?? 'p_unset', text)
  }

  return (
    <>
      {hasContent ? (
        <div className="conv-scroll">
          <div className="conv-inner">
            <MessageList events={events} busy={busy} />
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
        onAttach={(files: File[]) => { void attach(files) }}
        onSubmit={async (text) => {
          await send(selectedId ?? 'p_unset', text, pending.map(p => ({ filename: p.filename, doc_id: p.doc_id })))
          setPending([])
        }}
      />
    </>
  )
}
