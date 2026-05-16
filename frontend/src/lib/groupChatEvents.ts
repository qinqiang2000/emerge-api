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
  // Phase B: save_reviewed is hoisted so its SaveReviewedAdapter (the
  // "升级到 description / global_notes / 忽略" chip row) renders inline
  // beneath the tool card after a review-mode feedback turn.
  'mcp__emerge_tools__save_reviewed',
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
      // Each user event = one bubble. Consecutive user messages (e.g. after
      // interrupting the agent multiple times in a row) must stay separate so
      // retry/edit only operates on the most recent one.
      out.push({ kind: 'user', text: e.text, attachments: e.attachments })
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
