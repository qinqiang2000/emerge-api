import type { ChatEvent } from '../../types/chat'
import { groupChatEvents } from '../../lib/groupChatEvents'

import AgentMessage from './AgentMessage'
import ToolCallGroup from './ToolCallGroup'
import UserBubble from './UserBubble'

interface Props { events: ChatEvent[]; busy?: boolean }

export default function MessageList({ events, busy }: Props) {
  const items = groupChatEvents(events)
  return (
    <div data-testid="message-list" className="px-4 py-3 space-y-4 font-body">
      {items.map((item, i) => {
        if (item.kind === 'user') {
          return <UserBubble key={i} text={item.text} />
        }
        if (item.kind === 'agent') {
          return (
            <div key={i} className="flex justify-start">
              <div className="max-w-[80%]">
                <AgentMessage text={item.text} />
              </div>
            </div>
          )
        }
        if (item.kind === 'tools') {
          return (
            <div key={i} className="flex justify-start">
              <div className="max-w-[80%] w-full">
                <ToolCallGroup calls={item.calls} />
              </div>
            </div>
          )
        }
        return (
          <div
            key={i}
            className="border-l-2 border-accent-danger px-3 py-2 bg-subtle text-sm font-mono"
          >
            <span className="text-accent-danger">{item.error_code}</span>
            <span className="text-fg-secondary">: {item.error_message_en}</span>
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
          <div className="text-fg-muted italic flex items-center gap-2 px-1" aria-live="polite">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-fg-muted animate-pulse"></span>
            {name ? `calling ${name}...` : 'agent is thinking...'}
          </div>
        )
      })()}
    </div>
  )
}
