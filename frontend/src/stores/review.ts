// frontend/src/stores/review.ts
import { create } from 'zustand'

import {
  getExperimentPrediction,
  getPending,
  getPrediction,
  getReviewed,
  runExperimentPrediction,
  saveReviewed,
} from '../lib/api'
import type { ExperimentPredictionPayload, ReviewedPayload } from '../types/review'
import { useDocs } from './docs'

type FieldsValue = Record<string, unknown>

interface State {
  activeProjectId: string | null
  /** On-disk filename of the open doc — the only doc handle now. */
  activeFilename: string | null
  page: number
  pageCount: number    // best-effort; defaulted to 1 until viewer probes
  loading: boolean
  saving: boolean
  err: string | null
  entities: FieldsValue[]
  evidence: Record<string, number | null>[] | null
  notes: Record<string, string>
  /** Path of the field row currently highlighted in the FieldEditor — hoisted
   *  out of FieldEditor local state so the review chat column can render a
   *  contextual chip ("inv-042.pdf · buyer_name = …") in its header. */
  activeField: string | null
  /** Which entity tab the user is viewing in multi-entity docs. Lives in the
   *  store so the chat column can reach it for review_context. */
  activeEntityIdx: number
  // ── pro-labeler state ────────────────────────────────────────────
  /** True when the form is prefilled from `reviewed/_pending/{filename}.json`
   *  (Pro-labeler draft) and no human-verified `reviewed/` file exists yet.
   *  Flips false on save (`save_reviewed` deletes the matching pending file
   *  on the backend; we mirror that locally). */
  isPending: boolean
  /** Model that produced the pending draft. Shown in the banner copy. */
  labelerModel: string | null
  // ── experiment-tab state ─────────────────────────────────────────
  activeTabKey: 'active' | string  // 'active' or experiment_id
  predictionsByExp: Record<string, ExperimentPredictionPayload | null>
  // ── methods ──────────────────────────────────────────────────────
  open: (projectId: string, filename: string) => Promise<void>
  close: () => void
  setField: (entityIdx: number, name: string, value: unknown) => void
  setNote: (name: string, note: string) => void
  /** Toggle-set: passing the currently-active path clears selection. */
  setActiveField: (path: string | null) => void
  setActiveEntityIdx: (idx: number) => void
  addEntity: () => void
  removeEntity: (idx: number) => void
  goPage: (page: number) => void
  setPageCount: (n: number) => void
  save: () => Promise<void>
  setActiveTab: (key: 'active' | string) => void
  loadExperimentPrediction: (experimentId: string) => Promise<void>
  runExperimentPrediction: (experimentId: string) => Promise<void>
  // ── adopt-from-prediction (label-studio-style) ───────────────────
  adoptPrediction: (
    entities: FieldsValue[],
    evidence?: Record<string, number | null>[] | null,
  ) => void
  adoptPredictionField: (
    entityIdx: number,
    name: string,
    value: unknown,
    evidencePage?: number | null,
  ) => void
}

