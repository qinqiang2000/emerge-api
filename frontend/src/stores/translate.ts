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
import { create } from 'zustand'

import { translatePage, type TranslatePayload } from '../lib/api'

export type PageState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; payload: TranslatePayload }
  | { kind: 'error'; message: string }

// Three display modes:
// - `off`:    no translation; ghost layer not rendered, no fetches issued
// - `subtle`: tiny low-alpha ghost text, original is the visual primary
//             (the "navigator" — scan to decide what matters)
// - `cover`:  opaque larger ghost text covering the original raster, à la
//             Chrome / WeChat image translate (the "reading" mode)
// `on` is kept as a legacy alias of `subtle` so older keymap callers that
// say `setMode('on')` still resolve to a translated state.
export type Mode = 'off' | 'subtle' | 'cover'
export type ModeInput = Mode | 'on'

interface State {
  mode: Mode
  byKey: Record<string, PageState>
  setMode: (m: ModeInput) => void
  toggleMode: () => void
  ensure: (
    projectId: string,
    filename: string,
    page: number,
    opts?: { force?: boolean },
  ) => void
  clearProject: (projectId: string) => void
}

function makeKey(projectId: string, filename: string, page: number): string {
  return `${projectId}::${filename}::${page}`
}

function normalizeMode(m: ModeInput): Mode {
  return m === 'on' ? 'subtle' : m
}

// T-key + toolbar cycle order: off → cover → subtle → off.
// Cover comes first because it's the more useful state for most review
// flows — readable Chinese over the original raster. Subtle (small grey
// navigator annotation) is reachable on the second tap for users who
// already understand the original and just want a sparse cue.
function nextMode(m: Mode): Mode {
  if (m === 'off') return 'cover'
  if (m === 'cover') return 'subtle'
  return 'off'
}

export const useTranslate = create<State>((set, get) => ({
  mode: 'off',
  byKey: {},
  setMode: (m) => set({ mode: normalizeMode(m) }),
  toggleMode: () => set((s) => ({ mode: nextMode(s.mode) })),
  ensure: (projectId, filename, page, opts) => {
    if (!projectId || !filename || !page) return
    // Hard gate: when translation is off, this is a no-op. Toolbar button
    // explicitly flips mode away from off, then loops ensure() over
    // loadedPages — never the other way around. `subtle` and `cover` both
    // count as "on" for fetching purposes.
    if (get().mode === 'off') return
    const key = makeKey(projectId, filename, page)
    const current = get().byKey[key]
    if (!opts?.force && current && (current.kind === 'loading' || current.kind === 'ready')) {
      return
    }
    set((s) => ({ byKey: { ...s.byKey, [key]: { kind: 'loading' } } }))
    translatePage(projectId, filename, page, { force: opts?.force }).then(
      (payload) => set((s) => ({
        byKey: { ...s.byKey, [key]: { kind: 'ready', payload } },
      })),
      (err: unknown) => set((s) => ({
        byKey: {
          ...s.byKey,
          [key]: { kind: 'error', message: err instanceof Error ? err.message : String(err) },
        },
      })),
    )
  },
  clearProject: (projectId) => {
    const prefix = `${projectId}::`
    set((s) => {
      const next: Record<string, PageState> = {}
      for (const [k, v] of Object.entries(s.byKey)) {
        if (!k.startsWith(prefix)) next[k] = v
      }
      return { byKey: next }
    })
  },
}))
