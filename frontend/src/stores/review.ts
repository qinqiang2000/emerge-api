// frontend/src/stores/review.ts
import { create } from 'zustand'

import { getPrediction, getReviewed, saveReviewed } from '../lib/api'
import type { ReviewedPayload } from '../types/review'
import { useDocs } from './docs'

type FieldsValue = Record<string, unknown>

interface State {
  activeProjectId: string | null
  activeDocId: string | null
  page: number
  pageCount: number    // best-effort; defaulted to 1 until viewer probes
  loading: boolean
  saving: boolean
  err: string | null
  // Editing state: one entity for now (multi-entity is post-M2A)
  fields: FieldsValue
  open: (projectId: string, docId: string) => Promise<void>
  close: () => void
  setField: (name: string, value: unknown) => void
  goPage: (page: number) => void
  setPageCount: (n: number) => void
  save: () => Promise<void>
}

export const useReview = create<State>((set, get) => ({
  activeProjectId: null,
  activeDocId: null,
  page: 1,
  pageCount: 1,
  loading: false,
  saving: false,
  err: null,
  fields: {},
  open: async (projectId, docId) => {
    set({
      activeProjectId: projectId,
      activeDocId: docId,
      page: 1,
      pageCount: 1,
      loading: true,
      err: null,
      fields: {},
    })
    try {
      // Prefer reviewed payload (resume a partial review); fall back to draft.
      const reviewed = await getReviewed(projectId, docId)
      if (reviewed) {
        set({ fields: reviewed.entities[0] ?? {}, loading: false })
        return
      }
      const pred = await getPrediction(projectId, docId)
      set({ fields: pred?.entities[0] ?? {}, loading: false })
    } catch (e: unknown) {
      set({ err: String(e), loading: false })
    }
  },
  close: () => set({ activeProjectId: null, activeDocId: null, fields: {}, page: 1 }),
  setField: (name, value) => set((s) => ({ fields: { ...s.fields, [name]: value } })),
  goPage: (page) => set((s) => ({ page: Math.max(1, Math.min(s.pageCount, page)) })),
  setPageCount: (n) => set({ pageCount: Math.max(1, n) }),
  save: async () => {
    const { activeProjectId, activeDocId, fields } = get()
    if (!activeProjectId || !activeDocId) return
    set({ saving: true, err: null })
    try {
      const payload: ReviewedPayload = {
        entities: [fields],
        source: 'manual',
      }
      await saveReviewed(activeProjectId, activeDocId, payload)
      // refresh the doc-list status so the badge flips to "reviewed"
      void useDocs.getState().refresh(activeProjectId)
      set({ saving: false })
    } catch (e: unknown) {
      set({ err: String(e), saving: false })
    }
  },
}))
