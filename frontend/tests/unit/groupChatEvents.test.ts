import { describe, expect, it } from 'vitest'

import { groupChatEvents } from '../../src/lib/groupChatEvents'
import type { ChatEvent } from '../../src/types/chat'

function tc(name: string, ok = true, id = `tu_${name}`): Extract<ChatEvent, { type: 'tool_call' }> {
  return { type: 'tool_call', tool_use_id: id, tool_name: name, tool_input: {}, tool_result: 'ok', ok }
}

describe('groupChatEvents', () => {
  it('empty input -> empty output', () => {
    expect(groupChatEvents([])).toEqual([])
  })

  it('user / agent_text are 1:1', () => {
    const events: ChatEvent[] = [
      { type: 'user', text: 'hi' },
      { type: 'agent_text', text: 'hello' },
    ]
    const items = groupChatEvents(events)
    expect(items).toHaveLength(2)
    expect(items[0]).toEqual({ kind: 'user', text: 'hi' })
    expect(items[1]).toEqual({ kind: 'agent', text: 'hello' })
  })

  it('consecutive tool_calls collapse into one tools group', () => {
    const events: ChatEvent[] = [
      { type: 'agent_text', text: 'starting' },
      tc('a'),
      tc('b'),
      tc('c'),
      { type: 'agent_text', text: 'done' },
    ]
    const items = groupChatEvents(events)
    expect(items).toHaveLength(3)
    expect(items[0]).toEqual({ kind: 'agent', text: 'starting' })
    expect(items[1].kind).toBe('tools')
    if (items[1].kind === 'tools') {
      expect(items[1].calls.map(e => e.tool_name)).toEqual(['a', 'b', 'c'])
    }
    expect(items[2]).toEqual({ kind: 'agent', text: 'done' })
  })

  it('non-consecutive tool_calls remain in separate groups', () => {
    const events: ChatEvent[] = [
      tc('a'),
      { type: 'agent_text', text: 'x' },
      tc('b'),
    ]
    const items = groupChatEvents(events)
    expect(items).toHaveLength(3)
    expect(items[0].kind).toBe('tools')
    expect(items[1].kind).toBe('agent')
    expect(items[2].kind).toBe('tools')
  })

  it('turn_end is dropped', () => {
    const events: ChatEvent[] = [
      { type: 'user', text: 'hi' },
      { type: 'turn_end' },
      { type: 'agent_text', text: 'ok' },
    ]
    const items = groupChatEvents(events)
    expect(items).toHaveLength(2)
    expect(items[0].kind).toBe('user')
    expect(items[1].kind).toBe('agent')
  })

  it('error becomes its own item', () => {
    const events: ChatEvent[] = [
      { type: 'agent_text', text: 'try' },
      { type: 'error', error_code: 'bad', error_message_en: 'broken' },
    ]
    const items = groupChatEvents(events)
    expect(items).toHaveLength(2)
    expect(items[1]).toEqual({ kind: 'error', error_code: 'bad', error_message_en: 'broken' })
  })

  it('a tools group between two user msgs flushes correctly', () => {
    const events: ChatEvent[] = [
      { type: 'user', text: 'q1' },
      tc('a'),
      tc('b'),
      { type: 'user', text: 'q2' },
    ]
    const items = groupChatEvents(events)
    expect(items.map(i => i.kind)).toEqual(['user', 'tools', 'user'])
  })

  it('rich-card tools (score / readiness_check / issue_api_key / start_job) hoist out of tools group', () => {
    const events: ChatEvent[] = [
      tc('mcp__emerge_tools__read_documents'),
      tc('mcp__emerge_tools__derive_schema'),
      tc('mcp__emerge_tools__score'),
      tc('mcp__emerge_tools__write_schema'),
    ]
    const items = groupChatEvents(events)
    expect(items.map(i => i.kind)).toEqual(['tools', 'hoisted_tool', 'tools'])
    if (items[0].kind === 'tools') {
      expect(items[0].calls.map(c => c.tool_name)).toEqual([
        'mcp__emerge_tools__read_documents',
        'mcp__emerge_tools__derive_schema',
      ])
    }
    if (items[1].kind === 'hoisted_tool') {
      expect(items[1].call.tool_name).toBe('mcp__emerge_tools__score')
    }
    if (items[2].kind === 'tools') {
      expect(items[2].calls.map(c => c.tool_name)).toEqual(['mcp__emerge_tools__write_schema'])
    }
  })

  it('hoisted tool at start does not emit empty leading tools group', () => {
    const events: ChatEvent[] = [
      tc('mcp__emerge_tools__readiness_check'),
      tc('mcp__emerge_tools__write_schema'),
    ]
    const items = groupChatEvents(events)
    expect(items.map(i => i.kind)).toEqual(['hoisted_tool', 'tools'])
  })

  it('back-to-back hoisted tools each become their own item', () => {
    const events: ChatEvent[] = [
      tc('mcp__emerge_tools__readiness_check'),
      tc('mcp__emerge_tools__issue_api_key'),
    ]
    const items = groupChatEvents(events)
    expect(items.map(i => i.kind)).toEqual(['hoisted_tool', 'hoisted_tool'])
  })
})
