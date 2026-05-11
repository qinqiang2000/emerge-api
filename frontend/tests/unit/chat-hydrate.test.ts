import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../src/lib/api'
import { useChat, _testUtils } from '../../src/stores/chat'

const { reduceEvents, chatIdFor } = _testUtils

describe('reduceEvents', () => {
  it('pairs tool_call + tool_result by tool_use_id into one tool_call event', () => {
    const out = reduceEvents([
      { type: 'tool_call', tool_use_id: 'tu_1', tool_name: 'mcp__emerge_tools__write_schema', tool_input: { a: 1 }, ok: true },
      { type: 'tool_result', tool_use_id: 'tu_1', result_text: '{"ok":true}', ok: true },
    ])
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({
      type: 'tool_call',
      tool_use_id: 'tu_1',
      tool_name: 'mcp__emerge_tools__write_schema',
      tool_result: '{"ok":true}',
      ok: true,
    })
  })

  it('carries ok=false from the tool_result onto the paired tool_call', () => {
    const out = reduceEvents([
      { type: 'tool_call', tool_use_id: 'tu_x', tool_name: 'foo', tool_input: {}, ok: true },
      { type: 'tool_result', tool_use_id: 'tu_x', result_text: 'boom', ok: false },
    ])
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ type: 'tool_call', ok: false, tool_result: 'boom' })
  })

  it('drops an orphan tool_result with no matching tool_call', () => {
    const out = reduceEvents([
      { type: 'tool_result', tool_use_id: 'tu_orphan', result_text: 'nope', ok: true },
    ])
    expect(out).toHaveLength(0)
  })

  it('maps user / agent_text / error', () => {
    const out = reduceEvents([
      { type: 'user', text: 'hi' },
      { type: 'agent_text', text: 'hello back' },
      { type: 'error', error_code: 'E_X', error_message_en: 'something failed' },
    ])
    expect(out).toEqual([
      { type: 'user', text: 'hi' },
      { type: 'agent_text', text: 'hello back' },
      { type: 'error', error_code: 'E_X', error_message_en: 'something failed' },
    ])
  })

  it('skips turn_end and unknown line types', () => {
    const out = reduceEvents([
      { type: 'turn_end' },
      { type: 'user_acknowledged' },
      { type: 'mystery_future_type', text: 'x' },
      { type: 'user', text: 'real' },
    ])
    expect(out).toEqual([{ type: 'user', text: 'real' }])
  })

  it('pairs a tool_result with the most recent matching tool_call', () => {
    const out = reduceEvents([
      { type: 'tool_call', tool_use_id: 'tu_a', tool_name: 'a', tool_input: {}, ok: true },
      { type: 'tool_call', tool_use_id: 'tu_b', tool_name: 'b', tool_input: {}, ok: true },
      { type: 'tool_result', tool_use_id: 'tu_a', result_text: 'AAA', ok: true },
    ])
    expect(out).toHaveLength(2)
    expect(out[0]).toMatchObject({ tool_use_id: 'tu_a', tool_result: 'AAA' })
    expect(out[1]).toMatchObject({ tool_use_id: 'tu_b', tool_result: null })
  })
})

describe('chatIdFor', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns the persisted value when localStorage already has it', () => {
    localStorage.setItem('emerge.chatId.p_x', 'c_persisted123')
    expect(chatIdFor('p_x')).toBe('c_persisted123')
  })

  it('mints and persists a fresh id when none exists', () => {
    expect(localStorage.getItem('emerge.chatId.p_new')).toBeNull()
    const id = chatIdFor('p_new')
    expect(id).toMatch(/^c_[0-9a-f]{12}$/)
    expect(localStorage.getItem('emerge.chatId.p_new')).toBe(id)
  })
})

describe('enterProject', () => {
  beforeEach(() => {
    localStorage.clear()
    useChat.setState({ events: [], busy: false, chatId: 'c_initial', loadedProjectId: null })
    vi.restoreAllMocks()
  })

  it('switch case: clears events synchronously then hydrates from getChatEvents', async () => {
    const spy = vi.spyOn(api, 'getChatEvents').mockResolvedValue([{ type: 'user', text: 'hello' }])
    useChat.setState({
      events: [{ type: 'user', text: 'stale from old project' }],
      loadedProjectId: 'p_old',
      chatId: 'c_old',
    })

    useChat.getState().enterProject('p_new')
    // synchronous: cleared + rebound
    const after = useChat.getState()
    expect(after.events).toEqual([])
    expect(after.loadedProjectId).toBe('p_new')
    expect(after.chatId).not.toBe('c_old')

    // microtask: hydrated from the mock
    await Promise.resolve()
    await Promise.resolve()
    expect(spy).toHaveBeenCalled()
    expect(useChat.getState().events).toEqual([{ type: 'user', text: 'hello' }])
    expect(useChat.getState().loadedProjectId).toBe('p_new')
  })

  it('adopt case: loadedProjectId null + events non-empty → keep events, no fetch', () => {
    const spy = vi.spyOn(api, 'getChatEvents').mockResolvedValue([])
    useChat.setState({ events: [{ type: 'user', text: 'mid' }], loadedProjectId: null, chatId: 'c_inflight' })

    useChat.getState().enterProject('p_abc')
    const after = useChat.getState()
    expect(after.events).toEqual([{ type: 'user', text: 'mid' }])
    expect(after.loadedProjectId).toBe('p_abc')
    expect(after.chatId).toBe('c_inflight')
    expect(localStorage.getItem('emerge.chatId.p_abc')).toBe('c_inflight')
    expect(spy).not.toHaveBeenCalled()
  })

  it("'p_unset' → no-op (no state change, no fetch)", () => {
    const spy = vi.spyOn(api, 'getChatEvents').mockResolvedValue([])
    const before = { ...useChat.getState() }
    useChat.getState().enterProject('p_unset')
    const after = useChat.getState()
    expect(after.events).toEqual(before.events)
    expect(after.loadedProjectId).toBe(before.loadedProjectId)
    expect(after.chatId).toBe(before.chatId)
    expect(spy).not.toHaveBeenCalled()
  })

  it('re-entering the already-loaded project is a no-op (no re-clear / re-hydrate)', () => {
    const spy = vi.spyOn(api, 'getChatEvents').mockResolvedValue([])
    useChat.setState({ events: [{ type: 'agent_text', text: 'kept' }], loadedProjectId: 'p_same', chatId: 'c_same' })
    useChat.getState().enterProject('p_same')
    expect(useChat.getState().events).toEqual([{ type: 'agent_text', text: 'kept' }])
    expect(spy).not.toHaveBeenCalled()
  })
})
