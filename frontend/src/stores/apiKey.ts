import { create } from 'zustand'

import type { RevealPayload } from '../types/publish'

interface State {
  current: RevealPayload | null
  setReveal: (payload: RevealPayload) => void
  clear: () => void
}

export const useApiKey = create<State>((set) => ({
  current: null,
  setReveal: (payload) => set({ current: payload }),
  clear: () => set({ current: null }),
}))
