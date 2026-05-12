import { beforeEach, describe, expect, it, vi } from 'vitest'
import { usePrompts } from '../../src/stores/prompts'

describe('usePrompts', () => {
  beforeEach(() => {
    usePrompts.getState().reset()
    vi.restoreAllMocks()
  })

  it('loads list + active for a project', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async (input: any) => {
      const url = typeof input === 'string' ? input : input.url
      if (url.endsWith('/prompts')) {
        return new Response(JSON.stringify([
          { prompt_id: 'pr_baseline', label: 'Baseline', derived_from: null,
            is_active: true, created_at: 'x', updated_at: 'x' },
          { prompt_id: 'pr_other', label: 'Other', derived_from: 'pr_baseline',
            is_active: false, created_at: 'x', updated_at: 'x' },
        ]), { status: 200 })
      }
      if (url.endsWith('/prompts/active')) {
        return new Response(JSON.stringify({
          prompt_id: 'pr_baseline',
          label: 'Baseline',
          schema: [{ name: 'x', type: 'string', description: 'd' }],
          global_notes: '',
          derived_from: null,
          created_at: 'x',
          updated_at: 'x',
        }), { status: 200 })
      }
      return new Response('not found', { status: 404 })
    })

    await usePrompts.getState().load('p_abc')
    const state = usePrompts.getState()
    expect(state.list['p_abc']).toHaveLength(2)
    expect(state.activeByProject['p_abc']?.prompt_id).toBe('pr_baseline')
    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })

  it('dedupes concurrent loads', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async (input: any) => {
      const url = typeof input === 'string' ? input : input.url
      if (url.endsWith('/prompts')) {
        return new Response('[]', { status: 200 })
      }
      return new Response('{"prompt_id":"x","label":"x","schema":[],"global_notes":"","derived_from":null,"created_at":"x","updated_at":"x"}', { status: 200 })
    })
    await Promise.all([
      usePrompts.getState().load('p_abc'),
      usePrompts.getState().load('p_abc'),
    ])
    // 2 endpoints × 1 (deduped) = 2 fetches, NOT 4
    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })

  it('invalidate clears project entry', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async () =>
      new Response('[]', { status: 200 }),
    )
    await usePrompts.getState().load('p_abc')
    usePrompts.getState().invalidate('p_abc')
    expect(usePrompts.getState().list['p_abc']).toBeUndefined()
  })
})
