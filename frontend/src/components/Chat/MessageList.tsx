import type { ChatEvent } from '../../types/chat'

import JobProgressCard from './JobProgressCard'
import ToolCallCard from './ToolCallCard'
import KeyTrailCard from '../Publish/KeyTrailCard'
import AgentMessage from './AgentMessage'

interface Props { events: ChatEvent[]; busy?: boolean }

export default function MessageList({ events, busy }: Props) {
  return (
    <div className="px-4 py-3 space-y-3 font-body">
      {events.map((e, i) => {
        if (e.type === 'user') {
          return <div key={i} className="text-fg-primary"><b>you:</b> {e.text}</div>
        }
        if (e.type === 'agent_text') {
          return (
            <div key={i} className="text-fg-secondary">
              <AgentMessage text={e.text} />
            </div>
          )
        }
        if (e.type === 'tool_call') {
          if (e.tool_name === 'mcp__emerge_tools__issue_api_key') {
            return <KeyTrailCard key={i} event={e} />
          }
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
      {busy && (() => {
        const latest = [...events].reverse().find(e => e.type === 'tool_call') as
          | Extract<ChatEvent, { type: 'tool_call' }> | undefined
        const running = latest
          && (latest.tool_result === undefined || latest.tool_result === null)
          && latest.ok !== false
        const name = running ? latest.tool_name.replace(/^mcp__emerge_tools__/, '') : null
        return (
          <div className="text-fg-muted italic flex items-center gap-2" aria-live="polite">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-fg-muted animate-pulse"></span>
            {name ? `calling ${name}...` : 'agent is thinking...'}
          </div>
        )
      })()}
    </div>
  )
}
