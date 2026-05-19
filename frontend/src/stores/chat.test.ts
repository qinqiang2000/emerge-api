// M11 T5 store tests: send() splits into startTurn + attachStream; lifecycle
// methods detach the SSE without killing the backend turn; Stop button
// explicitly POSTs cancel.
//
// These tests pin the bleed-across-switch contract (the live bug M11 was
// born to fix) plus the cancel-calls-server contract that distinguishes the
// new "detach != cancel" semantics. Re-attach on enter (T6) is left as a
// `.skip` placeholder so a future task doesn't forget the gap.
//
// Mock surface: ``../lib/turn`` is stubbed end-to-end — startTurn returns a
// deterministic turn_id; attachStream is a controllable async generator
// (push events into a queue, the generator yields them in order, throws
// AbortError when the signal aborts). ``../lib/api`` is stubbed for the
// fire-and-forget hydrate / listChats calls so they don't try to fetch
// against a relative URL.

import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../lib/api'
import * as turn from '../lib/turn'
import { useChat } from './chat'

// ── attachStream mock plumbing ───────────────────────────────────────────
// Each test fills `queues[turnId]` with the events to yield (in order). The
// generator polls the queue; if the abort signal fires while the queue is
// empty, the generator throws an AbortError. A `null` sentinel in the queue
// closes the generator cleanly (simulates normal end-of-stream).
type FakeEvent = { event: string; data: unknown } | null
const queues: Record<string, FakeEvent[]> = {}
const waiters: Record<string, Array<() => void>> = {}

function pushEvent(turnId: string, ev: FakeEvent) {
  if (!queues[turnId]) queues[turnId] = []
  queues[turnId].push(ev)
  const w = waiters[turnId]
  if (w) {
    waiters[turnId] = []
    for (const r of w) r()
  }
}

function makeAttachStreamMock() {
  return function attachStreamMock(
    _cid: string,
    tid: string,
    opts: { after_offset: number; signal: AbortSignal },
  ): AsyncIterable<turn.StartTurnResponse extends infer _ ? { event: string; data: unknown } : never> {
    return {
      [Symbol.asyncIterator]() {
        return {
          async next() {
            // eslint-disable-next-line no-constant-condition
            while (true) {
              if (opts.signal.aborted) {
                const err = new Error('aborted')
                ;(err as { name?: string }).name = 'AbortError'
                throw err
              }
              const q = queues[tid] ?? []
              if (q.length > 0) {
                const ev = q.shift()!
                if (ev === null) return { value: undefined, done: true }
                return { value: ev, done: false }
              }
              // Empty — wait for the next push (or abort).
              await new Promise<void>(resolve => {
                if (!waiters[tid]) waiters[tid] = []
                waiters[tid].push(resolve)
                opts.signal.addEventListener('abort', () => resolve(), { once: true })
              })
            }
          },
        }
      },
    } as AsyncIterable<{ event: string; data: unknown }>
  }
}

// Quiet stand-ins for the fire-and-forget hydrate / list calls. The hydrate
// is wrapped in `void (async () => ...)` so unresolved promises don't break
// later assertions; making them resolve to empty arrays is the cheapest fix.
function stubApi() {
  vi.spyOn(api, 'getChatEvents').mockResolvedValue([])
  vi.spyOn(api, 'getUnboundChatEvents').mockResolvedValue([])
  vi.spyOn(api, 'getChatList').mockResolvedValue([])
  vi.spyOn(api, 'listUnboundChats').mockResolvedValue([])
}

