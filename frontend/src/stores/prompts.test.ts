import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { usePrompts } from './prompts'
import type { SchemaField } from './schema'

const LODGING: SchemaField[] = [
  { name: 'guestName', type: 'string', description: '' },
  { name: 'checkInDate', type: 'string', description: '' },
]

function okFetch(schema: SchemaField[] = LODGING) {
  return vi.fn(async () => ({
    ok: true,
    json: async () => ({ prompt_id: 'pr_lodging', label: '住宿', schema }),
  })) as unknown as typeof fetch
}

function notFoundFetch() {
  return vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })) as unknown as typeof fetch
}

function callCount(f: typeof fetch): number {
  return (f as unknown as ReturnType<typeof vi.fn>).mock.calls.length
}

describe('usePrompts.loadPromptSchema', () => {
  beforeEach(() => usePrompts.getState().reset())
  afterEach(() => vi.restoreAllMocks())

  it('caches a fetched prompt schema under projectId → promptId', async () => {
    const f = okFetch()
    vi.stubGlobal('fetch', f)

    await usePrompts.getState().loadPromptSchema('proj', 'pr_lodging')

    expect(usePrompts.getState().schemaById['proj']['pr_lodging']).toEqual(LODGING)
    expect(callCount(f)).toBe(1)
  })

  it('does not re-fetch a schema it already has', async () => {
    const f = okFetch()
    vi.stubGlobal('fetch', f)

    await usePrompts.getState().loadPromptSchema('proj', 'pr_lodging')
    await usePrompts.getState().loadPromptSchema('proj', 'pr_lodging')

    expect(callCount(f)).toBe(1)
  })

  it('caches a 404 as null so a deleted prompt is fetched once, not forever', async () => {
    const f = notFoundFetch()
    vi.stubGlobal('fetch', f)

    await usePrompts.getState().loadPromptSchema('proj', 'pr_gone')
    await usePrompts.getState().loadPromptSchema('proj', 'pr_gone')

    expect(usePrompts.getState().schemaById['proj']['pr_gone']).toBeNull()
    expect(callCount(f)).toBe(1)
  })

  it('keeps schemas of different prompts side by side', async () => {
    vi.stubGlobal('fetch', okFetch([{ name: 'a', type: 'string', description: '' }]))
    await usePrompts.getState().loadPromptSchema('proj', 'pr_a')
    vi.stubGlobal('fetch', okFetch([{ name: 'b', type: 'string', description: '' }]))
    await usePrompts.getState().loadPromptSchema('proj', 'pr_b')

    const byId = usePrompts.getState().schemaById['proj']
    expect(byId['pr_a']?.[0].name).toBe('a')
    expect(byId['pr_b']?.[0].name).toBe('b')
  })

  it('invalidate drops the per-prompt schema cache too', async () => {
    vi.stubGlobal('fetch', okFetch())
    await usePrompts.getState().loadPromptSchema('proj', 'pr_lodging')

    usePrompts.getState().invalidate('proj')

    expect(usePrompts.getState().schemaById['proj']).toBeUndefined()
  })
})
