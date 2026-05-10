import type { ChatEvent } from '../../types/chat'
import { groupChatEvents } from '../../lib/groupChatEvents'

import AgentMessage from './AgentMessage'
import ToolCallGroup from './ToolCallGroup'
import Turn from './Turn'

interface Props { events: ChatEvent[]; busy?: boolean }

export default function MessageList({ events, busy }: Props) {
  const items = groupChatEvents(events)
  return (
    <div data-testid="message-list">
      {items.map((item, i) => {
        if (item.kind === 'user') {
          return (
            <Turn key={i} who="you" ts="just now">
              <div className="msg user">{item.text}</div>
            </Turn>
          )
        }
        if (item.kind === 'agent') {
          return (
            <Turn key={i} who="agent" ts="just now">
              <AgentMessage text={item.text} />
            </Turn>
          )
        }
        if (item.kind === 'tools') {
          return (
            <div key={i} className="pl-2">
              <ToolCallGroup calls={item.calls} />
            </div>
          )
        }
        return (
          <div
            key={i}
            className="border-l-2 border-rose px-3 py-2 bg-paper-2 text-sm font-mono"
          >
            <span className="text-rose">{item.error_code}</span>
            <span className="text-ink-3">: {item.error_message_en}</span>
          </div>
        )
      })}
      {busy && (() => {
        const latest = [...events].reverse().find(e => e.type === 'tool_call') as
          | Extract<ChatEvent, { type: 'tool_call' }> | undefined
        const running = latest
          && (latest.tool_result === undefined || latest.tool_result === null)
          && latest.ok !== false
        const name = running ? latest.tool_name.replace(/^mcp__emerge_tools__/, '') : null
        return (
          <div className="text-ink-4 italic flex items-center gap-2 px-1 mt-4" aria-live="polite">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-ink-4 animate-pulse"></span>
            {name ? `calling ${name}...` : 'agent is thinking...'}
          </div>
        )
      })()}
    </div>
  )
}
