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
import { useBench } from './bench'
import { _testUtils, useChat } from './chat'
import { useDocs } from './docs'
import { useEval } from './eval'
import { useExperiments } from './experiments'
import { useModels } from './models'
import { useProjects } from './projects'
import { usePrompts } from './prompts'

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
      thinkingLine: '',
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

  it('test_stream_disconnect_surfaces: mid-turn EOF without turn_end → error event + interrupted, not silent', async () => {
    useChat.setState({ chatId: 'c_d000000001', loadedProjectId: 'p_d' })
    localStorage.setItem('emerge.activeChatId.p_d', 'c_d000000001')

    const startTurnSpy = vi.spyOn(turn, 'startTurn').mockResolvedValue({
      turn_id: 't_drop',
      status: 'running',
    })

    const sendP = useChat.getState().send('p_d', 'do a thing')
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    // Agent streams a partial response, then the backend goes away mid-turn:
    // the stream closes (null sentinel = clean EOF) BEFORE any turn_end.
    pushEvent('t_drop', { event: 'agent_text', data: { text: 'partial work' } })
    pushEvent('t_drop', null)

    for (let i = 0; i < 10; i++) await Promise.resolve()
    await sendP

    const after = useChat.getState()
    // The partial agent_text is still there...
    expect(after.events.some(
      e => e.type === 'agent_text' && /partial work/.test(e.text),
    )).toBe(true)
    // ...and the disconnect is now VISIBLE (not a silent re-enable).
    expect(after.events.some(
      e => e.type === 'error' && e.error_code === 'stream_disconnected',
    )).toBe(true)
    // Composer released; `interrupted` armed so the next send rewinds the
    // orphaned partial and retries (same recovery as the Stop button).
    expect(after.busy).toBe(false)
    expect(after.interrupted).toBe(true)
    // Inflight cleared — the dead turn isn't re-attachable.
    expect(after.inflightTurnId).toBeNull()
    expect(localStorage.getItem('turn:c_d000000001')).toBeNull()

    startTurnSpy.mockRestore()
  })

  it('test_token_deltas_accumulate_then_finalize: deltas build one streaming bubble, agent_text replaces it', async () => {
    useChat.setState({ chatId: 'c_s000000001', loadedProjectId: 'p_s' })
    localStorage.setItem('emerge.activeChatId.p_s', 'c_s000000001')
    const startTurnSpy = vi.spyOn(turn, 'startTurn').mockResolvedValue({
      turn_id: 't_s', status: 'running',
    })

    const sendP = useChat.getState().send('p_s', 'stream please')
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    pushEvent('t_s', { event: 'agent_text_delta', data: { text: 'Hel' } })
    pushEvent('t_s', { event: 'agent_text_delta', data: { text: 'lo wor' } })
    for (let i = 0; i < 6; i++) await Promise.resolve()

    // Mid-stream: a single agent_text bubble flagged streaming, text accreted.
    let mid = useChat.getState().events.filter(e => e.type === 'agent_text')
    expect(mid.length).toBe(1)
    expect(mid[0].type === 'agent_text' && mid[0].text).toBe('Hello wor')
    expect(mid[0].type === 'agent_text' && mid[0].streaming).toBe(true)

    // Finalize: authoritative full text replaces the bubble in place (no dup),
    // streaming flag cleared.
    pushEvent('t_s', { event: 'agent_text', data: { text: 'Hello world' } })
    pushEvent('t_s', { event: 'turn_end', data: {} })
    for (let i = 0; i < 10; i++) await Promise.resolve()
    await sendP

    const finalTexts = useChat.getState().events.filter(e => e.type === 'agent_text')
    expect(finalTexts.length).toBe(1)
    expect(finalTexts[0].type === 'agent_text' && finalTexts[0].text).toBe('Hello world')
    expect(finalTexts[0].type === 'agent_text' && finalTexts[0].streaming).toBeFalsy()

    startTurnSpy.mockRestore()
  })

  it('test_thinking_line_is_ephemeral: agent_thinking fills thinkingLine, cleared when text begins and at turn end', async () => {
    useChat.setState({ chatId: 'c_t000000001', loadedProjectId: 'p_t' })
    localStorage.setItem('emerge.activeChatId.p_t', 'c_t000000001')
    const startTurnSpy = vi.spyOn(turn, 'startTurn').mockResolvedValue({
      turn_id: 't_t', status: 'running',
    })

    const sendP = useChat.getState().send('p_t', 'think first')
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    pushEvent('t_t', { event: 'agent_thinking', data: { text: 'let me ' } })
    pushEvent('t_t', { event: 'agent_thinking', data: { text: 'reason' } })
    for (let i = 0; i < 6; i++) await Promise.resolve()
    expect(useChat.getState().thinkingLine).toBe('let me reason')
    // Reasoning never enters the persisted/rendered event log.
    expect(useChat.getState().events.some(e => e.type === 'agent_text')).toBe(false)

    // Visible content begins → the reasoning indicator is dropped.
    pushEvent('t_t', { event: 'agent_text_delta', data: { text: 'Answer' } })
    for (let i = 0; i < 6; i++) await Promise.resolve()
    expect(useChat.getState().thinkingLine).toBe('')

    pushEvent('t_t', { event: 'turn_end', data: {} })
    for (let i = 0; i < 10; i++) await Promise.resolve()
    await sendP
    expect(useChat.getState().thinkingLine).toBe('')

    startTurnSpy.mockRestore()
  })

  it('test_finalize_without_deltas_appends: replay path (no preceding stream) appends a fresh bubble', async () => {
    useChat.setState({ chatId: 'c_r000000001', loadedProjectId: 'p_r' })
    localStorage.setItem('emerge.activeChatId.p_r', 'c_r000000001')
    const startTurnSpy = vi.spyOn(turn, 'startTurn').mockResolvedValue({
      turn_id: 't_r', status: 'running',
    })

    const sendP = useChat.getState().send('p_r', 'replay')
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    // Two full agent_text blocks with no deltas (e.g. catch-up replay) → two
    // distinct bubbles, neither marked streaming.
    pushEvent('t_r', { event: 'agent_text', data: { text: 'one' } })
    pushEvent('t_r', { event: 'agent_text', data: { text: 'two' } })
    pushEvent('t_r', { event: 'turn_end', data: {} })
    for (let i = 0; i < 10; i++) await Promise.resolve()
    await sendP

    const texts = useChat.getState().events.filter(e => e.type === 'agent_text')
    expect(texts.map(e => (e.type === 'agent_text' ? e.text : ''))).toEqual(['one', 'two'])
    expect(texts.every(e => e.type === 'agent_text' && !e.streaming)).toBe(true)

    startTurnSpy.mockRestore()
  })
})

