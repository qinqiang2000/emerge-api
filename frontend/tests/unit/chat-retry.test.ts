import { beforeEach, describe, expect, it } from 'vitest'

import { useChat } from '../../src/stores/chat'

describe('useChat retry', () => {
  beforeEach(() => {
    useChat.setState({ events: [], busy: false, chatId: 'c_test_chat_id' })
  })

  it('lastUserMessage returns null when no user events', () => {
    expect(useChat.getState().lastUserMessage()).toBeNull()
  })

  it('lastUserMessage returns the most recent user text', () => {
    useChat.setState({
      events: [
        { type: 'user', text: 'first' },
        { type: 'agent_text', text: 'reply' },
        { type: 'user', text: 'second' },
      ],
    })
    expect(useChat.getState().lastUserMessage()).toBe('second')
  })

  it('hasRecentToolError true when latest agent turn contains failed tool', () => {
    useChat.setState({
      events: [
        { type: 'user', text: 'q' },
        { type: 'tool_call', tool_use_id: 'x', tool_name: 'foo', tool_input: {}, tool_result: 'oops', ok: false },
      ],
    })
    expect(useChat.getState().hasRecentToolError()).toBe(true)
  })

  it('hasRecentToolError false when latest tool succeeded', () => {
    useChat.setState({
      events: [
        { type: 'user', text: 'q' },
        { type: 'tool_call', tool_use_id: 'x', tool_name: 'foo', tool_input: {}, tool_result: 'ok', ok: true },
      ],
    })
    expect(useChat.getState().hasRecentToolError()).toBe(false)
  })

  it('hasRecentToolError true when an error event is the most recent', () => {
    useChat.setState({
      events: [
        { type: 'user', text: 'q' },
        { type: 'error', error_code: 'x', error_message_en: 'y' },
      ],
    })
    expect(useChat.getState().hasRecentToolError()).toBe(true)
  })
})
