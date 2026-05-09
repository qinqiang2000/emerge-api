import { describe, it, expect, beforeEach, vi } from 'vitest'

import { useJob } from '../../src/stores/jobs'

vi.mock('../../src/lib/sse', () => ({
  streamSSE: async function* () {
    // never yields; resolves on abort
    await new Promise(() => {})
  },
}))

describe('useJob per-jobId isolation', () => {
  beforeEach(() => {
    useJob.getState().reset()
  })

  it('keeps separate slices for two different jobIds', async () => {
    void useJob.getState().subscribe('p_aaaaaaaaaaaa', 'job_a')
    void useJob.getState().subscribe('p_aaaaaaaaaaaa', 'job_b')
    const slice_a = useJob.getState().slice('job_a')
    const slice_b = useJob.getState().slice('job_b')
    expect(slice_a).not.toBe(slice_b)
    expect(slice_a?.jobId).toBe('job_a')
    expect(slice_b?.jobId).toBe('job_b')
  })

  it('aborts the previous SSE when re-subscribing the same jobId', async () => {
    void useJob.getState().subscribe('p_aaaaaaaaaaaa', 'job_a')
    const ctrl1 = useJob.getState().slice('job_a')?._abort
    expect(ctrl1).toBeDefined()
    void useJob.getState().subscribe('p_aaaaaaaaaaaa', 'job_a')
    expect(ctrl1?.signal.aborted).toBe(true)
  })
})
