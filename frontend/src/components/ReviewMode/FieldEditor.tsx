// frontend/src/components/ReviewMode/FieldEditor.tsx
// T11: section-iterating wrapper around Section / JsonView.
// - Synthetic single-section fallback: all fields → one section labelled "fields"
// - Multi-entity nav: small strip above sections to swap entityIdx
// - forceOpen and view props wired from ReviewOverlay
// - M5 evidence click-to-page preserved via onJumpToPage
// - add/remove entity preserved
//
// `activeField` and `entityIdx` are hoisted into the review store so the review
// chat column header can show "<filename> · <field>" context without prop-drilling
// through ReviewOverlay.

import { ArrowLeftToLine } from 'lucide-react'
import { useCallback, useEffect, useMemo } from 'react'
import Section, { type SectionField } from './Section'
import JsonView from './JsonView'
import { useReview } from '../../stores/review'
import { useLocate } from '../../stores/locate'
import { evidencePageOf, type EvidenceValue } from '../../lib/locate'
import { useT } from '../../i18n'
import type { SchemaField } from '../../stores/schema'

/** Stable empty map so read-only tabs don't churn renders by passing a fresh
 *  `{}` literal each pass. */
const EMPTY_CORRECTIONS: Record<string, { before: unknown; after: unknown }> = {}

interface Props {
  schema: SchemaField[]
  entities: Record<string, unknown>[]
  notes?: Record<string, string>
  evidence?: (Record<string, unknown> | undefined)[] | null
  onChange: (entityIdx: number, name: string, value: unknown) => void
  onAddEntity: () => void
  onRemoveEntity: (idx: number) => void
  onJumpToPage?: (page: number) => void
  /** 'form' | 'json' — controlled by ReviewOverlay via view toggle */
  view?: 'form' | 'json'
  onSetView?: (v: 'form' | 'json') => void
  /** null = natural, true = expand all, false = collapse all */
  forceOpen?: boolean | null
  onToggleExpand?: () => void
  /** When true, all fields are read-only (experiment tabs) */
  readOnly?: boolean
  /** Bulk-copy the current display (a prediction) into the annotation and
   *  switch to the annotation tab. Only shown when readOnly. */
  onAdopt?: () => void
  /** Per-field copy — used when readOnly to import one prediction value
   *  into the annotation without leaving the comparison tab. */
  onAdoptField?: (entityIdx: number, name: string, value: unknown, evidencePage?: number | null) => void
}

