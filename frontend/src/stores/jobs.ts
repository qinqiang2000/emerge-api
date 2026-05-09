import { create } from 'zustand'

import { jobEventsUrl, pauseJob, resumeJob, cancelJob, acceptCandidate } from '../lib/api'
import { streamSSE } from '../lib/sse'
import type { JobEvent, JobStatus, TurnEvent } from '../types/job'

interface State {
  status: JobStatus
  jobId: string | null
  projectId: string | null
  turns: TurnEvent[]
  bestTurn: TurnEvent | null
  endedReason: string | null
  err: string | null
  subscribe: (projectId: string, jobId: string) => Promise<void>
  pause: () => Promise<void>
  resume: () => Promise<void>
  cancel: () => Promise<void>
  accept: (turn: number) => Promise<void>
  reset: () => void
}

export const useJob = create<State>((set, get) => ({
  status: 'pending',
  jobId: null,
  projectId: null,
  turns: [],
  bestTurn: null,
  endedReason: null,
  err: null,
  reset: () => set({ status: 'pending', jobId: null, projectId: null, turns: [], bestTurn: null, endedReason: null, err: null }),
  subscribe: async (projectId, jobId) => {
    set({ status: 'running', jobId, projectId, turns: [], bestTurn: null, endedReason: null, err: null })
    try {
      for await (const ev of streamSSE(jobEventsUrl(projectId, jobId), { method: 'GET' })) {
        if (ev.event !== 'job_event') continue
        const data = ev.data as JobEvent
        if (data.type === 'turn') {
          set(s => {
            const turns = [...s.turns, data]
            const best = data.saved && (!s.bestTurn || data.macro_f1 > s.bestTurn.macro_f1) ? data : s.bestTurn
            return { turns, bestTurn: best }
          })
        } else if (data.type === 'paused') {
          set({ status: 'paused' })
        } else if (data.type === 'resumed') {
          set({ status: 'running' })
        } else if (data.type === 'ended') {
          const reason = data.reason ?? null
          const status: JobStatus = reason === 'cancelled' ? 'cancelled' : reason === 'error' ? 'error' : 'done'
          set({ status, endedReason: reason })
        }
      }
    } catch (e) {
      set({ err: String(e), status: 'error' })
    }
  },
  pause: async () => { const { jobId } = get(); if (jobId) await pauseJob(jobId) },
  resume: async () => { const { jobId } = get(); if (jobId) await resumeJob(jobId) },
  cancel: async () => { const { jobId } = get(); if (jobId) await cancelJob(jobId) },
  accept: async (turn) => {
    const { jobId, projectId } = get()
    if (!jobId || !projectId) return
    await acceptCandidate(projectId, jobId, turn)
  },
}))
