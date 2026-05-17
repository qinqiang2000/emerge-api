/** Attachment carried on a user message. `filename` is the only doc handle.
 *  `source` distinguishes conversational scratch (`"chat"` — default for
 *  paste/drop, lives in `chats/<chat_id>/attachments/`) from docs-promoted
 *  refs (`"docs"` — lives in `docs/`, powers eval/predictions/review).
 *  Renderers dispatch thumbnail / link URLs on `source`. */
export interface ChatAttachment {
  filename: string
  source?: 'chat' | 'docs'
}

/** SDK `can_use_tool` ask-user round-trip. Backend emits one of these as an
 *  SSE `permission_request` event whenever the workspace safety gate
 *  classifies a tool call as `ask` (network ops, out-of-workspace paths,
 *  unrecognised tool names, etc.). The chat turn is *paused* awaiting the
 *  user's decision; UI must surface an approve/deny card. The `resolution`
 *  field is filled in locally once the user clicks — kept on the event so a
 *  re-render of historical chat shows "approved" / "denied" trail rather
 *  than a live card. Pending-only: nothing about this is persisted to the
 *  server-side JSONL; reload drops it. */
export interface PermissionRequestEvent {
  type: 'permission_request'
  request_id: string
  tool_name: string
  tool_input: unknown
  reason: string
  suggested_scope: 'once' | 'always'
  /** undefined → still awaiting user; otherwise the user's reply. */
  resolution?: {
    decision: 'approve' | 'deny'
    scope: 'once' | 'always'
  }
}

export type ChatEvent =
  | { type: 'user'; text: string; attachments?: ChatAttachment[] }
  | { type: 'agent_text'; text: string }
  | { type: 'tool_call'; tool_use_id?: string; tool_name: string; tool_input: unknown; tool_result: unknown; ok: boolean }
  | { type: 'error'; error_code: string; error_message_en: string }
  | { type: 'turn_end' }
  | PermissionRequestEvent

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

export type RenderItem =
  | { kind: 'user'; text: string; attachments?: ChatAttachment[] }
  | { kind: 'agent'; text: string }
  | { kind: 'tools'; calls: ToolCallEvent[] }
  | { kind: 'hoisted_tool'; call: ToolCallEvent }
  | { kind: 'error'; error_code: string; error_message_en: string }
  | { kind: 'permission'; event: PermissionRequestEvent }

// ── Task / TodoWrite checklist ────────────────────────────────────────────
// SDK built-in task tools (`TodoWrite` — single-tool input `{todos: [...]}`,
// or the older `TaskCreate` / `TaskUpdate` / `TaskList` triple) surface as
// normal `tool_call` events. We DON'T add a new ChatEvent type — instead, the
// TaskChecklist component reads `events` and derives the live list from the
// most recent matching tool_call, so it auto-resets on chat switch (events
// resets) and doesn't need lifecycle plumbing. Persistence is intentionally
// not done — reload drops the panel.
export type TaskStatus = 'pending' | 'in_progress' | 'completed'

export interface TaskEntry {
  id?: string
  content: string
  status: TaskStatus
  /** Some TodoWrite variants carry an `activeForm` companion to `content`.
   *  Surfaced when present so the panel can show the imperative form on the
   *  in-progress item, matching Claude Code's rendering. */
  activeForm?: string
}
