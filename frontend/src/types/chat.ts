export type ChatEvent =
  | { type: 'user'; text: string }
  | { type: 'agent_text'; text: string }
  | { type: 'tool_call'; tool_name: string; tool_input: unknown; tool_result: unknown; ok: boolean }
  | { type: 'error'; error_code: string; error_message_en: string }
  | { type: 'turn_end' }
