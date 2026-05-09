import { create } from 'zustand'

import { newChatId } from '../lib/ids'
import { streamSSE } from '../lib/sse'
import type { ChatEvent } from '../types/chat'
import { useApiKey } from './apiKey'

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
          handleToolResult(d, projectId, _findRecentVersionId())
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

function _findRecentVersionId(): string | null {
  const events = useChat.getState().events
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    if (e.type !== 'tool_call' || e.tool_name !== 'mcp__emerge_tools__freeze_version') continue
    if (typeof e.tool_result === 'string') {
      try {
        return (JSON.parse(e.tool_result) as { version_id?: string }).version_id ?? null
      } catch {
        return null
      }
    }
    if (e.tool_result && typeof e.tool_result === 'object') {
      return (e.tool_result as { version_id?: string }).version_id ?? null
    }
    break
  }
  return null
}

function handleToolResult(
  d: { tool_use_id: string; result_text: string; ok: boolean },
  projectId: string,
  versionId: string | null,
) {
  const events = useChat.getState().events
  const parent = events.find(e => e.type === 'tool_call' && e.tool_use_id === d.tool_use_id)
  let resultPayload: unknown = d.result_text

  if (parent?.type === 'tool_call' && parent.tool_name === 'mcp__emerge_tools__issue_api_key') {
    try {
      const parsed = JSON.parse(d.result_text) as {
        key_plaintext?: string
        key_hash?: string
        key_prefix?: string
        created_at?: string
        error?: { error_code: string; error_message_en: string }
      }
      if (parsed.error) {
        useChat.setState(s => ({
          events: [...s.events, {
            type: 'error',
            error_code: parsed.error!.error_code,
            error_message_en: parsed.error!.error_message_en,
          }],
        }))
        resultPayload = { redacted: true, error: parsed.error.error_code }
      } else if (parsed.key_plaintext && parsed.key_hash && parsed.key_prefix && parsed.created_at) {
        useApiKey.getState().setReveal({
          key_plaintext: parsed.key_plaintext,
          key_hash: parsed.key_hash,
          key_prefix: parsed.key_prefix,
          created_at: parsed.created_at,
          project_id: projectId,
          version_id: versionId,
        })
        resultPayload = {
          redacted: true,
          key_prefix: parsed.key_prefix,
          key_hash_short: parsed.key_hash.slice(-6),
          created_at: parsed.created_at,
        }
      }
    } catch {
      resultPayload = { redacted: true, error: 'parse_failed' }
    }
  }

  useChat.setState(s => ({
    events: s.events.map(e => {
      if (e.type === 'tool_call' && e.tool_use_id === d.tool_use_id) {
        return { ...e, tool_result: resultPayload, ok: d.ok }
      }
      return e
    }),
  }))
}

export const _testUtils = { handleToolResult }

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
