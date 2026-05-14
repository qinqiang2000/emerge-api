import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useChat } from '../../src/stores/chat'
import { useDocs } from '../../src/stores/docs'
import { useProjects } from '../../src/stores/projects'

// Drive a deterministic SSE stream from each test case. The mock yields
// `events` then a final `turn_end` so the store unwinds cleanly.
const _emitted: Array<{ event: string; data: unknown }> = []
vi.mock('../../src/lib/sse', () => ({
  streamSSE: async function* () {
    for (const e of _emitted) yield e
    yield { event: 'turn_end', data: {} }
  },
}))

beforeEach(() => {
  _emitted.length = 0
  useChat.setState({ events: [], busy: false, loadedProjectId: null, chatId: 'c_test', interrupted: false })
  useProjects.setState({ projects: [], selectedId: null, loading: false })
  // Silence post-mint side-effect fetches (projects refresh, listChats, docs refresh).
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() =>
    Promise.resolve(new Response('[]', { status: 200 })),
  ))
  // localStorage is a noop in jsdom by default; here we want the writes to
  // actually persist so we can assert them.
  try { localStorage.clear() } catch { /* ignore */ }
})


describe('chat store: project_minted SSE handling (empty-hero drop flow)', () => {
  it('binds chatId under the new pid, flips selectedId, refreshes stores', async () => {
    _emitted.push({ event: 'project_minted', data: { project_id: 'p_freshmint01', name: 'Untitled-251205-093012' } })
    _emitted.push({ event: 'agent_text', data: { text: 'ok' } })

    const refreshProjects = vi.spyOn(useProjects.getState(), 'refresh').mockResolvedValue()
    const refreshDocs = vi.spyOn(useDocs.getState(), 'refresh').mockResolvedValue()

    await useChat.getState().send('p_unset', '/init pull these')

    // selectedId flipped to the minted pid.
    expect(useProjects.getState().selectedId).toBe('p_freshmint01')
    // loadedProjectId mirrors the new pid so ChatPanel's useEffect early-returns
    // (no clear-and-hydrate) — events stay in place.
    expect(useChat.getState().loadedProjectId).toBe('p_freshmint01')
    // localStorage keyed under the new pid (so a reload pulls the right history).
    expect(localStorage.getItem('emerge.activeChatId.p_freshmint01')).toBe('c_test')
    // Cross-store refreshes were kicked off.
    expect(refreshProjects).toHaveBeenCalled()
    expect(refreshDocs).toHaveBeenCalledWith('p_freshmint01')
    // The user message + agent_text both rendered.
    const types = useChat.getState().events.map(e => e.type)
    expect(types).toContain('user')
    expect(types).toContain('agent_text')

    refreshProjects.mockRestore()
    refreshDocs.mockRestore()
  })

  it('does nothing special when project_minted is not emitted (legacy path)', async () => {
    _emitted.push({ event: 'agent_text', data: { text: 'hello' } })

    await useChat.getState().send('p_unset', 'hi')

    expect(useProjects.getState().selectedId).toBeNull()
    // loadedProjectId stays untouched (no mint happened).
    expect(useChat.getState().loadedProjectId).toBeNull()
  })
})
