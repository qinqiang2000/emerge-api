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
import type { ExperimentPredictionPayload, ReviewedPayload, RunStamp } from '../types/review'
import { toast } from './toast'
import { t } from '../i18n'
import { useDocs } from './docs'
import { useProjects } from './projects'
import { useLocate } from './locate'
import type { EvidenceValue } from '../lib/locate'

type FieldsValue = Record<string, unknown>

/** Per-field before/after the human changed this save pass. Keyed by
 *  top-level field name; the backend proposer reads it as
 *  `_corrections[fieldName]` on entity[0]. */
type Corrections = Record<string, { before: unknown; after: unknown }>

/** Deep copy entity rows so the loaded baseline can't be mutated by later
 *  setField calls. Values are JSON-serializable (extraction output), so
 *  structuredClone-equivalent via JSON round-trip is sufficient and stable. */
function deepCopyEntities(entities: FieldsValue[]): FieldsValue[] {
  return entities.map((e) => JSON.parse(JSON.stringify(e ?? {})) as FieldsValue)
}

/** Stable deep-equality for JSON-serializable values. */
function deepEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

/** Diff loaded baseline vs final entities, keyed by top-level field name.
 *  The backend keys corrections by field name on the representative entity[0],
 *  so we collapse multi-entity docs to a single before/after per field name:
 *  use entity[0]'s values when present, otherwise the first entity whose value
 *  changed. Only changed fields are emitted. */