// T9 — cross-store invalidation: when a Bench-mutating tool succeeds, the
// chat slice must call `useBench.getState().invalidate(slug)` so the next
// Bench overlay open re-fetches the aggregator. The plan enumerates 9 tools:
// promote_experiment, run_experiment_eval, create_experiment,
// archive_experiment, delete_experiment, write_prompt,
// switch_active_prompt, switch_active_model, score.
//
// We drive `handleToolResult` (re-exported via _testUtils) directly with a
// seeded `tool_call` event in the chat slice for each tool — that's the
// same entry point the SSE branch in _consumeStream uses, but without the
// async generator plumbing.
describe('chat store: cross-store invalidation → useBench.invalidate', () => {
  const PID = 'proj-a'
  const TUID = 't_use_42'

  function seedToolCall(toolName: string) {
    useChat.setState({
      chatId: 'c_initial0001',
      events: [{
        type: 'tool_call',
        tool_use_id: TUID,
        tool_name: toolName,
        tool_input: {},
        tool_result: null,
        ok: true,
      }],
      busy: false,
      loadedProjectId: PID,
      loadedUnboundChatId: null,
      chatsByProject: {},
      chatsUnbound: [],
      streamAbort: null,
      inflightTurnId: null,
      interrupted: false,
    })
  }

  beforeEach(() => {
    try { localStorage.clear() } catch { /* ignore */ }
    vi.restoreAllMocks()
    useBench.setState({ byProject: {}, loading: {} })
    // Stub the side-effect `load` / `refresh` calls on sibling stores so
    // `handleToolResult`'s post-invalidate refetch helpers don't fire real
    // network requests (no API base URL in jsdom → unhandled rejection).
    // We're only asserting the BENCH invalidate spy here; the other store
    // wirings have their own coverage.
    vi.spyOn(usePrompts.getState(), 'load').mockResolvedValue(undefined)
    vi.spyOn(useModels.getState(), 'load').mockResolvedValue(undefined)
    vi.spyOn(useExperiments.getState(), 'load').mockResolvedValue(undefined)
    vi.spyOn(useEval.getState(), 'refresh').mockResolvedValue(null)
    vi.spyOn(useDocs.getState(), 'refresh').mockResolvedValue(undefined)
    vi.spyOn(useProjects.getState(), 'refresh').mockResolvedValue(undefined)
    // useSchema.invalidate is sync — no need to stub.
  })

  // Each of the 9 plan-listed tools: a successful tool_result MUST trigger
  // `useBench.invalidate(slug)`. We don't test the other invalidations the
  // same handler triggers (those have their own coverage upstream); we only
  // assert the bench invalidate spy fires with the right slug.
  const BENCH_INVALIDATING_TOOLS = [
    'mcp__emerge_tools__promote_experiment',
    'mcp__emerge_tools__run_experiment_eval',
    'mcp__emerge_tools__create_experiment',
    'mcp__emerge_tools__archive_experiment',
    'mcp__emerge_tools__delete_experiment',
    'mcp__emerge_tools__write_prompt',
    'mcp__emerge_tools__switch_active_prompt',
    'mcp__emerge_tools__switch_active_model',
    'mcp__emerge_tools__score',
  ] as const

  for (const toolName of BENCH_INVALIDATING_TOOLS) {
    it(`invalidates useBench(${PID}) on tool_result for ${toolName}`, () => {
      seedToolCall(toolName)
      const benchSpy = vi.spyOn(useBench.getState(), 'invalidate')

      _testUtils.handleToolResult(
        { tool_use_id: TUID, result_text: '{}', ok: true },
        PID,
        null,
      )

      expect(benchSpy).toHaveBeenCalledWith(PID)
    })
  }

  it('does NOT invalidate useBench when tool_result.ok is false', () => {
    // Sanity: failed tool calls already skip every other invalidate branch
    // (`if (... && d.ok)`), so the new bench branch must respect that too.
    seedToolCall('mcp__emerge_tools__promote_experiment')
    const benchSpy = vi.spyOn(useBench.getState(), 'invalidate')

    _testUtils.handleToolResult(
      { tool_use_id: TUID, result_text: 'err', ok: false },
      PID,
      null,
    )

    expect(benchSpy).not.toHaveBeenCalled()
  })

  it('does NOT invalidate useBench for an unrelated tool (e.g. list_docs)', () => {
    // Negative case — ensures we didn't accidentally fire invalidate on
    // every successful tool. `list_docs` mutates nothing.
    seedToolCall('mcp__emerge_tools__list_docs')
    const benchSpy = vi.spyOn(useBench.getState(), 'invalidate')

    _testUtils.handleToolResult(
      { tool_use_id: TUID, result_text: '{}', ok: true },
      PID,
      null,
    )

    expect(benchSpy).not.toHaveBeenCalled()
  })
})
