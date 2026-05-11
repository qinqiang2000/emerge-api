export type ChatEvent =
  | { type: 'user'; text: string }
  | { type: 'agent_text'; text: string }
  | { type: 'tool_call'; tool_use_id?: string; tool_name: string; tool_input: unknown; tool_result: unknown; ok: boolean }
  | { type: 'error'; error_code: string; error_message_en: string }
  | { type: 'turn_end' }

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

export type RenderItem =
  | { kind: 'user'; text: string }
  | { kind: 'agent'; text: string }
  | { kind: 'tools'; calls: ToolCallEvent[] }
  | { kind: 'hoisted_tool'; call: ToolCallEvent }
  | { kind: 'error'; error_code: string; error_message_en: string }
