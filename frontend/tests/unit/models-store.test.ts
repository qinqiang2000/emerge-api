import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useModels } from '../../src/stores/models'

describe('useModels', () => {
  beforeEach(() => {
    useModels.getState().reset()
    vi.restoreAllMocks()
  })

  it('loads list + active for a project', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (input: any) => {
      const url = typeof input === 'string' ? input : input.url
      if (url.endsWith('/models')) {
        return new Response(JSON.stringify([
          { model_id: 'm_default', label: 'Default', provider: 'google',
            provider_model_id: 'gemini-2.0-flash', is_active: true, created_at: 'x' },
          { model_id: 'm_sonnet', label: 'Sonnet 4.6', provider: 'anthropic',
            provider_model_id: 'claude-sonnet-4-6', is_active: false, created_at: 'x' },
        ]), { status: 200 })
      }
      if (url.endsWith('/models/active')) {
        return new Response(JSON.stringify({
          model_id: 'm_default',
          label: 'Default',
          provider: 'google',
          provider_model_id: 'gemini-2.0-flash',
          params: { temperature: 0 },
          created_at: 'x',
        }), { status: 200 })
      }
      return new Response('not found', { status: 404 })
    })

    await useModels.getState().load('p_abc')
    const state = useModels.getState()
    expect(state.list['p_abc']).toHaveLength(2)
    expect(state.activeByProject['p_abc']?.provider_model_id).toBe('gemini-2.0-flash')
  })
})
