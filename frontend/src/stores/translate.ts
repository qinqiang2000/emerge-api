// frontend/src/stores/translate.ts
//
// On-demand per-page translation cache + a single global on/off toggle.
//
// Two separate concerns share this store:
//   1. `mode`: user-facing global switch (toolbar button + `T` key). When
//      off, no fetches are issued and the ghost layer renders nothing.
//      When on, the consumer (PdfViewer's `PageOverlays`) calls
//      `ensure(...)` per page and the ghost paints whatever has
//      resolved. Cached payloads survive toggling off → on so retoggling
//      is instant.
//   2. `byKey`: per (project, filename, page) state machine
//      idle → loading → ready | error. Mirrors the textlayer store shape
//      so the two host components in PdfViewer read identically.
//
// Caching note: backend has its own sidecar cache keyed by (filename,
// page, lang, mode, model). `force: true` skips both caches end-to-end.
//
// Abort semantics: mirrors `useTextlayer` — when ensure() is called for a
// new (project, filename), abort every still-inflight fetch for the prior
// doc so the per-origin HTTP/1.1 connection pool doesn't get tied up by
// stale multi-second translate calls when the user fast-steps with ←/→.
import { create } from 'zustand'

import { translatePage, type TranslatePayload } from '../lib/api'

export type PageState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; payload: TranslatePayload }
  | { kind: 'error'; message: string }

// Two display modes:
// - `off`:   no translation; ghost layer not rendered, no fetches issued
// - `cover`: opaque larger ghost text covering the original raster, à la
//            Chrome / WeChat image translate. Original raster + textlayer
//            stay underneath, so original text is still selectable via
//            cmd+drag through the transparent textlayer at z=1.
export type Mode = 'off' | 'cover'

interface State {
  mode: Mode
  byKey: Record<string, PageState>
  setMode: (m: Mode) => void
  toggleMode: () => void
  ensure: (
    projectId: string,
    filename: string,
    page: number,
    opts?: { force?: boolean },
  ) => void
  /** Look-ahead warmer for the NEXT doc in the review queue (not yet opened).
   *  Self-gates on `mode` — only spends translator tokens when the reviewer
   *  has translation switched on, so we never pre-translate docs nobody will
   *  read in another language. Unlike `ensure` it does NOT run the doc-switch
   *  abort (prewarming a different doc must not abort the current doc's
   *  inflight fetches); when the user navigates there, `ensure` reuses the
   *  resolved entry. */
  prewarm: (projectId: string, filename: string, page: number) => void
  clearProject: (projectId: string) => void
}

function makeKey(projectId: string, filename: string, page: number): string {
  return `${projectId}::${filename}::${page}`
}

// Module-scoped abort bookkeeping; see textlayer.ts for the same pattern.
const inflight: Map<string, AbortController> = new Map()
let lastDocKey: string | null = null

export const useTranslate = create<State>((set, get) => ({
  mode: 'off',
  byKey: {},
  setMode: (m) => set({ mode: m }),
  toggleMode: () => set((s) => ({ mode: s.mode === 'off' ? 'cover' : 'off' })),
  ensure: (projectId, filename, page, opts) => {
    if (!projectId || !filename || !page) return
    // Hard gate: when translation is off, this is a no-op. Toolbar button
    // explicitly flips mode away from off, then loops ensure() over
    // loadedPages — never the other way around.
    if (get().mode === 'off') return

    // Doc-switch abort — same shape as useTextlayer.
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
    if (!opts?.force && current && (current.kind === 'loading' || current.kind === 'ready')) {
      return
    }

    // `force: true` re-fetches; if a previous attempt is still inflight
    // for this exact key, cancel it so we don't double-write the result.
    const prior = inflight.get(key)
    if (prior) {
      prior.abort()
      inflight.delete(key)
    }

    const ac = new AbortController()
    inflight.set(key, ac)
    set((s) => ({ byKey: { ...s.byKey, [key]: { kind: 'loading' } } }))
    translatePage(projectId, filename, page, { force: opts?.force, signal: ac.signal }).then(
      (payload) => {
        inflight.delete(key)
        if (ac.signal.aborted) return
        set((s) => ({ byKey: { ...s.byKey, [key]: { kind: 'ready', payload } } }))
      },
      (err: unknown) => {
        inflight.delete(key)
        if (ac.signal.aborted) return
        set((s) => ({
          byKey: {
            ...s.byKey,
            [key]: { kind: 'error', message: err instanceof Error ? err.message : String(err) },
          },
        }))
      },
    )
  },
  prewarm: (projectId, filename, page) => {
    if (!projectId || !filename || !page) return
    // Same hard gate as ensure: no translation work while mode is off.
    if (get().mode === 'off') return
    const key = makeKey(projectId, filename, page)
    const current = get().byKey[key]
    if (current && (current.kind === 'loading' || current.kind === 'ready')) return
    if (inflight.has(key)) return
    const ac = new AbortController()
    inflight.set(key, ac)
    set((s) => ({ byKey: { ...s.byKey, [key]: { kind: 'loading' } } }))
    translatePage(projectId, filename, page, { signal: ac.signal }).then(
      (payload) => {
        inflight.delete(key)
        if (ac.signal.aborted) return
        set((s) => ({ byKey: { ...s.byKey, [key]: { kind: 'ready', payload } } }))
      },
      (err: unknown) => {
        inflight.delete(key)
        if (ac.signal.aborted) return
        set((s) => ({
          byKey: {
            ...s.byKey,
            [key]: { kind: 'error', message: err instanceof Error ? err.message : String(err) },
          },
        }))
      },
    )
  },
  clearProject: (projectId) => {
    const prefix = `${projectId}::`
    const aborted: string[] = []
    for (const [k, ac] of inflight) {
      if (k.startsWith(prefix)) {
        ac.abort()
        aborted.push(k)
      }
    }
    for (const k of aborted) inflight.delete(k)
    set((s) => {
      const next: Record<string, PageState> = {}
      for (const [k, v] of Object.entries(s.byKey)) {
        if (!k.startsWith(prefix)) next[k] = v
      }
      return { byKey: next }
    })
  },
}))
