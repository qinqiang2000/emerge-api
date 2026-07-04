// Review-board data cache (`useReviewBoard`) — per-slug, cache-first, a much
// simpler cousin of `useBoard`. `load(slug)` does the single `render_review-
// board` HTTP twin fetch and stores the whole payload (docs + self-contained
// per-doc HTML + tally + model label).
//
// Selector discipline: components must select plain slices
// (`s.byProject[slug]`) — never `?? []` / `.filter` / object literals inside a
// selector (repo trap `project_zustand_selector_fresh_ref_loop`). Coalesce in
// a component useMemo instead.

import { create } from 'zustand'

import { getReviewBoard, type ReviewBoardPayload } from '../lib/api'

interface State {
  byProject: Record<string, ReviewBoardPayload>
  loading: Record<string, boolean>
  errors: Record<string, string>
  load: (slug: string) => Promise<void>
  invalidate: (slug: string) => void
  reset: () => void
}

export const useReviewBoard = create<State>((set, get) => ({
  byProject: {},
  loading: {},
  errors: {},

  reset: () => set({ byProject: {}, loading: {}, errors: {} }),

  invalidate: (slug) =>
    set((s) => {
      const byProject = { ...s.byProject }; delete byProject[slug]
      const errors = { ...s.errors }; delete errors[slug]
      return { byProject, errors }
    }),

  load: async (slug) => {
    if (slug in get().byProject) return // cached — skip fetch
    if (get().loading[slug]) {
      // dedupe in-flight: park on the subscribe and resolve when the slug
      // lands in byProject (mirrors useBoard).
      return new Promise<void>((resolve) => {
        const unsub = useReviewBoard.subscribe((s) => {
          if (slug in s.byProject || !s.loading[slug]) {
            unsub(); resolve()
          }
        })
      })
    }
    set((s) => {
      const errors = { ...s.errors }; delete errors[slug]
      return { loading: { ...s.loading, [slug]: true }, errors }
    })
    try {
      const payload = await getReviewBoard(slug)
      set((s) => ({ byProject: { ...s.byProject, [slug]: payload } }))
    } catch (e) {
      set((s) => ({
        errors: { ...s.errors, [slug]: e instanceof Error ? e.message : String(e) },
      }))
    } finally {
      set((s) => {
        const next = { ...s.loading }; delete next[slug]
        return { loading: next }
      })
    }
  },
}))
