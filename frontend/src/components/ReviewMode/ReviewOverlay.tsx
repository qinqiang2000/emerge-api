// frontend/src/components/ReviewMode/ReviewOverlay.tsx
import { useEffect, useMemo, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { useReview } from '../../stores/review'
import { useReviewTune } from '../../stores/reviewTune'
import { toast } from '../../stores/toast'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'
import { useExperiments } from '../../stores/experiments'
import { useModels } from '../../stores/models'
import { useChat } from '../../stores/chat'

import FieldEditor from './FieldEditor'
import PdfViewer from './PdfViewer'
import PreLabelNotice from './PreLabelNotice'
import ReviewBar from './ReviewBar'
import ReviewChatColumn, { readRevChatWidth, writeRevChatWidth } from './ReviewChatColumn'
import { useT } from '../../i18n'

type Props = {
  onBack: () => void
  leftHidden?: boolean
  rightHidden?: boolean
  onToggleLeft?: () => void
  onToggleRight?: () => void
}

export default function ReviewOverlay({
  onBack,
  leftHidden,
  rightHidden,
  onToggleLeft,
  onToggleRight,
}: Props) {
  const t = useT()
  const {
    activeProjectId,
    activeFilename,
    entities,
    evidence,
    notes,
    loading,
    saving,
    err,
    setField,
    addEntity,
    removeEntity,
    goPage,
    save,
    open,
    activeTabKey,
    predictionsByExp,
    loadExperimentPrediction,
    setActiveTab,
    adoptPrediction,
    adoptPredictionField,
    activeField: activeFieldPath,
    activeEntityIdx,
    isPending,
    labelerModel,
    draftRun,
    draftEntities,
    draftEvidence,
    pendingRun,
    pendingEntities,
    pendingEvidence,
  } = useReview()

  const docs = useDocs(useShallow(s => s.byProject[activeProjectId ?? ''] ?? []))
  const removeDocFromStore = useDocs((s) => s.remove)
  const schema = useSchema(useShallow((s) => (activeProjectId ? s.byProject[activeProjectId] ?? [] : [])))
  const loadSchema = useSchema((s) => s.load)
  const loadExperiments = useExperiments((s) => s.load)
  const loadModels = useModels((s) => s.load)

  const experimentList = useExperiments(useShallow(s => activeProjectId ? s.list[activeProjectId] ?? [] : []))
  const modelList = useModels(useShallow(s => activeProjectId ? s.list[activeProjectId] ?? [] : []))

  // For the tab strip's top line we want a compact, recognizable model name.
  // The user-supplied `label` often duplicates the model_id ("Default (gemini-
  // 2.5-flash)"); the bare provider_model_id reads better in a tight chip.
  const modelLabels = useMemo(
    () => Object.fromEntries(modelList.map(m => [m.model_id, m.provider_model_id])),
    [modelList],
  )

  // M14 — `_draft` / `_pending` are synthetic tab keys (not experiment ids);
  // their entities/evidence live on the store from the initial `open()` fetch.
  // Everything except 'active' is readonly — only the ✏ annotation tab edits.
  const displayEntities = activeTabKey === 'active'
    ? entities
    : activeTabKey === '_draft'
      ? (draftEntities ?? [])
      : activeTabKey === '_pending'
        ? (pendingEntities ?? [])
        : (predictionsByExp[activeTabKey]?.entities ?? [])
  const displayEvidence = activeTabKey === 'active'
    ? evidence
    : activeTabKey === '_draft'
      ? (draftEvidence ?? null)
      : activeTabKey === '_pending'
        ? (pendingEvidence ?? null)
        : (predictionsByExp[activeTabKey]?._evidence ?? null)
  const readOnly = activeTabKey !== 'active'

  const handleAdoptAll = readOnly
    ? () => adoptPrediction(displayEntities, displayEvidence ?? null)
    : undefined
  const handleAdoptField = readOnly
    ? (entityIdx: number, name: string, value: unknown, evidencePage?: number | null) =>
        adoptPredictionField(entityIdx, name, value, evidencePage)
    : undefined

  const [view, setView] = useState<'form' | 'json'>('form')
  const [forceOpen, setForceOpen] = useState<boolean | null>(null)

  // ── review chat column width (px, persisted) ──
  // The third-column toggle is driven by App.tsx's existing right-rail
  // hidden state (KEY_RIGHT_REVIEW), threaded down as `rightHidden`. Width
  // is independent state because the toggle is binary and width is analog.
  const [chatW, setChatW] = useState<number>(() => readRevChatWidth())
  const chatOpen = !rightHidden
  const handleChatWidthChange = (px: number) => {
    setChatW(px)
    writeRevChatWidth(px)
  }
  const currentEntityForChat = entities[activeEntityIdx] ?? entities[0] ?? {}
  const activeFieldValue = activeFieldPath
    ? (currentEntityForChat as Record<string, unknown>)[activeFieldPath]
    : undefined

  // ── draggable splitter ──────────────────────────────────────────────
  // Delta-based: capture startX/startPct on mousedown so the handle stays
  // glued to the cursor instead of snapping its left edge to clientX on the
  // first mousemove (which made the splitter jump away from the press point).
  const bodyRef = useRef<HTMLDivElement>(null)
  const SPLIT_MIN = 22, SPLIT_MAX = 78
  const [splitPct, setSplitPct] = useState(() => {
    const v = parseFloat(localStorage.getItem('emerge.revSplit') ?? '')
    return (v >= SPLIT_MIN && v <= SPLIT_MAX) ? v : 52
  })
  const [splitDrag, setSplitDrag] = useState(false)
  const splitStartX = useRef(0)
  const splitStartPct = useRef(splitPct)

  useEffect(() => { localStorage.setItem('emerge.revSplit', String(splitPct)) }, [splitPct])

  useEffect(() => {
    if (!splitDrag) return
    function onMove(e: MouseEvent | TouchEvent) {
      const body = bodyRef.current; if (!body) return
      const rect = body.getBoundingClientRect()
      const x = 'touches' in e ? e.touches[0].clientX : e.clientX
      const dxPct = ((x - splitStartX.current) / rect.width) * 100
      const next = splitStartPct.current + dxPct
      setSplitPct(Math.max(SPLIT_MIN, Math.min(SPLIT_MAX, next)))
      if (e.cancelable) e.preventDefault()
    }
    function onUp() { setSplitDrag(false) }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    window.addEventListener('touchmove', onMove, { passive: false })
    window.addEventListener('touchend', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('touchend', onUp)
    }
  }, [splitDrag])

  function startSplitDrag(e: React.MouseEvent | React.TouchEvent) {
    splitStartX.current = 'touches' in e ? e.touches[0].clientX : e.clientX
    splitStartPct.current = splitPct
    setSplitDrag(true)
    e.preventDefault()
  }

  useEffect(() => {
    if (!activeProjectId) return
    void loadSchema(activeProjectId)
    void loadExperiments(activeProjectId)
    void loadModels(activeProjectId)
  }, [activeProjectId, loadSchema, loadExperiments, loadModels])

  // ── tune signal (non-chat focused-tune affordance) ──
  // Refresh the correction-backlog summary when the doc changes and after each
  // save (so the "field X corrected K times" copy tracks the latest edit), and
  // drop in-flight job cards when the project changes.
  const tuneSignal = useReviewTune((s) => s.signal)
  const dismissedKey = useReviewTune((s) => s.dismissedKey)
  useEffect(() => {
    useReviewTune.getState().reset()
  }, [activeProjectId])
  useEffect(() => {
    if (activeProjectId && activeFilename) {
      void useReviewTune.getState().refresh(activeProjectId)
    }
  }, [activeProjectId, activeFilename])
  const prevSaving = useRef(saving)
  useEffect(() => {
    if (prevSaving.current && !saving && activeProjectId) {
      void useReviewTune.getState().refresh(activeProjectId)
    }
    prevSaving.current = saving
  }, [saving, activeProjectId])

  // Always tune the *full* set of fields corrected in this backlog — a field
  // corrected only once still gets fixed. `hot_fields` (corrected ≥2×) is kept
  // only for copy emphasis/ordering, never to trim the target set (otherwise a
  // single-correction field gets silently dropped when a hotter field exists).
  const tuneTargets = tuneSignal ? tuneSignal.corrected_fields : []
  // Dismiss fingerprint: the sorted field-name set this banner is offering to
  // tune. Dismissing stores this key; the banner stays hidden while the set is
  // unchanged, and re-appears once a NEW field gets corrected (key changes).
  const tuneKey = [...tuneTargets].sort().join('|')
  // Compact field list for the multi-field banner: first 3 names + a localized
  // "etc." when there are more.
  const fieldsPreview = (fields: string[]): string => {
    const head = fields.slice(0, 3).join(', ')
    return fields.length > 3 ? `${head} ${t('review.tune.andMore')}` : head
  }
  // Expandable "what did I change" disclosure under the banner. Renders the
  // human's own before→after edits (from tuneSignal.samples) so "optimize
  // these fields" isn't a black box — you see what the tune will learn from.
  const [tuneOpen, setTuneOpen] = useState(false)
  const fmtVal = (v: unknown): string => {
    if (v == null || v === '') return t('review.tune.empty')
    return typeof v === 'object' ? JSON.stringify(v) : String(v)
  }
  const handleTune = () => {
    if (!activeProjectId || tuneTargets.length === 0) return
    // Land the progress card on a fresh thread instead of stacking it on the
    // project's persisted history (dogfood: "is the old session still here?").
    // The job subscription lives in useJob (keyed by jobId, independent of
    // chatId), so opening a new chat here never interrupts the in-flight tune;
    // the old thread is preserved under its own chatId and reachable via history.
    useChat.getState().newChat(activeProjectId)
    void useReviewTune.getState().startFocused(activeProjectId, tuneTargets)
    toast.ok(t('review.tune.started'))
    // Surface the progress in the right-hand chat column: open it if hidden.
    if (rightHidden && onToggleRight) onToggleRight()
  }

  // Auto-load every non-archived experiment's prediction so all tabs are
  // immediately switchable; loadExperimentPrediction is idempotent per id.
  useEffect(() => {
    if (!activeProjectId || !activeFilename) return
    for (const e of experimentList) {
      if (e.status === 'archived') continue
      void loadExperimentPrediction(e.experiment_id)
    }
  }, [activeProjectId, activeFilename, experimentList, loadExperimentPrediction])

  // An experiment only earns a tab on THIS doc if it actually produced a
  // prediction for it. The eager probe above stores `null` in predictionsByExp
  // when the GET 404s (experiment never ran on this doc) — hide those rather
  // than render a 0-entity tab that looks like a bug. `undefined` = not yet
  // probed; keep it visible so a covering tab doesn't flicker out before its
  // fetch resolves. open() resets activeTabKey to 'active' on every doc switch,
  // so a hidden tab can never be the active one.
  const visibleExperiments = useMemo(
    () => experimentList.filter(
      (e) => e.status !== 'archived' && predictionsByExp[e.experiment_id] !== null,
    ),
    [experimentList, predictionsByExp],
  )

  // ── neighbor + delete + key-nav helpers ──
  // Centralized so the trash button and the ← / → key handler share one
  // navigation rule: prefer the next doc, fall back to prev, otherwise close.
  const currentIdx = activeFilename
    ? docs.findIndex(d => d.filename === activeFilename)
    : -1
  const stepTo = (delta: -1 | 1) => {
    if (!activeProjectId || currentIdx < 0) return
    const target = currentIdx + delta
    if (target < 0 || target >= docs.length) return
    void open(activeProjectId, docs[target].filename)
  }
  const handleDelete = async (target: string) => {
    if (!activeProjectId) return
    // Pick the doc to jump to *before* the list shrinks. Prefer the next
    // doc (so users moving forward through a review queue keep flowing);
    // fall back to the previous one; otherwise close the overlay.
    const fallback = docs[currentIdx + 1] ?? docs[currentIdx - 1] ?? null
    try {
      await removeDocFromStore(activeProjectId, target)
    } catch {
      // surface via the existing err banner; useDocs.remove only throws on
      // network/HTTP errors, and the overlay's `err` slot is owned by the
      // review store. Best-effort: just bail.
      return
    }
    if (fallback) {
      void open(activeProjectId, fallback.filename)
    } else {
      onBack()
    }
  }

  // ── two-step delete (shared by trash button + Backspace shortcut) ──
  // armed/deleting live here so the keyboard handler can drive them too;
  // ReviewBar's trash button is purely presentational.
  const [armedDelete, setArmedDelete] = useState(false)
  const [deletingDoc, setDeletingDoc] = useState(false)
  const armTimerRef = useRef<number | null>(null)
  useEffect(() => {
    if (!armedDelete) return
    armTimerRef.current = window.setTimeout(() => setArmedDelete(false), 3000)
    return () => { if (armTimerRef.current != null) window.clearTimeout(armTimerRef.current) }
  }, [armedDelete])
  useEffect(() => { setArmedDelete(false) }, [activeFilename])

  const armOrConfirmDelete = () => {
    if (!activeFilename || deletingDoc) return
    if (!armedDelete) { setArmedDelete(true); return }
    setArmedDelete(false)
    setDeletingDoc(true)
    void Promise.resolve(handleDelete(activeFilename)).finally(() => setDeletingDoc(false))
  }

  // Keyboard nav + delete. We skip when the user is typing in a text field
  // (input / textarea / contentEditable) so editing a value never triggers
  // navigation or delete. PDF area gets the keys — the viewer has no
  // horizontal-arrow controls of its own.
  //   ← / →         step through docs
  //   ⌫ (Backspace) arm delete; second press confirms
  //   Esc           cancel armed delete
  //
  // Enter is intentionally NOT bound: too many focusable elements (sidebar doc
  // rows, buttons) convert Enter into a click, and a "press Enter to confirm
  // destructive action" shortcut would either fight those handlers or
  // require capture-phase interception that surprises users.
  //
  // We register in the *capture* phase so this fires before per-element
  // onKeyDown handlers — Backspace/←/→/Esc are claimed before any inner
  // listener (e.g. spine rows) can see them.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null
      const inField = !!t && (() => {
        const tag = t.tagName
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
        if (t.isContentEditable) return true
        if (t.closest && t.closest('[contenteditable="true"]')) return true
        return false
      })()

      const claim = () => { e.preventDefault(); e.stopImmediatePropagation() }

      // Cmd/Ctrl+S → save. Claimed FIRST and regardless of `inField` (save is a
      // global action; the user is usually focused inside a contentEditable
      // field). preventDefault stops the browser's "save page as" dialog. Read
      // live store state to avoid stale closures (no need to widen deps); only
      // the editable ✏ tab persists, so gate on readOnly/saving there.
      if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S')) {
        claim()
        const st = useReview.getState()
        const readOnlyNow = st.activeTabKey !== 'active'
        if (!readOnlyNow && !st.saving) void st.save()
        return
      }

      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        if (e.metaKey || e.ctrlKey || e.altKey) return
        if (inField) return
        claim()
        stepTo(e.key === 'ArrowLeft' ? -1 : 1)
        return
      }

      if (e.key === 'Backspace') {
        if (e.metaKey || e.ctrlKey || e.altKey) return
        if (inField) return
        if (!activeFilename) return
        claim()
        armOrConfirmDelete()
        return
      }

      if (e.key === 'Escape') {
        if (armedDelete) {
          claim()
          setArmedDelete(false)
          return
        }
        if (!inField && !useChat.getState().busy) {
          claim()
          onBack()
          return
        }
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProjectId, activeFilename, docs.length, currentIdx, armedDelete, deletingDoc])

  const handleToggleExpand = () => setForceOpen(v => (v === true ? false : true))
  const handleSetView = (v: 'form' | 'json') => {
    setView(v)
    setForceOpen(null)
  }

  return (
    <div className="rev-overlay">
      <ReviewBar
        saving={saving}
        canSave={!readOnly}
        view={view}
        onSetView={handleSetView}
        forceOpen={forceOpen}
        onToggleExpand={handleToggleExpand}
        docs={docs}
        activeFilename={activeFilename}
        activeProjectId={activeProjectId}
        onOpen={open}
        onSave={() => void save()}
        onBack={onBack}
        armedDelete={armedDelete}
        deletingDoc={deletingDoc}
        onDeleteTrigger={armOrConfirmDelete}
        activeTabKey={activeTabKey}
        availableExperiments={visibleExperiments}
        onSwitchTab={setActiveTab}
        modelLabels={modelLabels}
        baselineRun={draftRun}
        pendingRun={pendingRun}
        leftHidden={leftHidden}
        rightHidden={rightHidden}
        onToggleLeft={onToggleLeft}
        onToggleRight={onToggleRight}
      />

      {tuneSignal && tuneTargets.length > 0 && tuneKey !== dismissedKey && (
        <div className="rev-tune-bar">
          <div className="rev-tune-row">
            <button
              type="button"
              className="rev-tune-msg"
              onClick={() => setTuneOpen(o => !o)}
              aria-expanded={tuneOpen}
              title={t('review.tune.toggleHint')}
            >
              <span className={'rev-tune-caret' + (tuneOpen ? ' open' : '')}>▸</span>
              {tuneTargets.length === 1 ? (
                t('review.tune.focus', {
                  field: tuneTargets[0],
                  count: tuneSignal.by_field.find(b => b.field === tuneTargets[0])?.count ?? 1,
                })
              ) : (
                t('review.tune.multi', {
                  fields: fieldsPreview(tuneTargets),
                  n: tuneTargets.length,
                })
              )}
            </button>
            <button type="button" className="rev-tune-cta" onClick={handleTune}>
              {tuneTargets.length === 1 ? t('review.tune.focus.cta') : t('review.tune.multi.cta')}
            </button>
            <button
              type="button"
              className="rev-tune-dismiss"
              onClick={() => useReviewTune.getState().dismiss(tuneKey)}
              title={t('review.tune.dismiss')}
              aria-label={t('review.tune.dismiss')}
            >✕</button>
          </div>
          {tuneOpen && (
            <div className="rev-tune-detail">
              {tuneTargets.map((f) => (
                <div key={f} className="rev-tune-drow">
                  <span className="fld">{f}</span>
                  <span className="diffs">
                    {(tuneSignal.samples[f] ?? []).map((s, i) => (
                      <button
                        key={i}
                        type="button"
                        className="diff"
                        title={`${s.filename} · ${t('review.tune.jumpHint')}`}
                        onClick={() => {
                          if (activeProjectId) {
                            void useReview.getState().navigateToCorrection(activeProjectId, s.filename, f)
                          }
                        }}
                      >
                        <span className="b">{fmtVal(s.before)}</span>
                        <span className="ar">→</span>
                        <span className="a">{fmtVal(s.after)}</span>
                      </button>
                    ))}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {isPending && !readOnly && (
        <PreLabelNotice labelerModel={labelerModel} />
      )}

      {err && (
        <div style={{ borderLeft: '2px solid var(--rose)', padding: '8px 16px', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--rose)' }}>
          error: {err}
        </div>
      )}

      <div
        className={
          'rev-body'
          + (splitDrag ? ' dragging' : '')
          + (chatOpen ? ' has-chat' : '')
        }
        ref={bodyRef}
        style={{
          '--rev-split': splitPct + '%',
          '--rev-split-frac': splitPct / 100,
          '--rev-chat-w': chatW + 'px',
        } as React.CSSProperties}
      >
        <div className="rev-pdf">
          <PdfViewer />
        </div>
        <div
          className={'rev-split' + (splitDrag ? ' active' : '')}
          onMouseDown={startSplitDrag}
          onTouchStart={startSplitDrag}
          onDoubleClick={() => setSplitPct(52)}
          title={t('review.overlay.resize')}
        />
        <div style={{ minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
          {loading ? (
            <div style={{ padding: '16px', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-5)' }}>
              {t('review.loading')}
            </div>
          ) : (
            <FieldEditor
              schema={schema}
              entities={displayEntities}
              notes={notes}
              evidence={displayEvidence ?? null}
              onChange={setField}
              onAddEntity={addEntity}
              onRemoveEntity={removeEntity}
              onJumpToPage={goPage}
              view={view}
              forceOpen={forceOpen}
              readOnly={readOnly}
              onAdopt={handleAdoptAll}
              onAdoptField={handleAdoptField}
            />
          )}
        </div>
        {chatOpen && onToggleRight && (
          <ReviewChatColumn
            filename={activeFilename}
            activeField={activeFieldPath}
            activeValue={activeFieldValue}
            width={chatW}
            onWidthChange={handleChatWidthChange}
            onClose={onToggleRight}
          />
        )}
      </div>
    </div>
  )
}
