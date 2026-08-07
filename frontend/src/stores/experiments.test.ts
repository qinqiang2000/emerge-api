// `useExperiments` is cache-first: once `list[projectId]` is populated nothing
// re-fetches it, so the ONLY way fresh rows arrive is `invalidate()` +
// `load()` — which is exactly what chat's `handleToolResult` fires on every
// create/archive/delete/run_experiment_eval result. That makes the in-flight
// dedupe path load-bearing: an invalidation that lands while a fetch is
// running must not be absorbed by that fetch's stale result, or the spine's
// `experiments/` list silently freezes at a partial snapshot until a reload.
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../lib/api'
import { useExperiments } from './experiments'
import type { ExperimentSummary } from '../types/review'

const PID = 'us-invoice'

function mkExp(id: string, over: Partial<ExperimentSummary> = {}): ExperimentSummary {
  return {
    experiment_id: id,
    label: `Baseline v1 × ${id}`,
    prompt_id: 'pr_baseline',
    prompt_version: 1,
    model_id: 'm_default',
    status: 'draft',
    created_at: '2026-07-07T02:00:00Z',
    score: null,
    ...over,
  }
}

const EX1 = mkExp('ex_0i4l6eb2de17')
const EX2 = mkExp('ex_5c0q7jie55in')

describe('useExperiments store', () => {
  beforeEach(() => {
    useExperiments.getState().reset()
    vi.restoreAllMocks()
  })

  it('load() fetches once and caches the rows under the project id', async () => {
    const spy = vi.spyOn(api, 'listExperiments').mockResolvedValue([EX1])

    await useExperiments.getState().load(PID)
    await useExperiments.getState().load(PID)

    expect(spy).toHaveBeenCalledTimes(1)
    expect(useExperiments.getState().list[PID]).toEqual([EX1])
  })

  it('dedupes concurrent load() calls into a single fetch', async () => {
    const spy = vi.spyOn(api, 'listExperiments').mockResolvedValue([EX1])

    await Promise.all([
      useExperiments.getState().load(PID),
      useExperiments.getState().load(PID),
    ])

    expect(spy).toHaveBeenCalledTimes(1)
    expect(useExperiments.getState().list[PID]).toEqual([EX1])
  })

  it('does not let an in-flight fetch re-cache rows an invalidate() already dropped', async () => {
    // The agent creates two experiments in one turn. The first tool result
    // starts fetch A; the second lands while A is still in flight, so its
    // invalidate() + load() must not resolve against A's pre-creation rows.
    let resolveA!: (rows: ExperimentSummary[]) => void
    const fetchA = new Promise<ExperimentSummary[]>((r) => { resolveA = r })
    const spy = vi.spyOn(api, 'listExperiments')
      .mockReturnValueOnce(fetchA)
      .mockResolvedValue([EX2, EX1])

    const first = useExperiments.getState().load(PID)

    useExperiments.getState().invalidate(PID)
    const second = useExperiments.getState().load(PID)

    resolveA([EX1])  // snapshot taken before the second experiment existed
    await Promise.all([first, second])

    expect(spy).toHaveBeenCalledTimes(2)
    expect(useExperiments.getState().list[PID]).toEqual([EX2, EX1])
  })
})
