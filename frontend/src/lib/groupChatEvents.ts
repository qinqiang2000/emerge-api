import type { ChatEvent, RenderItem } from '../types/chat'

export function groupChatEvents(events: ChatEvent[]): RenderItem[] {
  const out: RenderItem[] = []
  let toolBuf: Extract<ChatEvent, { type: 'tool_call' }>[] = []

  const flushTools = () => {
    if (toolBuf.length > 0) {
      out.push({ kind: 'tools', calls: toolBuf })
      toolBuf = []
    }
  }

  for (const e of events) {
    if (e.type === 'tool_call') {
      toolBuf.push(e)
      continue
    }
    flushTools()
    if (e.type === 'user') {
      const prev = out[out.length - 1]
      if (prev && prev.kind === 'user') {
        // merge consecutive user messages
        prev.text = prev.text + '\n\n' + e.text
      } else {
        out.push({ kind: 'user', text: e.text })
      }
    } else if (e.type === 'agent_text') {
      const prev = out[out.length - 1]
      if (prev && prev.kind === 'agent') {
        // merge consecutive agent text chunks
        prev.text = prev.text + e.text
      } else {
        out.push({ kind: 'agent', text: e.text })
      }
    } else if (e.type === 'error') {
      out.push({
        kind: 'error',
        error_code: e.error_code,
        error_message_en: e.error_message_en,
      })
    }
  }
  flushTools()
  return out
}
