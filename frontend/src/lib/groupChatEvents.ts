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
  // A3: audit results render as rich cards (AuditCard) — the per-rule
  // checklist / score strip is the user's primary artifact.
  'mcp__emerge_tools__run_audit',
  'mcp__emerge_tools__score_audit',
])

export function groupChatEvents(events: ChatEvent[]): RenderItem[] {
  const out: RenderItem[] = []
  let toolBuf: Extract<ChatEvent, { type: 'tool_call' }>[] = []

  const flushTools = () => {
    if (toolBuf.length > 0) {
      out.push({ kind: 'tools', calls: toolBuf, parent_tool_use_id: toolBufParent })
      toolBuf = []
      toolBufParent = undefined
    }
  }

  // Track the current toolBuf's parent so subagent-emitted tool calls don't
  // accidentally merge into a sibling top-level tool stack.
  let toolBufParent: string | undefined
  for (const e of events) {
    if (e.type === 'tool_call') {
      if (HOISTED_TOOL_NAMES.has(e.tool_name)) {
        flushTools()
        out.push({ kind: 'hoisted_tool', call: e })
      } else {
        if (toolBuf.length > 0 && toolBufParent !== e.parent_tool_use_id) {
          flushTools()
        }
        if (toolBuf.length === 0) toolBufParent = e.parent_tool_use_id
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
      if (prev && prev.kind === 'agent' && prev.parent_tool_use_id === e.parent_tool_use_id) {
        // merge consecutive agent text chunks only when they belong to the
        // same agent (top-level vs same subagent).
        prev.text = prev.text + e.text
      } else {
        out.push({ kind: 'agent', text: e.text, parent_tool_use_id: e.parent_tool_use_id })
      }
    } else if (e.type === 'error') {
      out.push({
        kind: 'error',
        error_code: e.error_code,
        error_message_en: e.error_message_en,
      })
    } else if (e.type === 'permission_request') {
      // Permission prompts render as their own item (own line in the conv).
      // They never collapse into a tool stack — the user needs the UI to
      // make a decision before the agent can proceed. Resolved cards stay
      // visible as a trail so chat history reads naturally.
      out.push({ kind: 'permission', event: e })
    } else if (e.type === 'ask_user_request') {
      // Structured agent question (ask_user MCP tool). Same standalone-line
      // treatment as permission_request — the agent is paused awaiting a
      // user pick; resolved cards stay as a "you answered X" trail.
      out.push({ kind: 'ask_user', event: e })
    }
  }
  flushTools()
  return out
}
