import { create } from 'zustand'

import { newChatId } from '../lib/ids'
import { streamSSE } from '../lib/sse'
import type { ChatEvent } from '../types/chat'

interface State {
  chatId: string
  events: ChatEvent[]
  busy: boolean
  send: (projectId: string, message: string, attachments?: { filename: string }[]) => Promise<void>
  reset: () => void
}

export const useChat = create<State>((set, get) => ({
  chatId: newChatId(),
  events: [],
  busy: false,
  reset: () => set({ chatId: newChatId(), events: [] }),
  send: async (projectId, message, attachments) => {
    set(s => ({ events: [...s.events, { type: 'user', text: message }], busy: true }))
    try {
      for await (const ev of streamSSE('/lab/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          chat_id: get().chatId,
          user_message: message,
          attachments,
        }),
      })) {
        if (ev.event === 'tool_result') {
          const d = ev.data as { tool_use_id: string; result_text: string; ok: boolean }
          set(s => ({
            events: s.events.map(e => {
              if (e.type === 'tool_call' && e.tool_use_id === d.tool_use_id) {
                return { ...e, tool_result: d.result_text, ok: d.ok }
              }
              return e
            }),
          }))
          continue
        }
        const mapped = mapSse(ev.event, ev.data)
        if (mapped === null) continue   // ignored event (user_acknowledged etc.)
        if (mapped.type === 'turn_end') break
        set(s => ({ events: [...s.events, mapped] }))
      }
    } finally {
      set({ busy: false })
    }
  },
}))

function mapSse(event: string, data: unknown): ChatEvent | null {
  if (event === 'agent_text') return { type: 'agent_text', text: (data as { text: string }).text }
  if (event === 'tool_call') {
    const d = data as { tool_use_id?: string; tool_name: string; tool_input: unknown; tool_result: unknown; ok?: boolean }
    return {
      type: 'tool_call',
      tool_use_id: d.tool_use_id,
      tool_name: d.tool_name,
      tool_input: d.tool_input,
      tool_result: d.tool_result,
      ok: d.ok ?? true,
    }
  }
  if (event === 'error') {
    const d = data as { error_code: string; error_message_en: string }
    return { type: 'error', error_code: d.error_code, error_message_en: d.error_message_en }
  }
  if (event === 'turn_end') return { type: 'turn_end' }
  // user_acknowledged / system / unknown — ignored. Returning null lets
  // future event types pass through silently rather than corrupt the chat.
  return null
}