export const useReview = create<State>((set, get) => ({
  activeProjectId: null,
  activeFilename: null,
  page: 1,
  pageCount: 1,
  loading: false,
  saving: false,
  err: null,
  entities: [],
  evidence: null,
  notes: {},
  activeField: null,
  activeEntityIdx: 0,
  activeTabKey: 'active',
  predictionsByExp: {},
  isPending: false,
  labelerModel: null,
  open: async (projectId, filename) => {
    set({
      activeProjectId: projectId,
      activeFilename: filename,
      page: 1,
      pageCount: 1,
      loading: true,
      err: null,
      entities: [],
      evidence: null,
      notes: {},
      activeField: null,
      activeEntityIdx: 0,
      isPending: false,
      labelerModel: null,
      // ── tab state reset ──
      activeTabKey: 'active',
      predictionsByExp: {},
    })
    try {
      // Layered fetch: reviewed (human-verified) > pending (Pro-labeler draft)
      // > prediction (Flash draft). Reviewed and prediction can run in
      // parallel; pending is only queried when reviewed is absent, because
      // saving reviewed makes pending obsolete (the backend cleans it inside
      // the same project_lock).
      const [reviewed, pred] = await Promise.all([
        getReviewed(projectId, filename),
        getPrediction(projectId, filename),
      ])
      const pending = reviewed ? null : await getPending(projectId, filename)

      const reviewedEnts = reviewed?.entities
      const pendingEnts = pending?.entities
      const predEnts = pred?.entities
      const base = reviewedEnts ?? pendingEnts ?? predEnts ?? [{}]
      const entities = base.map((src, i) => {
        const predEnt = (predEnts?.[i] ?? {}) as Record<string, unknown>
        const baseEnt = (src ?? {}) as Record<string, unknown>
        // When reviewed or pending entities are the source of truth, layer
        // prediction underneath so newly-added schema fields the user hasn't
        // touched still surface a draft value.
        return reviewedEnts || pendingEnts
          ? { ...predEnt, ...baseEnt }
          : baseEnt
      })
      set({
        entities,
        evidence: reviewed?._evidence ?? pending?._evidence ?? pred?._evidence ?? null,
        notes: reviewed?._notes ?? {},
        isPending: !reviewed && !!pending,
        labelerModel: !reviewed && pending ? pending.labeler_model ?? null : null,
        loading: false,
      })
    } catch (e: unknown) {
      set({ err: String(e), loading: false })
    }
  },
  close: () => set({ activeProjectId: null, activeFilename: null, entities: [], evidence: null, notes: {}, page: 1, activeField: null, activeEntityIdx: 0, isPending: false, labelerModel: null }),
  setField: (entityIdx, name, value) => set((s) => {
    const next = s.entities.slice()
    const cur = next[entityIdx] ?? {}
    next[entityIdx] = { ...cur, [name]: value }
    return { entities: next }
  }),
  setNote: (name, note) => set((s) => ({ notes: { ...s.notes, [name]: note } })),
  setActiveField: (path) => set((s) => ({
    // Toggle semantics — clicking the row that's already active deselects it.
    activeField: path !== null && s.activeField === path ? null : path,
  })),
  setActiveEntityIdx: (idx) => set({ activeEntityIdx: Math.max(0, idx) }),
  addEntity: () => set((s) => ({ entities: [...s.entities, {}] })),
  removeEntity: (idx) => set((s) => ({
    entities: s.entities.length > 1 ? s.entities.filter((_, i) => i !== idx) : s.entities,
  })),
  goPage: (page) => set((s) => ({ page: Math.max(1, Math.min(s.pageCount, page)) })),
  setPageCount: (n) => set({ pageCount: Math.max(1, n) }),
  save: async () => {
    const { activeProjectId, activeFilename, entities, evidence, notes } = get()
    if (!activeProjectId || !activeFilename) return
    set({ saving: true, err: null })
    try {
      const payload: ReviewedPayload = {
        entities,
        source: 'manual',
        ...(evidence ? { _evidence: evidence } : {}),
        ...(Object.keys(notes).length > 0 ? { _notes: notes } : {}),
      }
      await saveReviewed(activeProjectId, activeFilename, payload)
      // refresh the doc-list status so the badge flips to "reviewed"
      void useDocs.getState().refresh(activeProjectId)
      // Backend deleted the matching pending file inside the same project_lock
      // as the reviewed write — mirror that here so the banner disappears
      // without waiting for a re-open of the doc.
      set({ saving: false, isPending: false, labelerModel: null })
    } catch (e: unknown) {
      set({ err: String(e), saving: false })
    }
  },

  setActiveTab: (key) => set({ activeTabKey: key }),

  loadExperimentPrediction: async (experimentId) => {
    const { activeProjectId, activeFilename, predictionsByExp } = get()
    if (!activeProjectId || !activeFilename) return
    if (experimentId in predictionsByExp) return  // already attempted (success or 404)
    const payload = await getExperimentPrediction(activeProjectId, experimentId, activeFilename)
    set((s) => ({ predictionsByExp: { ...s.predictionsByExp, [experimentId]: payload } }))
  },

  runExperimentPrediction: async (experimentId) => {
    const { activeProjectId, activeFilename } = get()
    if (!activeProjectId || !activeFilename) return
    const payload = await runExperimentPrediction(activeProjectId, experimentId, activeFilename)
    set((s) => ({ predictionsByExp: { ...s.predictionsByExp, [experimentId]: payload } }))
  },

  adoptPrediction: (entities, evidence) => set({
    entities: entities.map((e) => ({ ...(e ?? {}) })),
    evidence: evidence ? evidence.map((e) => ({ ...(e ?? {}) })) : null,
    // Switch to the editable annotation tab so the user sees the result.
    activeTabKey: 'active',
  }),

  adoptPredictionField: (entityIdx, name, value, evidencePage) => set((s) => {
    const nextEntities = s.entities.slice()
    while (nextEntities.length <= entityIdx) nextEntities.push({})
    nextEntities[entityIdx] = { ...nextEntities[entityIdx], [name]: value }

    let nextEvidence = s.evidence
    if (evidencePage !== undefined) {
      const base = (s.evidence ?? []).slice() as Record<string, number | null>[]
      while (base.length <= entityIdx) base.push({})
      base[entityIdx] = { ...base[entityIdx], [name]: evidencePage }
      nextEvidence = base
    }
    return { entities: nextEntities, evidence: nextEvidence }
  }),
}))
