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
  /** Fingerprint of the corrected-field set the user dismissed the banner for.
   *  Keyed by sorted field names (not counts) so re-correcting the same field
   *  won't re-nag, but correcting a NEW field changes the key and re-surfaces
   *  the banner. Cleared on project change via reset(). Session-only — not
   *  persisted, so a reload re-offers (the backlog is itself a live signal). */
  dismissedKey: string | null
  refresh: (slug: string) => Promise<void>
  /** Launch a focused tune on `targetFields`; returns the new job id (or null
   *  on failure). */
  startFocused: (slug: string, targetFields: string[]) => Promise<string | null>
  /** Hide the banner for the given corrected-field-set fingerprint. */
  dismiss: (key: string) => void
  reset: () => void
}

export const useReviewTune = create<State>((set) => ({
  signal: null,
  jobIds: [],
  dismissedKey: null,
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
  dismiss: (key) => set({ dismissedKey: key }),
  reset: () => set({ signal: null, jobIds: [], dismissedKey: null }),
}))
