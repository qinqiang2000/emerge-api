import { create } from 'zustand'

import { jobEventsUrl, pauseJob, resumeJob, cancelJob, acceptCandidate } from '../lib/api'
import { streamSSE } from '../lib/sse'
import type { JobEvent, JobStatus, TurnEvent } from '../types/job'

export interface JobSlice {
  jobId: string
  projectId: string
  status: JobStatus
  turns: TurnEvent[]
  bestTurn: TurnEvent | null
  endedReason: string | null
  err: string | null
  _abort: AbortController | null
}

interface State {
  byId: Record<string, JobSlice>
  slice: (jobId: string) => JobSlice | null
  subscribe: (projectId: string, jobId: string) => Promise<void>
  pause: (jobId: string) => Promise<void>
  resume: (jobId: string) => Promise<void>
  cancel: (jobId: string) => Promise<void>
  accept: (jobId: string, turn: number) => Promise<void>
  reset: () => void
}

const empty = (jobId: string, projectId: string): JobSlice => ({
  jobId,
  projectId,
  status: 'running',
  turns: [],
  bestTurn: null,
  endedReason: null,
  err: null,
  _abort: null,
})

function patch(set: any, jobId: string, patch: Partial<JobSlice>) {
  set((s: State) => {
    const cur = s.byId[jobId]
    if (!cur) return s
    return { byId: { ...s.byId, [jobId]: { ...cur, ...patch } } }
  })
}

export const useJob = create<State>((set, get) => ({
  byId: {},
  slice: (jobId) => get().byId[jobId] ?? null,
  reset: () => {
    for (const slice of Object.values(get().byId)) slice._abort?.abort()
    set({ byId: {} })
  },
  subscribe: async (projectId, jobId) => {
    // Abort any in-flight SSE for the same jobId before opening a new one.
    const prev = get().byId[jobId]
    prev?._abort?.abort()
    const ctrl = new AbortController()
    set((s) => ({ byId: { ...s.byId, [jobId]: { ...empty(jobId, projectId), _abort: ctrl } } }))
    try {
      for await (const ev of streamSSE(jobEventsUrl(projectId, jobId), { method: 'GET', signal: ctrl.signal })) {
        if (ev.event !== 'job_event') continue
        const data = ev.data as JobEvent
        if (data.type === 'turn') {
          set((s) => {
            const cur = s.byId[jobId]
            if (!cur) return s
            const turns = [...cur.turns, data]
            const best = data.saved && (!cur.bestTurn || data.macro_f1 > cur.bestTurn.macro_f1) ? data : cur.bestTurn
            return { byId: { ...s.byId, [jobId]: { ...cur, turns, bestTurn: best } } }
          })
        } else if (data.type === 'paused') {
          patch(set, jobId, { status: 'paused' })
        } else if (data.type === 'resumed') {
          patch(set, jobId, { status: 'running' })
        } else if (data.type === 'ended') {
          const reason = data.reason ?? null
          const status: JobStatus = reason === 'cancelled' ? 'cancelled' : reason === 'error' ? 'error' : 'done'
          patch(set, jobId, { status, endedReason: reason })
        }
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') return
      patch(set, jobId, { err: String(e), status: 'error' })
    }
  },
  pause: async (jobId) => { await pauseJob(jobId) },
  resume: async (jobId) => { await resumeJob(jobId) },
  cancel: async (jobId) => { await cancelJob(jobId) },
  accept: async (jobId, turn) => {
    const slice = get().byId[jobId]
    if (!slice) return
    await acceptCandidate(slice.projectId, jobId, turn)
  },
}))