describe('chat store: send() split + lifecycle detach', () => {
  beforeEach(() => {
    // Drain queues so a previous test's leftover events don't drip into the
    // next one's stream.
    for (const k of Object.keys(queues)) delete queues[k]
    for (const k of Object.keys(waiters)) delete waiters[k]

    try { localStorage.clear() } catch { /* ignore */ }
    useChat.setState({
      chatId: 'c_initial0001',
      events: [],
      busy: false,
      loadedProjectId: null,
      loadedUnboundChatId: null,
      chatsByProject: {},
      chatsUnbound: [],
      streamAbort: null,
      inflightTurnId: null,
      interrupted: false,
    })

    vi.restoreAllMocks()
    stubApi()
    vi.spyOn(turn, 'startTurn').mockImplementation(async (_cid, _body) => ({
      turn_id: 't_default',
      status: 'running',
    }))
    vi.spyOn(turn, 'cancelTurn').mockResolvedValue({ status: 'cancelled' })
    vi.spyOn(turn, 'attachStream').mockImplementation(makeAttachStreamMock())
  })

  it('test_switch_project_mid_turn_does_not_bleed: post-detach chunks land nowhere', async () => {
    // Arrange chat A as the active project chat.
    useChat.setState({
      chatId: 'c_a000000001',
      loadedProjectId: 'p_a',
    })
    localStorage.setItem('emerge.activeChatId.p_a', 'c_a000000001')

    // Bespoke startTurn → turn_id 't_a'. attachStream will pull from
    // queues['t_a'] and yield in order; we'll keep pumping past the switch.
    const startTurnSpy = vi.spyOn(turn, 'startTurn').mockResolvedValue({
      turn_id: 't_a',
      status: 'running',
    })

    // Kick off send(). The first agent_text lands BEFORE we switch.
    const sendP = useChat.getState().send('p_a', 'hello on A')
    // Microtask flush so `startTurn` resolves and the stream attach begins.
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    pushEvent('t_a', { event: 'agent_text', data: { text: 'partial A response' } })
    // Generous microtask flush so the agent_text is dispatched into events[].
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    // Sanity: the in-flight turn id was persisted on A, and the partial
    // agent_text was dispatched before we tried to switch.
    expect(useChat.getState().chatId).toBe('c_a000000001')
    expect(useChat.getState().inflightTurnId).toBe('t_a')
    expect(localStorage.getItem('turn:c_a000000001')).toBe('t_a')
    expect(useChat.getState().events.some(
      e => e.type === 'agent_text' && /partial A response/.test(e.text),
    )).toBe(true)

    // Act: user clicks chat B in the same project. switchChat must call
    // _detachStream — the abort propagates into the (still-running)
    // attachStream generator, which throws AbortError and lets send()'s
    // `finally` fall through. The OLD chat's `inflightTurnId` localStorage
    // entry MUST stay so T6's re-enter can re-attach.
    useChat.getState().switchChat('p_a', 'c_b000000001')

    // Push more chunks AFTER the switch — these must end up nowhere visible.
    pushEvent('t_a', { event: 'agent_text', data: { text: 'should-not-bleed' } })
    pushEvent('t_a', { event: 'turn_end', data: {} })

    // Let the abort+finally settle and the async hydrate resolve.
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    await sendP

    const after = useChat.getState()
    // The NEW chat slice is in focus and has no events from chat A's stream.
    expect(after.chatId).toBe('c_b000000001')
    expect(after.events.some(
      e => e.type === 'agent_text' && /should-not-bleed/.test(e.text),
    )).toBe(false)
    // Chat A's turn:cid entry survives → T6 can re-attach by reading it.
    expect(localStorage.getItem('turn:c_a000000001')).toBe('t_a')
    // streamAbort cleared because we're no longer attached.
    expect(after.streamAbort).toBeNull()
    // No spurious cancelTurn was POSTed — detach must not cancel.
    expect(turn.cancelTurn).not.toHaveBeenCalled()

    startTurnSpy.mockRestore()
  })

  it('test_reenter_chat_reattaches: hydrate + fetchTurnState(running) → attachStream(after_offset=events.length)', async () => {
    // Seed: chat A had an in-flight turn (t_a) that's still running on the
    // backend. localStorage carries the turn id so re-enter can probe. Also
    // pre-bind activeChatId.p_a → c_a... so enterProject('p_a') picks up the
    // SAME chat id (otherwise chatIdFor mints a fresh one and the turn:{cid}
    // entry under c_a... would be ignored).
    localStorage.setItem('emerge.activeChatId.p_a', 'c_a000000001')
    localStorage.setItem('turn:c_a000000001', 't_a')

    // fetchTurnState reports turn t_a still running, last_offset=3 (jsonl has
    // 3 lines persisted). The chat's hydrate will load those 3 events; the
    // re-attached stream should pick up at after_offset=3.
    const turnStateSpy = vi.spyOn(turn, 'fetchTurnState').mockResolvedValue({
      active_turn_id: 't_a',
      status: 'running',
      last_offset: 3,
    })

    // getChatEvents returns 3 events (matching last_offset=3). reduceEvents
    // produces 3 ChatEvents from these.
    const hydrateEvents = [
      { type: 'user', text: 'hello A' },
      { type: 'agent_text', text: 'first chunk' },
      { type: 'agent_text', text: 'second chunk' },
    ]
    vi.spyOn(api, 'getChatEvents').mockResolvedValue(hydrateEvents)

    // Re-attached stream yields two more agent_text events, then closes
    // naturally via a turn_end sentinel. (We use the same attachStream mock
    // from beforeEach; the queue keyed by turn_id is the test's lever.)
    pushEvent('t_a', { event: 'agent_text', data: { text: 'live chunk 1' } })
    pushEvent('t_a', { event: 'agent_text', data: { text: 'live chunk 2' } })
    pushEvent('t_a', { event: 'turn_end', data: {} })

    // Act: enterProject('p_a') hydrates (installs 3 events) then probes
    // turn_state. Since the turn is still running and matches, _maybeReattach
    // opens attachStream at after_offset=3 and feeds events into the slice.
    useChat.getState().enterProject('p_a')

    // Flush enough microtasks for: hydrate await → set → fetchTurnState
    // await → _consumeStream loop → turn_end. The attachStream mock yields
    // one event per next() call, so several microtask ticks are needed.
    for (let i = 0; i < 20; i++) await Promise.resolve()

    const after = useChat.getState()
    // Hydrated 3 + reattached 2 = 5 events on the slice.
    expect(after.events.length).toBe(5)
    expect(after.events.some(
      e => e.type === 'agent_text' && /live chunk 1/.test(e.text),
    )).toBe(true)
    expect(after.events.some(
      e => e.type === 'agent_text' && /live chunk 2/.test(e.text),
    )).toBe(true)
    // attachStream was called with after_offset matching the hydrate length.
    expect(turn.attachStream).toHaveBeenCalledWith(
      'c_a000000001',
      't_a',
      expect.objectContaining({ after_offset: 3 }),
    )
    // Natural stream end → inflight cleared on slice + localStorage.
    expect(after.inflightTurnId).toBeNull()
    expect(localStorage.getItem('turn:c_a000000001')).toBeNull()
    // streamAbort cleared post-natural-end.
    expect(after.streamAbort).toBeNull()

    turnStateSpy.mockRestore()
  })

  it('test_cancel_calls_server: cancel() POSTs to the cancel endpoint and clears inflight state', async () => {
    useChat.setState({ chatId: 'c_c000000001', loadedProjectId: 'p_c' })
    localStorage.setItem('emerge.activeChatId.p_c', 'c_c000000001')

    const startTurnSpy = vi.spyOn(turn, 'startTurn').mockResolvedValue({
      turn_id: 't_cancel',
      status: 'running',
    })

    // Begin a turn but never push events — it stays busy until cancel.
    const sendP = useChat.getState().send('p_c', 'work on this')
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    expect(useChat.getState().busy).toBe(true)
    expect(useChat.getState().inflightTurnId).toBe('t_cancel')

    // Act: user hits Stop.
    useChat.getState().cancel()
    // Let the cancel + abort + finally settle.
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    await sendP

    // POST cancel was issued for the live turn.
    expect(turn.cancelTurn).toHaveBeenCalledWith('c_c000000001', 't_cancel')
    // Inflight cleared on slice + localStorage.
    expect(useChat.getState().inflightTurnId).toBeNull()
    expect(localStorage.getItem('turn:c_c000000001')).toBeNull()
    // Busy released; interrupted flipped so the next send rewinds the tail.
    expect(useChat.getState().busy).toBe(false)
    expect(useChat.getState().interrupted).toBe(true)

    startTurnSpy.mockRestore()
  })
})
