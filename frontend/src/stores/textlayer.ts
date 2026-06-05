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
//
// Abort semantics: the backend now runs a Gemini vision OCR enrichment on
// every page (5e02a42), which makes each /textlayer fetch take seconds.
// When the user rapidly steps through docs with ←/→, prior-doc fetches
// would otherwise saturate the browser's per-origin HTTP/1.1 connection
// pool and queue the new doc's /pages/<n>.png raster behind them — visible
// as a stuck stale image. We track an AbortController per inflight key and
// abort all prior-doc fetches the first time `ensure` is called for a new
// (project, filename). Aborted keys reset to `idle` so a later remount
// (e.g. user steps back) refetches cleanly.
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
  /** Look-ahead warmer for a doc the user has NOT opened yet (the next entry
   *  in the review queue). Same fetch as `ensure`, but deliberately does NOT
   *  touch the `lastDocKey` doc-switch abort bookkeeping — prewarming the next
   *  doc must not look like a doc switch (which would abort the current doc's
   *  inflight fetches). When the user actually navigates there, `ensure` sees
   *  the `loading`/`ready` entry and reuses it instead of refetching. */
  prewarm: (projectId: string, filename: string, page: number) => void
  clearProject: (projectId: string) => void
}

function makeKey(projectId: string, filename: string, page: number): string {
  return `${projectId}::${filename}::${page}`
}

// Module-scoped so the abort bookkeeping survives across re-renders without
// adding nullable React state. Keys mirror `byKey`.
const inflight: Map<string, AbortController> = new Map()
let lastDocKey: string | null = null

export const useTextlayer = create<State>((set, get) => ({
  byKey: {},
  ensure: (projectId, filename, page) => {
    if (!projectId || !filename || !page) return

    // Doc switch — abort every still-inflight fetch for the prior doc so
    // the browser HTTP pool frees up immediately for the new doc's page
    // raster + textlayer. Reset their byKey entries to `idle` so a future
    // remount for the same key (user steps back) refetches.
    const docKey = `${projectId}::${filename}`
    if (lastDocKey && lastDocKey !== docKey) {
      const prefix = `${lastDocKey}::`
      const aborted: string[] = []
      for (const [k, ac] of inflight) {
        if (k.startsWith(prefix)) {
          ac.abort()
          aborted.push(k)
        }
      }
      for (const k of aborted) inflight.delete(k)
      if (aborted.length > 0) {
        set((s) => {
          const next = { ...s.byKey }
          for (const k of aborted) {
            if (next[k]?.kind === 'loading') next[k] = { kind: 'idle' }
          }
          return { byKey: next }
        })
      }
    }
    lastDocKey = docKey

    const key = makeKey(projectId, filename, page)
    const current = get().byKey[key]
    if (current && current.kind !== 'idle') return  // already loading / ready / error

    const ac = new AbortController()
    inflight.set(key, ac)
    set((s) => ({ byKey: { ...s.byKey, [key]: { kind: 'loading' } } }))
    fetchTextlayer(projectId, filename, page, ac.signal).then(
      (payload) => {
        inflight.delete(key)
        if (ac.signal.aborted) return
        set((s) => ({ byKey: { ...s.byKey, [key]: { kind: 'ready', payload } } }))
      },
      (err: unknown) => {
        inflight.delete(key)
        if (ac.signal.aborted) return
        set((s) => ({
          byKey: { ...s.byKey, [key]: { kind: 'error', message: String(err) } },
        }))
      },
    )
  },
  prewarm: (projectId, filename, page) => {
    if (!projectId || !filename || !page) return
    const key = makeKey(projectId, filename, page)
    const current = get().byKey[key]
    if (current && current.kind !== 'idle') return  // already loading / ready / error
    if (inflight.has(key)) return
    const ac = new AbortController()
    inflight.set(key, ac)
    set((s) => ({ byKey: { ...s.byKey, [key]: { kind: 'loading' } } }))
    fetchTextlayer(projectId, filename, page, ac.signal).then(
      (payload) => {
        inflight.delete(key)
        if (ac.signal.aborted) return
        set((s) => ({ byKey: { ...s.byKey, [key]: { kind: 'ready', payload } } }))
      },
      (err: unknown) => {
        inflight.delete(key)
        if (ac.signal.aborted) return
        set((s) => ({
          byKey: { ...s.byKey, [key]: { kind: 'error', message: String(err) } },
        }))
      },
    )
  },
  clearProject: (projectId) => {
    const prefix = `${projectId}::`
    // Also abort any still-inflight requests under this project — caller
    // typically invokes this on project teardown.
    const aborted: string[] = []
    for (const [k, ac] of inflight) {
      if (k.startsWith(prefix)) {
        ac.abort()
        aborted.push(k)
      }
    }
    for (const k of aborted) inflight.delete(k)
    set((s) => {
      const next: Record<string, TextlayerState> = {}
      for (const [k, v] of Object.entries(s.byKey)) {
        if (!k.startsWith(prefix)) next[k] = v
      }
      return { byKey: next }
    })
  },
}))