export default function FieldEditor({
  schema,
  entities,
  notes = {},
  evidence,
  onChange,
  onAddEntity,
  onRemoveEntity,
  onJumpToPage,
  view = 'form',
  onSetView,
  forceOpen = null,
  onToggleExpand,
  readOnly = false,
  onAdopt,
  onAdoptField,
}: Props) {
  const t = useT()
  // Active field + entity selection live in the review store now so the chat
  // column can read them without prop-drilling.
  const activeField = useReview(s => s.activeField)
  const setActiveField = useReview(s => s.setActiveField)
  // `corrections` describes the editable 校订稿's diff. Read-only experiment /
  // draft / pending tabs render a raw model output where "已修正" is meaningless
  // — suppress the badges there instead of bleeding the 校订稿's痕迹 onto them.
  const correctionsRaw = useReview(s => s.corrections)
  const corrections = readOnly ? EMPTY_CORRECTIONS : correctionsRaw
  const pendingFocusField = useReview(s => s.pendingFocusField)
  const entityIdx = useReview(s => s.activeEntityIdx)
  const setEntityIdx = useReview(s => s.setActiveEntityIdx)
  const safeIdx = Math.min(entityIdx, Math.max(0, entities.length - 1))
  const currentEntity = entities[safeIdx] ?? {}
  const evidenceForEntity = evidence?.[safeIdx] ?? undefined

  // ── Source grounding (locate) wiring ───────────────────────────────────────
  // Resolve source rects for the currently-displayed tab's entities/evidence,
  // cached per (filename, tabKey) so this fires once per tab — not per render.
  const projectId = useReview(s => s.activeProjectId)
  const filename = useReview(s => s.activeFilename)
  const activeTabKey = useReview(s => s.activeTabKey)
  const focusLocate = useLocate(s => s.focus)
  const requestScroll = useLocate(s => s.requestScroll)
  const loadFor = useLocate(s => s.loadFor)
  const warmAndRelocate = useLocate(s => s.warmAndRelocate)
  const locateLoading = useLocate(s => s.loading)
  const tabLocations = useLocate(s => s.byKey[`${filename}::${activeTabKey}`])

  const isPending = useReview(s => s.isPending)
  // Debounce the locate trigger: a doc the user just paged past should NOT fire
  // a (CPU-heavy) locate. Without this, fast doc-switching dispatched one locate
  // per doc; the backlog saturated the backend's worker pool / GIL and froze the
  // review-form loads ("加载中…" stuck). The cleanup cancels the pending fire when
  // the doc changes, so only a doc the user settles on (>~400ms) is resolved.
  useEffect(() => {
    if (!projectId || !filename || !entities.length) return
    const id = window.setTimeout(() => {
      void loadFor(
        projectId,
        filename,
        activeTabKey,
        entities as Record<string, unknown>[],
        (evidence ?? null) as (Record<string, unknown> | null)[] | null,
        // the editable `active` tab is backed by pending when verifying a
        // pre-label, else by the draft — the grounding cache target.
        isPending ? '_pending' : '_draft',
      )
    }, 400)
    return () => window.clearTimeout(id)
  }, [projectId, filename, activeTabKey, entities, evidence, isPending, loadFor])

  // On-demand single-page OCR: when the focused field settled to `none` but has
  // a page hint, its value likely lives in that page's letterhead IMAGE (absent
  // from a cold fitz-only text layer). Warm just that page's OCR + re-locate so
  // the highlight appears — instead of stranding the user on a page-level button.
  // Fires only after locate settles (not mid-load) and is idempotent per page.
  const focusedPath = useLocate(s => s.focusedPath)
  const focusedEntity = useLocate(s => s.focusedEntity)
  useEffect(() => {
    if (!projectId || !filename || !focusedPath || focusedEntity == null) return
    if (locateLoading || !tabLocations) return  // wait for locate to settle
    const hit = tabLocations.find(
      (l) => l.entity_index === focusedEntity && l.path === focusedPath,
    )
    const resolved = !!hit && hit.status !== 'none' && hit.rects.length > 0 && hit.page != null
    if (resolved) return
    const evEntry = evidence?.[focusedEntity] ?? undefined
    const evPage = evidencePageOf(evEntry?.[focusedPath] as EvidenceValue)
    if (evPage == null) return
    void warmAndRelocate(
      projectId,
      filename,
      activeTabKey,
      evPage,
      entities as Record<string, unknown>[],
      (evidence ?? null) as (Record<string, unknown> | null)[] | null,
    )
  }, [projectId, filename, activeTabKey, focusedPath, focusedEntity, tabLocations, locateLoading, evidence, entities, warmAndRelocate])

  // Field click → existing select + new source-grounding focus. If the field's
  // resolved source sits on another page, scroll there (off-page jump lives in
  // the focus handler, not the render layer, so it fires exactly once on click).
  const handleSetActiveField = useCallback((path: string) => {
    // `focus`/`setActiveField` are toggles — clicking the active row clears it.
    // Only navigate when this click *focuses* the field, not when it clears.
    const ls = useLocate.getState()
    const wasFocused = ls.focusedPath === path && ls.focusedEntity === safeIdx
    setActiveField(path)
    focusLocate(path, safeIdx)
    if (wasFocused) return
    if (projectId && filename) {
      // Clicking a field is itself "settling" on this doc — if the debounced
      // pre-load hasn't fired yet, kick locate now (idempotent: loadFor no-ops
      // when the key is already cached) so a within-window click still resolves
      // instead of falsely showing the no-source hint. The pan then lands
      // reactively once the rect mounts (requestScroll seq).
      if (!(`${filename}::${activeTabKey}` in ls.byKey)) {
        void loadFor(
          projectId,
          filename,
          activeTabKey,
          entities as Record<string, unknown>[],
          (evidence ?? null) as (Record<string, unknown> | null)[] | null,
          isPending ? '_pending' : '_draft',
        )
      }
      const locations = ls.byKey[`${filename}::${activeTabKey}`] ?? []
      // Scope to the displayed entity — the same leaf path repeats once per
      // entity (each on its own page), so an unscoped find always lands on
      // entity 0 and the doc jumps to the wrong page.
      const hit = locations.find(
        (l) =>
          l.entity_index === safeIdx &&
          l.path === path &&
          l.status !== 'none' &&
          l.rects.length > 0 &&
          l.page != null,
      )
      // Navigate to the located page; when the field hasn't resolved (still
      // loading, or `none` because its value lives in a letterhead image absent
      // from the cold text layer), fall back to the evidence page hint so the
      // viewer still lands on the RIGHT page — never leaves the user stranded.
      // The reactive effect below then warms that page's OCR + re-locates.
      const evPage = evidencePageOf(evidenceForEntity?.[path] as EvidenceValue)
      if (hit?.page != null) onJumpToPage?.(hit.page)
      else if (evPage != null) onJumpToPage?.(evPage)
    }
    // Bump the pan request so the focused field's source rect scrolls to center
    // once its page overlay is mounted (LocateHighlight claims it). No-op when
    // the field has no located source — the doc-pane hint covers that case.
    requestScroll(path)
  }, [setActiveField, focusLocate, requestScroll, projectId, filename, activeTabKey, onJumpToPage, safeIdx, loadFor, entities, evidence, isPending])

  // Consume a queued focus from the tune banner: once the navigated doc's
  // entities are loaded, select the corrected field (which also pans the PDF)
  // and scroll its form row into view, then clear the one-shot signal.
  useEffect(() => {
    if (!pendingFocusField || entities.length === 0) return
    const field = pendingFocusField
    useReview.getState().consumePendingFocus()
    if (activeField !== field) handleSetActiveField(field)
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-fpath="${CSS.escape(field)}"]`)
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    })
  }, [pendingFocusField, entities.length, activeField, handleSetActiveField])

  // T11.1: Synthetic single-section — one section labelled "fields" containing all SchemaFields
  const sections = useMemo(() => {
    const fields: SectionField[] = schema.flatMap((f) => {
      // Top-level fields always have a name (validated server-side).
      if (!f.name) return []
      // New shape: array<object> stores row schema at items.properties.
      // Legacy shape: row schema lives at children. Normalize for Section.
      const rowSchema = f.children ?? (f.type === 'array' && f.items?.type === 'object' ? f.items.properties ?? null : null)
      return [{
        name: f.name,
        type: f.type,
        description: f.description,
        value: currentEntity[f.name] ?? null,
        note: notes[f.name],
        evidencePage: evidencePageOf(evidenceForEntity?.[f.name] as EvidenceValue | undefined),
        children: rowSchema,
      }]
    })
    // If/when backend grows section support, read from schema; for now, one section.
    return [{ id: 'fields', label: 'fields', fields }]
  }, [schema, currentEntity, notes, evidenceForEntity])

  // Store-level `setActiveField` already implements toggle semantics — pass it
  // straight to Section. `notes` is still threaded through SectionField for
  // future hover hint use, but the row no longer offers inline editing.

  return (
    <div className="flex flex-col h-full">
      {/* Top bar: entity navigator + add entity */}
      <header className="px-4 py-2 border-b border-rule flex items-center gap-3">
        {entities.length > 1 ? (
          <>
            <button
              type="button"
              aria-label={t('field.entity.prev')}
              disabled={safeIdx === 0}
              onClick={() => setEntityIdx(Math.max(0, safeIdx - 1))}
              className="font-mono text-xs px-2 py-1 border border-rule rounded hover:bg-paper-2 disabled:opacity-30"
            >
              ‹
            </button>
            <span className="font-mono text-xs text-ink-4">
              {t('field.entity.position', { idx: safeIdx + 1, total: entities.length })}
            </span>
            <button
              type="button"
              aria-label={t('field.entity.next')}
              disabled={safeIdx === entities.length - 1}
              onClick={() => setEntityIdx(Math.min(entities.length - 1, safeIdx + 1))}
              className="font-mono text-xs px-2 py-1 border border-rule rounded hover:bg-paper-2 disabled:opacity-30"
            >
              ›
            </button>
            {!readOnly && (
              <button
                type="button"
                aria-label={t('field.entity.removeIdx', { idx: safeIdx + 1 })}
                onClick={() => {
                  onRemoveEntity(safeIdx)
                  setEntityIdx(Math.max(0, safeIdx - 1))
                }}
                className="font-mono text-xs px-2 py-1 border border-rule rounded hover:bg-paper-2 text-rose ml-1"
              >
                {t('field.entity.removeLabel')}
              </button>
            )}
          </>
        ) : (
          <span className="font-mono text-xs text-ink-4">
            {entities.length === 1 ? t('field.entity.count.one') : t('field.entity.count.many', { n: entities.length })}
          </span>
        )}
        {/* FORM/JSON + expand-all live here, not in the top ReviewBar: they act
            on THIS panel, and the bar needs its horizontal room for the
            experiment tab strip (which otherwise collapses into a "»N" chip). */}
        <div className="rev-toolbar ml-auto">
          {onSetView && (
            <div className="seg">
              <button
                className={view === 'form' ? 'on' : ''}
                onClick={() => onSetView('form')}
                type="button"
              >
                {t('review.view.form')}
              </button>
              <button
                className={view === 'json' ? 'on' : ''}
                onClick={() => onSetView('json')}
                type="button"
              >
                {t('review.view.json')}
              </button>
            </div>
          )}
          {onToggleExpand && view === 'form' && (
            <button
              className="ghostbtn"
              onClick={onToggleExpand}
              title={forceOpen === true ? t('review.collapseAll') : t('review.expandAll')}
              aria-label={forceOpen === true ? t('review.collapseAll') : t('review.expandAll')}
              type="button"
              style={{ padding: '4px 7px', fontSize: 12 }}
            >
              {forceOpen === true ? '⤡' : '⤢'}
            </button>
          )}
        </div>
        {!readOnly && (
          <button
            type="button"
            aria-label={t('field.entity.add')}
            onClick={onAddEntity}
            className="font-mono text-xs px-2 py-1 border border-rule rounded hover:bg-paper-2"
          >
            {t('field.entity.addLabel')}
          </button>
        )}
        {readOnly && onAdopt && (
          <button
            type="button"
            aria-label={t('field.adopt.aria')}
            onClick={onAdopt}
            title={t('field.adopt.title')}
            className="adopt-all-btn"
          >
            <ArrowLeftToLine size={11} strokeWidth={1.7} />
            <span>{t('field.adopt.label')}</span>
          </button>
        )}
      </header>

      {/* Main content */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {view === 'json' ? (
          <JsonView data={currentEntity} activeField={activeField} readOnly={readOnly} />
        ) : (
          <div className="rev-fields">
            {sections.map((sect) => (
              <Section
                key={sect.id}
                id={sect.id}
                label={sect.label}
                fields={sect.fields}
                activeField={activeField}
                corrections={corrections}
                forceOpen={forceOpen}
                entityIdx={safeIdx}
                readOnly={readOnly}
                onChange={onChange}
                onJumpToPage={onJumpToPage}
                onSetActiveField={handleSetActiveField}
                onAdoptField={onAdoptField}
                getEvidencePage={(p) =>
                  // Grounding now keys array-child evidence by the CONCRETE row
                  // path (lines[2].name) so each row carries its own page+quote.
                  // Look up concrete-first; fall back to the collapsed form
                  // (lines[].name) for legacy blobs grounded before that change.
                  evidencePageOf(
                    (evidenceForEntity?.[p] ??
                      evidenceForEntity?.[p.replace(/\[\d+\]/g, '[]')]) as
                      | EvidenceValue
                      | undefined,
                  )}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