function diffCorrections(baseline: FieldsValue[], final: FieldsValue[]): Corrections {
  const out: Corrections = {}
  // Union of all top-level field names seen across both snapshots, anchored on
  // entity[0] first so the representative entity's keys lead.
  const names = new Set<string>()
  for (const ent of [final[0], baseline[0], ...final, ...baseline]) {
    for (const k of Object.keys(ent ?? {})) names.add(k)
  }
  for (const name of names) {
    const beforeRep = (baseline[0] ?? {})[name]
    const afterRep = (final[0] ?? {})[name]
    if (!deepEqual(beforeRep, afterRep)) {
      out[name] = { before: beforeRep, after: afterRep }
      continue
    }
    // entity[0] unchanged for this field — fall back to the first entity whose
    // value moved, so corrections in multi-entity docs aren't silently dropped.
    const n = Math.max(baseline.length, final.length)
    for (let i = 1; i < n; i++) {
      const before = (baseline[i] ?? {})[name]
      const after = (final[i] ?? {})[name]
      if (!deepEqual(before, after)) {
        out[name] = { before, after }
        break
      }
    }
  }
  return out
}

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
  /** Deep-copied snapshot of the entities as first loaded into the editable
   *  annotation tab — the "before" the human started correcting. save() diffs
   *  the final entities against this to emit `_corrections` (Phase B of the
   *  review-correction → prompt-tune loop). Reset on doc open and re-anchored
   *  to the just-saved entities after each successful save. */
  baselineEntities: FieldsValue[]
  evidence: Record<string, EvidenceValue>[] | null
  notes: Record<string, string>
  /** Per-field before/after of what was corrected on THIS doc (the open doc's
   *  persisted `_corrections`, from the last save pass). Drives the "corrected"
   *  badge on field rows so a human can see at a glance which fields they fixed.
   *  Reset on open, re-anchored after each save. */
  corrections: Record<string, { before: unknown; after: unknown }>
  /** One-shot focus signal: when the tune banner's before→after entry is
   *  clicked, we open the source doc and stash the field here so FieldEditor can
   *  select + scroll it into view once the entities finish loading, then clear
   *  it via consumePendingFocus(). null when nothing is pending. */
  pendingFocusField: string | null
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
  // ── M14: run envelopes from draft + pending blobs ────────────────
  /** `_run` from the active-baseline draft (`predictions/_draft/{f}.json`).
   *  null when the blob doesn't exist or pre-dates M14. Drives the
   *  "baseline" tab in ExperimentTabStrip and seeds the readonly view when
   *  the user clicks it. */
  draftRun: RunStamp | null
  /** Cached draft entities/evidence for the `_draft` tab's readonly view —
   *  surfaced alongside `draftRun` so the overlay can switch view without
   *  re-fetching. */
  draftEntities: FieldsValue[] | null
  draftEvidence: Record<string, EvidenceValue>[] | null
  /** `_run` from the pre-label pending blob; powers the "pre-label" tab. */
  pendingRun: RunStamp | null
  /** Cached pending entities/evidence for the `_pending` tab's readonly view. */
  pendingEntities: FieldsValue[] | null
  pendingEvidence: Record<string, EvidenceValue>[] | null
  // ── experiment-tab state ─────────────────────────────────────────
  activeTabKey: 'active' | '_draft' | '_pending' | string  // 'active' / '_draft' / '_pending' / experiment_id
  predictionsByExp: Record<string, ExperimentPredictionPayload | null>
  // ── methods ──────────────────────────────────────────────────────
  open: (projectId: string, filename: string) => Promise<void>
  /** Open the doc behind a correction and queue its field for focus + scroll.
   *  No-op re-open when the doc is already active. */
  navigateToCorrection: (projectId: string, filename: string, field: string) => Promise<void>
  /** FieldEditor calls this after it has consumed `pendingFocusField`. */
  consumePendingFocus: () => void
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
  setActiveTab: (key: 'active' | '_draft' | '_pending' | string) => void
  loadExperimentPrediction: (experimentId: string) => Promise<void>
  runExperimentPrediction: (experimentId: string) => Promise<void>
  // ── adopt-from-prediction (label-studio-style) ───────────────────
  adoptPrediction: (
    entities: FieldsValue[],
    evidence?: Record<string, EvidenceValue>[] | null,
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
  baselineEntities: [],
  evidence: null,
  notes: {},
  corrections: {},
  pendingFocusField: null,
  activeField: null,
  activeEntityIdx: 0,
  activeTabKey: 'active',
  predictionsByExp: {},
  isPending: false,
  labelerModel: null,
  draftRun: null,
  draftEntities: null,
  draftEvidence: null,
  pendingRun: null,
  pendingEntities: null,
  pendingEvidence: null,
  open: async (projectId, filename) => {
    // Re-anchor the spine to the review's project. Covers the case where the
    // user clicked another project in the spine after entering review: prev /
    // next here snaps selectedSlug (and the URL) back to the doc being
    // reviewed, restoring the docs/ row highlight that gates on
    // `reviewActiveProjectId === selectedSlug` in FSSpine.
    if (useProjects.getState().selectedSlug !== projectId) {
      useProjects.getState().select(projectId)
    }
    // Source-grounding cache + focus are doc-scoped — clear them alongside the
    // tab/entity state reset below so a freshly-opened doc starts clean.
    useLocate.getState().reset()
    set({
      activeProjectId: projectId,
      activeFilename: filename,
      page: 1,
      pageCount: 1,
      loading: true,
      err: null,
      entities: [],
      baselineEntities: [],
      evidence: null,
      notes: {},
      corrections: {},
      pendingFocusField: null,
      activeField: null,
      activeEntityIdx: 0,
      isPending: false,
      labelerModel: null,
      // ── tab state reset ──
      activeTabKey: 'active',
      predictionsByExp: {},
      draftRun: null,
      draftEntities: null,
      draftEvidence: null,
      pendingRun: null,
      pendingEntities: null,
      pendingEvidence: null,
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
        // Snapshot the loaded entities as the per-doc "before" baseline so
        // save() can diff out which top-level fields the human actually
        // changed (Phase B → `_corrections`). Deep copy so later setField
        // mutations don't bleed into it.
        baselineEntities: deepCopyEntities(entities),
        evidence: (reviewed?._evidence ?? pending?._evidence ?? pred?._evidence ?? null) as Record<string, EvidenceValue>[] | null,
        notes: reviewed?._notes ?? {},
        corrections: reviewed?._corrections ?? {},
        isPending: !reviewed && !!pending,
        labelerModel: !reviewed && pending ? pending.labeler_model ?? null : null,
        // M14 — cache the draft/pending payloads (entities + evidence + _run)
        // so the tabstrip can offer them as readonly tabs without re-fetching.
        draftRun: pred?._run ?? null,
        draftEntities: pred?.entities ?? null,
        draftEvidence: (pred?._evidence ?? null) as Record<string, EvidenceValue>[] | null,
        pendingRun: pending?._run ?? null,
        pendingEntities: pending?.entities ?? null,
        pendingEvidence: (pending?._evidence ?? null) as Record<string, EvidenceValue>[] | null,
        loading: false,
      })
    } catch (e: unknown) {
      set({ err: String(e), loading: false })
    }
  },
  navigateToCorrection: async (projectId, filename, field) => {
    const cur = get()
    if (cur.activeProjectId !== projectId || cur.activeFilename !== filename) {
      await get().open(projectId, filename)
    }
    // Stash AFTER open (open() resets pendingFocusField via its top set). The
    // FieldEditor effect picks this up once entities are present.
    set({ pendingFocusField: field })
  },
  consumePendingFocus: () => set({ pendingFocusField: null }),
  close: () => set({ activeProjectId: null, activeFilename: null, entities: [], baselineEntities: [], evidence: null, notes: {}, corrections: {}, pendingFocusField: null, page: 1, activeField: null, activeEntityIdx: 0, isPending: false, labelerModel: null, draftRun: null, draftEntities: null, draftEvidence: null, pendingRun: null, pendingEntities: null, pendingEvidence: null }),
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
    const { activeProjectId, activeFilename, entities, baselineEntities, evidence, notes } = get()
    if (!activeProjectId || !activeFilename) return
    set({ saving: true, err: null })
    try {
      // Diff the loaded baseline against the final entities to surface which
      // top-level fields the human actually corrected this pass (Phase B).
      // Only non-empty diffs add `_corrections`; the backend body forbids
      // unknown keys, so omit it entirely when nothing changed.
      const corrections = diffCorrections(baselineEntities, entities)
      const payload: ReviewedPayload = {
        entities,
        source: 'manual',
        ...(evidence ? { _evidence: evidence } : {}),
        ...(Object.keys(notes).length > 0 ? { _notes: notes } : {}),
        ...(Object.keys(corrections).length > 0 ? { _corrections: corrections } : {}),
      }
      await saveReviewed(activeProjectId, activeFilename, payload)
      // refresh the doc-list status so the badge flips to "reviewed"
      void useDocs.getState().refresh(activeProjectId)
      // Backend deleted the matching pending file inside the same project_lock
      // as the reviewed write — mirror that here so the banner disappears
      // without waiting for a re-open of the doc. Re-anchor the baseline to the
      // just-saved entities so a second save in this session diffs from here,
      // not from the original load.
      set({
        saving: false,
        isPending: false,
        labelerModel: null,
        baselineEntities: deepCopyEntities(entities),
        // Mirror the backend: save_reviewed overwrites `_corrections` with just
        // this pass, so the corrected-field badges track the latest save.
        corrections,
      })
      toast.ok(t('review.save.ok'))
    } catch (e: unknown) {
      // Save failures surface via toast (transient, non-blocking). The inline
      // `err` banner in ReviewOverlay is reserved for load failures so a save
      // error doesn't paint both a banner and a toast.
      set({ saving: false })
      toast.err(t('review.save.fail', { err: String(e) }))
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
      const base = (s.evidence ?? []).slice() as Record<string, EvidenceValue>[]
      while (base.length <= entityIdx) base.push({})
      base[entityIdx] = { ...base[entityIdx], [name]: evidencePage }
      nextEvidence = base
    }
    return { entities: nextEntities, evidence: nextEvidence }
  }),
}))
