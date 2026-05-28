// Store contract for the project-level Bench leaderboard.
//
// Bench is a project-scoped read-only aggregator. The store keeps one
// `BenchResponse` per project slug — load is cache-first (a second call for
// the same slug must not re-fetch), mutation-aware (chat store invalidates
// when an experiment / prompt / model changes; T9 task wires that), and
// project-switch-aware (reset on logout / project-list reset path).
//
// Mirrors `useExperiments` and `useEval` invalidate semantics so chat
// store's `handleToolResult` can drop the cached row in one line without
// rewriting bench fetch logic.

import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../lib/api'
import type { BenchResponse } from '../../types/bench'
import { useBench } from '../bench'

function mkBench(overrides: Partial<BenchResponse> = {}): BenchResponse {
  return {
    prompts: [],
    models: [],
    fields: [],
    sample_filenames: [],
    headline: { best_score: null, best_prompt_id: null, best_model_id: null },
    rows: [],
    ...overrides,
  }
}

describe('useBench store', () => {
  beforeEach(() => {
    useBench.setState({ byProject: {}, loading: {} })
    vi.restoreAllMocks()
  })

  it('load() fetches once and caches the response under the slug', async () => {
    const payload = mkBench({ fields: ['vendor'] })
    const spy = vi.spyOn(api, 'getBench').mockResolvedValue(payload)

    await useBench.getState().load('proj-a')

    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy).toHaveBeenCalledWith('proj-a')
    expect(useBench.getState().byProject['proj-a']).toEqual(payload)
  })

  it('load() is cache-first: a second call for the same slug does NOT re-fetch', async () => {
    const payload = mkBench({ fields: ['vendor'] })
    const spy = vi.spyOn(api, 'getBench').mockResolvedValue(payload)

    await useBench.getState().load('proj-a')
    await useBench.getState().load('proj-a')

    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('invalidate(slug) drops the cache so the next load() re-fetches', async () => {
    const payload = mkBench({ fields: ['vendor'] })
    const spy = vi.spyOn(api, 'getBench').mockResolvedValue(payload)

    await useBench.getState().load('proj-a')
    useBench.getState().invalidate('proj-a')
    await useBench.getState().load('proj-a')

    expect(spy).toHaveBeenCalledTimes(2)
    // Cache repopulated after the second load.
    expect(useBench.getState().byProject['proj-a']).toEqual(payload)
  })

  it('invalidate(slug) only touches the named slug — other projects survive', async () => {
    const a = mkBench({ fields: ['vendor'] })
    const b = mkBench({ fields: ['total'] })
    vi.spyOn(api, 'getBench').mockImplementation(async (slug: string) =>
      slug === 'proj-a' ? a : b,
    )

    await useBench.getState().load('proj-a')
    await useBench.getState().load('proj-b')
    useBench.getState().invalidate('proj-a')

    expect('proj-a' in useBench.getState().byProject).toBe(false)
    expect(useBench.getState().byProject['proj-b']).toEqual(b)
  })

  it('reset() clears every slug so the next load() re-fetches all of them', async () => {
    const payload = mkBench()
    const spy = vi.spyOn(api, 'getBench').mockResolvedValue(payload)

    await useBench.getState().load('proj-a')
    await useBench.getState().load('proj-b')
    useBench.getState().reset()

    expect(useBench.getState().byProject).toEqual({})
    expect(useBench.getState().loading).toEqual({})

    await useBench.getState().load('proj-a')
    // 2 loads pre-reset + 1 load post-reset = 3.
    expect(spy).toHaveBeenCalledTimes(3)
  })

  it('concurrent load() for the same slug dedupes to a single fetch', async () => {
    let resolveFetch: ((p: BenchResponse) => void) | null = null
    const pending = new Promise<BenchResponse>((resolve) => {
      resolveFetch = resolve
    })
    const spy = vi.spyOn(api, 'getBench').mockReturnValue(pending)

    const p1 = useBench.getState().load('proj-a')
    const p2 = useBench.getState().load('proj-a')

    expect(spy).toHaveBeenCalledTimes(1)

    resolveFetch!(mkBench())
    await Promise.all([p1, p2])

    expect(spy).toHaveBeenCalledTimes(1)
    expect('proj-a' in useBench.getState().byProject).toBe(true)
  })
})
