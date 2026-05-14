/** Attachment carried on a user message. `doc_id` is required for render —
 *  thumbnails fetch `/lab/projects/{pid}/docs/{doc_id}/pages/1`. Pre-upload
 *  pending chips don't make it into chat events. */
export interface ChatAttachment {
  filename: string
  doc_id: string
}

export type ChatEvent =
  | { type: 'user'; text: string; attachments?: ChatAttachment[] }
  | { type: 'agent_text'; text: string }
  | { type: 'tool_call'; tool_use_id?: string; tool_name: string; tool_input: unknown; tool_result: unknown; ok: boolean }
  | { type: 'error'; error_code: string; error_message_en: string }
  | { type: 'turn_end' }

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

export type RenderItem =
  | { kind: 'user'; text: string; attachments?: ChatAttachment[] }
  | { kind: 'agent'; text: string }
  | { kind: 'tools'; calls: ToolCallEvent[] }
  | { kind: 'hoisted_tool'; call: ToolCallEvent }
  | { kind: 'error'; error_code: string; error_message_en: string }
