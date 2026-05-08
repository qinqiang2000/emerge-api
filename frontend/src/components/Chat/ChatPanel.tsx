import { useState } from 'react'

import { useProjects } from '../../stores/projects'
import { useChat } from '../../stores/chat'

import Composer from './Composer'
import MessageList from './MessageList'

export default function ChatPanel() {
  const { selectedId } = useProjects()
  const { events, send, busy } = useChat()
  const [pending, setPending] = useState<{ filename: string }[]>([])

  return (
    <div className="flex flex-col h-full">
      <header className="border-b border-subtle px-4 py-3 font-heading text-sm uppercase tracking-wide text-fg-muted">
        Chat
      </header>
      <div className="flex-1 overflow-auto">
        <MessageList events={events} />
      </div>
      <Composer
        disabled={busy}
        pending={pending}
        onAttach={(files) => setPending(p => [...p, ...files])}
        onSubmit={async (text) => {
          await send(selectedId ?? 'p_unset', text, pending)
          setPending([])
        }}
      />
    </div>
  )
}
