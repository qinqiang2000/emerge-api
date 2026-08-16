import type { ChatEvent, RenderItem } from '../types/chat'
import { canonicalToolName, scoreKindOf } from './legacyToolName'

// Tools that render as standalone "rich cards" (EvalCard, PublishStage, JobProgressCard).
// They stay outside the ToolStack collapse so their primary artifact (score
// numbers, readiness checklist, one-time key reveal, job progress) is always
// immediately visible. Plumbing tools (read_documents, derive_schema, …)
// collapse into the ToolStack. See docs/design-decisions.md 2026-05-11.
// Bare (post-canonicalToolName) names — compared via canonicalToolName below
// so both current and legacy (pre-P4-merge) recorded tool_names hoist alike.
const HOISTED_TOOL_NAMES = new Set([
  'start_job', 'readiness_check', 'issue_api_key', 'score',
  // Phase B: save_reviewed is hoisted so its SaveReviewedAdapter (the
  // "升级到 description / global_notes / 忽略" chip row) renders inline
  // beneath the tool card after a review-mode feedback turn.
  'save_reviewed',
  // A3: audit results render as rich cards (AuditCard) — the per-rule
  // checklist / score strip is the user's primary artifact. `run_audit` is
  // its own tool (unaffected by Task 7); `score`'s kind='audit' calls are
  // handled below by name alone (canonicalToolName already maps the legacy
  // `score_audit` transcripts onto `score`, so one entry suffices).
  'run_audit',
  // 审单核对白板: render_review_board hoists so its ReviewBoardCard (doc list +
  // "打开白板 ↗") renders inline instead of collapsing into the tool stack.
  'render_review_board',
])

// `score` folds score_audit/score_match (P4 Task 7): kind='extract'/'audit'
// hoist same as before (they were their own hoisted tools pre-merge);
// kind='match' must NOT hoist — score_match was never in HOISTED_TOOL_NAMES,
// it always fell through to the collapsed ToolStack, and the merge must not
// silently change that. scoreKindOf is the single place both this grouping
// decision and MessageList's card dispatch read the kind from, so the two
// cannot drift apart from each other.
function isHoisted(e: Extract<ChatEvent, { type: 'tool_call' }>): boolean {
  const kind = scoreKindOf(e.tool_name, e.tool_input)
  if (kind !== null) return kind !== 'match'
  return HOISTED_TOOL_NAMES.has(canonicalToolName(e.tool_name))
}

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
      if (isHoisted(e)) {
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
    } else if (e.type === 'turn_truncated') {
      // Follows the agent's own handover text. Renders as a quiet notice, not
      // an error — the turn produced real work and the session resumes.
      out.push({ kind: 'truncated', num_turns: e.num_turns })
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
