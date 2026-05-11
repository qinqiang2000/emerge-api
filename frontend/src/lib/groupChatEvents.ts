import type { ChatEvent, RenderItem } from '../types/chat'

// Tools that render as standalone "rich cards" (EvalCard, PublishStage, JobProgressCard).
// They stay outside the ToolStack collapse so their primary artifact (score
// numbers, readiness checklist, one-time key reveal, job progress) is always
// immediately visible. Plumbing tools (read_documents, derive_schema, …)
// collapse into the ToolStack. See docs/design-decisions.md 2026-05-11.
const HOISTED_TOOL_NAMES = new Set([
  'mcp__emerge_tools__start_job',
  'mcp__emerge_tools__readiness_check',
  'mcp__emerge_tools__issue_api_key',
  'mcp__emerge_tools__score',
])

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
      if (HOISTED_TOOL_NAMES.has(e.tool_name)) {
        flushTools()
        out.push({ kind: 'hoisted_tool', call: e })
      } else {
        toolBuf.push(e)
      }
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
