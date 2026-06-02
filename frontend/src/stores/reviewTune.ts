// frontend/src/stores/reviewTune.ts
//
// Review-scoped "tune signal" + focused-tune launcher. This is the non-chat
// entry point to the correction→tune loop: the review bar shows "field X
// corrected K times → optimize this field" from `signal`, and the button calls
// `startFocused` which kicks off an autoresearch job scoped to the corrected
// fields (target_fields). The resulting job ids surface as JobProgressCards in
// the review chat column — process still runs through the right-hand chat, the
// button just takes the user's unknown first step for them.
import { create } from 'zustand'

import { getTuneSignal, startJob } from '../lib/api'
import type { TuneSignal } from '../lib/api'

interface State {
  signal: TuneSignal | null
  /** Focused-tune jobs launched from the review bar this session. */
  jobIds: string[]
  refresh: (slug: string) => Promise<void>
  /** Launch a focused tune on `targetFields`; returns the new job id (or null
   *  on failure). */
  startFocused: (slug: string, targetFields: string[]) => Promise<string | null>
  reset: () => void
}

export const useReviewTune = create<State>((set) => ({
  signal: null,
  jobIds: [],
  refresh: async (slug) => {
    try {
      const s = await getTuneSignal(slug)
      set({ signal: s })
    } catch {
      // Best-effort: a failed signal fetch just hides the affordance.
    }
  },
  startFocused: async (slug, targetFields) => {
    try {
      const { job_id } = await startJob(slug, { target_fields: targetFields })
      set((st) => ({ jobIds: [...st.jobIds, job_id] }))
      return job_id
    } catch {
      return null
    }
  },
  reset: () => set({ signal: null, jobIds: [] }),
}))
