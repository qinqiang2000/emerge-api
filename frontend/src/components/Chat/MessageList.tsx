import type { ChatEvent } from '../../types/chat'

import ToolCallCard from './ToolCallCard'

interface Props { events: ChatEvent[] }

export default function MessageList({ events }: Props) {
  return (
    <div className="px-4 py-3 space-y-3 font-body">
      {events.map((e, i) => {
        if (e.type === 'user') {
          return <div key={i} className="text-fg-primary"><b>you:</b> {e.text}</div>
        }
        if (e.type === 'agent_text') {
          return <div key={i} className="text-fg-secondary"><b>agent:</b> {e.text}</div>
        }
        if (e.type === 'tool_call') {
          return <ToolCallCard key={i} event={e} />
        }
        if (e.type === 'error') {
          return (
            <div key={i} className="border-l-2 border-accent-danger px-3 py-2 bg-subtle text-sm">
              <span className="font-mono text-accent-danger">{e.error_code}</span>: {e.error_message_en}
            </div>
          )
        }
        return null
      })}
    </div>
  )
}
