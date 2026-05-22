// frontend/src/stores/textlayer.ts
//
// Per (project, filename, page) cache for the PDF text-layer payload. The
// overlay is rendered as transparent <span> boxes positioned in %-of-page
// units on top of the rasterised page image, giving the user real
// rubberband-select + Cmd-C without the agent having to ferry text by hand.
//
// `ensure(...)` is fire-and-forget: idle → loading → ready | error, never
// re-fetches an existing key. Storage is intentionally lazy and persistent
// across doc switches — text layers are small JSON blobs and pagination
// inside one doc is the hot path.
import { create } from 'zustand'

import { fetchTextlayer, type TextlayerPayload } from '../lib/api'

export type TextlayerState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; payload: TextlayerPayload }
  | { kind: 'error'; message: string }

interface State {
  byKey: Record<string, TextlayerState>
  ensure: (projectId: string, filename: string, page: number) => void
  clearProject: (projectId: string) => void
}

function makeKey(projectId: string, filename: string, page: number): string {
  return `${projectId}::${filename}::${page}`
}

export const useTextlayer = create<State>((set, get) => ({
  byKey: {},
  ensure: (projectId, filename, page) => {
    if (!projectId || !filename || !page) return
    const key = makeKey(projectId, filename, page)
    const current = get().byKey[key]
    if (current && current.kind !== 'idle') return  // already loading / ready / error
    set((s) => ({ byKey: { ...s.byKey, [key]: { kind: 'loading' } } }))
    fetchTextlayer(projectId, filename, page).then(
      (payload) => set((s) => ({
        byKey: { ...s.byKey, [key]: { kind: 'ready', payload } },
      })),
      (err: unknown) => set((s) => ({
        byKey: { ...s.byKey, [key]: { kind: 'error', message: String(err) } },
      })),
    )
  },
  clearProject: (projectId) => {
    const prefix = `${projectId}::`
    set((s) => {
      const next: Record<string, TextlayerState> = {}
      for (const [k, v] of Object.entries(s.byKey)) {
        if (!k.startsWith(prefix)) next[k] = v
      }
      return { byKey: next }
    })
  },
}))
