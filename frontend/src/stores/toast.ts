// frontend/src/stores/toast.ts
//
// Minimal global toast: a zustand queue + auto-expire. There was no
// notification primitive before — save() (and other one-shot actions) had no
// success feedback, only an inline red error banner. This fills that gap with
// the smallest thing that works: push a transient line, it self-dismisses
// after `ttl`ms, click to dismiss early.
import { create } from 'zustand'

export type ToastKind = 'ok' | 'err' | 'info'

export interface Toast {
  id: number
  kind: ToastKind
  text: string
}

interface ToastState {
  toasts: Toast[]
  push: (t: { kind: ToastKind; text: string; ttl?: number }) => void
  dismiss: (id: number) => void
}

let seq = 0
const DEFAULT_TTL = 3000

export const useToast = create<ToastState>((set, get) => ({
  toasts: [],
  push: ({ kind, text, ttl = DEFAULT_TTL }) => {
    const id = ++seq
    set((s) => ({ toasts: [...s.toasts, { id, kind, text }] }))
    if (ttl > 0) {
      // Best-effort auto-dismiss; clicking the toast can still remove it sooner.
      setTimeout(() => get().dismiss(id), ttl)
    }
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

/** Imperative helpers for non-React call sites (zustand actions, event
 *  handlers outside the render tree). Mirrors the `t()` imperative escape
 *  hatch in i18n. */
export const toast = {
  ok: (text: string) => useToast.getState().push({ kind: 'ok', text }),
  err: (text: string) => useToast.getState().push({ kind: 'err', text }),
  info: (text: string) => useToast.getState().push({ kind: 'info', text }),
}
