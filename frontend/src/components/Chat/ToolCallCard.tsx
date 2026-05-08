import type { ChatEvent } from '../../types/chat'

interface Props { event: Extract<ChatEvent, { type: 'tool_call' }> }

export default function ToolCallCard({ event }: Props) {
  return <div className="text-xs font-mono text-fg-muted">[{event.tool_name}] (placeholder)</div>
}
