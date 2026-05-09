import { beforeEach, describe, expect, it } from 'vitest'

import { useApiKey } from '../../src/stores/apiKey'
import { useChat, _testUtils } from '../../src/stores/chat'


describe('chat store: issue_api_key reveal handling', () => {
  beforeEach(() => {
    useChat.setState({ events: [], busy: false, chatId: 'c_test_chat_id' })
    useApiKey.setState({ current: null })
  })

  it('parses issue_api_key tool result, sets reveal, redacts plaintext from events', () => {
    useChat.setState({
      events: [
        {
          type: 'tool_call',
          tool_use_id: 'tu_1',
          tool_name: 'mcp__emerge_tools__issue_api_key',
          tool_input: { project_id: 'p_abc123def456' },
          tool_result: undefined,
          ok: true,
        },
      ],
    })
    const result_text = JSON.stringify({
      key_plaintext: 'ek_abcdefgh01234567890123456789ABCD',
      key_hash: 'd'.repeat(64),
      key_prefix: 'ek_abcdefgh',
      created_at: '2026-05-09T01:23:45Z',
    })
    _testUtils.handleToolResult({ tool_use_id: 'tu_1', result_text, ok: true }, 'p_abc123def456', 'v1')

    const reveal = useApiKey.getState().current
    expect(reveal).not.toBeNull()
    expect(reveal!.key_plaintext).toBe('ek_abcdefgh01234567890123456789ABCD')
    expect(reveal!.project_id).toBe('p_abc123def456')
    expect(reveal!.version_id).toBe('v1')

    const ev = useChat.getState().events[0] as any
    expect(JSON.stringify(ev.tool_result)).not.toContain('ek_abcdefgh01234567890123456789ABCD')
    expect(JSON.stringify(ev.tool_result)).toContain('ek_abcdefgh')
  })
})
