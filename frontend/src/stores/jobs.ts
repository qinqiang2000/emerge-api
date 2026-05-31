import { create } from 'zustand'

import { jobEventsUrl, pauseJob, resumeJob, cancelJob, acceptCandidate } from '../lib/api'
import type { AcceptCandidateResult } from '../lib/api'
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
  /** True while an accept request is in flight (disables the accept button). */
  accepting: boolean
  /** Set on a successful accept — drives the inline "new variant adopted"
   *  confirmation on the card (Phase D). */
  accepted: AcceptCandidateResult | null
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
  accepting: false,
  accepted: null,
  _abort: null,
})

function patch(set: any, jobId: string, updates: Partial<JobSlice>) {
  set((s: State) => {
    const cur = s.byId[jobId]
    if (!cur) return s
    return { byId: { ...s.byId, [jobId]: { ...cur, ...updates } } }
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
            // M12.x — best-turn picker prefers `field_accuracy_macro`. Falls
            // back to the legacy `macro_f1` for pre-M12.x turn JSONLs (the
            // backend now emits both with the same accuracy value, so live
            // jobs always have the new field; the fallback only matters for
            // resumed jobs whose first turns predate this code).
            const datumScore = data.field_accuracy_macro ?? data.macro_f1
            const bestScore = cur.bestTurn
              ? (cur.bestTurn.field_accuracy_macro ?? cur.bestTurn.macro_f1)
              : -Infinity
            const best =
              data.saved && (!cur.bestTurn || datumScore > bestScore)
                ? data
                : cur.bestTurn
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
    if (!slice || slice.accepting) return
    patch(set, jobId, { accepting: true })
    try {
      const result = await acceptCandidate(slice.projectId, jobId, turn)
      patch(set, jobId, { accepting: false, accepted: result })
    } catch (e) {
      patch(set, jobId, { accepting: false, err: String(e) })
    }
  },
}))
