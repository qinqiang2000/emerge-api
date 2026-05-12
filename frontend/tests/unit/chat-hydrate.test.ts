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
    localStorage.setItem('emerge.activeChatId.p_x', 'c_persisted123')
    expect(chatIdFor('p_x')).toBe('c_persisted123')
  })

  it('mints and persists a fresh id when none exists', () => {
    expect(localStorage.getItem('emerge.activeChatId.p_new')).toBeNull()
    const id = chatIdFor('p_new')
    expect(id).toMatch(/^c_[0-9a-f]{12}$/)
    expect(localStorage.getItem('emerge.activeChatId.p_new')).toBe(id)
  })
})

describe('enterProject', () => {
  beforeEach(() => {
    localStorage.clear()
    useChat.setState({ events: [], busy: false, chatId: 'c_initial', loadedProjectId: null })
    vi.restoreAllMocks()
    // enterProject fires a fire-and-forget listChats; stub it out so the
    // test environment doesn't try to fetch a relative URL.
    vi.spyOn(api, 'getChatList').mockResolvedValue([])
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
    expect(localStorage.getItem('emerge.activeChatId.p_abc')).toBe('c_inflight')
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

  it('switch race: a fetch in-flight when the user switches away again is dropped', async () => {
    // Two deferred promises so we can resolve the B fetch *after* switching to C.
    let resolveB!: (v: unknown[]) => void
    const deferredB = new Promise<unknown[]>(res => { resolveB = res })
    const deferredC = new Promise<unknown[]>(res => res([]))
    const spy = vi.spyOn(api, 'getChatEvents')
      .mockImplementationOnce(() => deferredB)   // first call (enterProject p_b)
      .mockImplementationOnce(() => deferredC)   // second call (enterProject p_c)

    useChat.setState({ events: [], loadedProjectId: 'p_a', chatId: 'c_a' })

    useChat.getState().enterProject('p_b')
    expect(useChat.getState().loadedProjectId).toBe('p_b')

    // User switches away again before fetch B resolves.
    useChat.getState().enterProject('p_c')
    expect(useChat.getState().loadedProjectId).toBe('p_c')

    // Now fetch B resolves with content — must be dropped (we already moved to p_c).
    resolveB([{ type: 'user', text: 'B-history-event' }])
    await Promise.resolve()
    await Promise.resolve()

    const after = useChat.getState()
    expect(after.loadedProjectId).toBe('p_c')
    expect(after.events.some(e => e.type === 'user' && e.text === 'B-history-event')).toBe(false)
    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('send during hydration: server history is prepended to the user in-flight tail', async () => {
    let resolveFetch!: (v: unknown[]) => void
    const deferred = new Promise<unknown[]>(res => { resolveFetch = res })
    vi.spyOn(api, 'getChatEvents').mockImplementation(() => deferred)

    useChat.setState({ events: [], loadedProjectId: 'p_old', chatId: 'c_old' })

    useChat.getState().enterProject('p_new')
    // Synchronous: events cleared, prefixLen captured = 0 by the store.
    expect(useChat.getState().events).toEqual([])

    // Simulate the user sending mid-fetch (grows events past prefixLen).
    useChat.setState(s => ({
      events: [...s.events, { type: 'user', text: 'mid-fetch' }],
      busy: true,
    }))

    // Now the hydrate resolves with prior server history.
    resolveFetch([{ type: 'agent_text', text: 'old history' }])
    await Promise.resolve()
    await Promise.resolve()

    expect(useChat.getState().events).toEqual([
      { type: 'agent_text', text: 'old history' },
      { type: 'user', text: 'mid-fetch' },
    ])
  })

  it('fresh-load first-entry switch: null loadedProjectId + empty events still hydrates', async () => {
    const spy = vi.spyOn(api, 'getChatEvents').mockResolvedValue([
      { type: 'agent_text', text: 'historical' },
    ])
    useChat.setState({ events: [], loadedProjectId: null, chatId: 'c_initial' })

    useChat.getState().enterProject('p_x')

    // Synchronously: switch branch ran (adopt branch needs events.length > 0).
    const sync = useChat.getState()
    expect(sync.loadedProjectId).toBe('p_x')
    expect(sync.chatId).toBe(chatIdFor('p_x'))
    expect(sync.events).toEqual([])

    await Promise.resolve()
    await Promise.resolve()
    expect(spy).toHaveBeenCalled()
    expect(useChat.getState().events).toEqual([{ type: 'agent_text', text: 'historical' }])
  })
})

describe('localStorage key migration', () => {
  beforeEach(() => {
    localStorage.clear()
    useChat.setState({ events: [], busy: false, chatId: 'c_initial', loadedProjectId: null })
    vi.restoreAllMocks()
  })

  it('chatIdFor migrates emerge.chatId.<pid> → emerge.activeChatId.<pid> on first read', () => {
    localStorage.setItem('emerge.chatId.p_old', 'c_legacy00001')
    expect(chatIdFor('p_old')).toBe('c_legacy00001')
    expect(localStorage.getItem('emerge.activeChatId.p_old')).toBe('c_legacy00001')
    expect(localStorage.getItem('emerge.chatId.p_old')).toBe('c_legacy00001')
  })

  it('chatIdFor prefers the new key when both exist', () => {
    localStorage.setItem('emerge.chatId.p_x', 'c_old000000001')
    localStorage.setItem('emerge.activeChatId.p_x', 'c_new000000001')
    expect(chatIdFor('p_x')).toBe('c_new000000001')
  })
})

describe('listChats', () => {
  beforeEach(() => {
    localStorage.clear()
    useChat.setState({ events: [], busy: false, chatId: 'c_initial', loadedProjectId: null, chatsByProject: {} })
    vi.restoreAllMocks()
  })

  it('fetches and stores the list under chatsByProject[pid]', async () => {
    const list = [
      { chat_id: 'c_aaaaaaaaaaaa', label: 'extract', kind: 'run', ts_iso: '2026-05-12T09:00:00+00:00', n_events: 4 },
    ]
    vi.spyOn(api, 'getChatList').mockResolvedValue(list)
    await useChat.getState().listChats('p_1')
    expect(useChat.getState().chatsByProject['p_1']).toEqual(list)
  })

  it('a failed fetch leaves chatsByProject[pid] = [] (never throws)', async () => {
    vi.spyOn(api, 'getChatList').mockResolvedValue([])
    await useChat.getState().listChats('p_1')
    expect(useChat.getState().chatsByProject['p_1']).toEqual([])
  })
})

describe('switchChat', () => {
  beforeEach(() => {
    localStorage.clear()
    useChat.setState({ events: [], busy: false, chatId: 'c_initial', loadedProjectId: 'p_a', chatsByProject: {} })
    vi.restoreAllMocks()
  })

  it('persists the new active chat id, clears events, hydrates from the server', async () => {
    const spy = vi.spyOn(api, 'getChatEvents').mockResolvedValue([{ type: 'agent_text', text: 'from chat 2' }])
    useChat.setState({ events: [{ type: 'user', text: 'stale' }], chatId: 'c_old000000001', loadedProjectId: 'p_a' })
    useChat.getState().switchChat('p_a', 'c_new000000001')
    const after = useChat.getState()
    expect(after.chatId).toBe('c_new000000001')
    expect(after.events).toEqual([])
    expect(localStorage.getItem('emerge.activeChatId.p_a')).toBe('c_new000000001')
    await Promise.resolve(); await Promise.resolve()
    expect(spy).toHaveBeenCalledWith('p_a', 'c_new000000001')
    expect(useChat.getState().events).toEqual([{ type: 'agent_text', text: 'from chat 2' }])
  })

  it('switching to the already-active chat is a no-op (no clear, no fetch)', () => {
    const spy = vi.spyOn(api, 'getChatEvents').mockResolvedValue([])
    useChat.setState({ events: [{ type: 'agent_text', text: 'kept' }], chatId: 'c_same00000001', loadedProjectId: 'p_a' })
    useChat.getState().switchChat('p_a', 'c_same00000001')
    expect(useChat.getState().events).toEqual([{ type: 'agent_text', text: 'kept' }])
    expect(spy).not.toHaveBeenCalled()
  })

  it('switch race: a hydrate in-flight when the user switches again is dropped', async () => {
    let resolveA!: (v: unknown[]) => void
    const deferredA = new Promise<unknown[]>(res => { resolveA = res })
    vi.spyOn(api, 'getChatEvents')
      .mockImplementationOnce(() => deferredA)
      .mockImplementationOnce(() => Promise.resolve([]))
    useChat.setState({ events: [], chatId: 'c_orig00000001', loadedProjectId: 'p_a' })
    useChat.getState().switchChat('p_a', 'c_aaa000000001')
    useChat.getState().switchChat('p_a', 'c_bbb000000001')
    resolveA([{ type: 'user', text: 'chat-A history' }])
    await Promise.resolve(); await Promise.resolve()
    const after = useChat.getState()
    expect(after.chatId).toBe('c_bbb000000001')
    expect(after.events.some(e => e.type === 'user' && e.text === 'chat-A history')).toBe(false)
  })
})

describe('newChat', () => {
  beforeEach(() => {
    localStorage.clear()
    useChat.setState({ events: [], busy: false, chatId: 'c_initial', loadedProjectId: 'p_a', chatsByProject: {} })
    vi.restoreAllMocks()
  })

  it('mints a fresh id, persists it as active, clears events, does NOT touch the server', () => {
    const evSpy = vi.spyOn(api, 'getChatEvents').mockResolvedValue([])
    const listSpy = vi.spyOn(api, 'getChatList').mockResolvedValue([])
    useChat.setState({ events: [{ type: 'user', text: 'old chat' }], chatId: 'c_old000000001', loadedProjectId: 'p_a' })
    useChat.getState().newChat('p_a')
    const after = useChat.getState()
    expect(after.chatId).toMatch(/^c_[0-9a-f]{12}$/)
    expect(after.chatId).not.toBe('c_old000000001')
    expect(after.events).toEqual([])
    expect(after.loadedProjectId).toBe('p_a')
    expect(localStorage.getItem('emerge.activeChatId.p_a')).toBe(after.chatId)
    expect(evSpy).not.toHaveBeenCalled()
    expect(listSpy).not.toHaveBeenCalled()
  })
})
