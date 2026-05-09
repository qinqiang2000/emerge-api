import type { ChatEvent } from '../../types/chat'

import JobProgressCard from './JobProgressCard'
import ToolCallCard from './ToolCallCard'

interface Props { events: ChatEvent[]; busy?: boolean }

export default function MessageList({ events, busy }: Props) {
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
          if (e.tool_name === 'mcp__emerge_tools__start_job' && typeof e.tool_result === 'string' && e.tool_result.startsWith('j_')) {
            return <JobProgressCard key={i} jobId={e.tool_result} />
          }
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
      {busy && (
        <div className="text-fg-muted italic flex items-center gap-2" aria-live="polite">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-fg-muted animate-pulse"></span>
          agent is thinking…
        </div>
      )}
    </div>
  )
}
