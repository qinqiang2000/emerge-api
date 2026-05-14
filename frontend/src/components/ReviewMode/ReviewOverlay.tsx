// frontend/src/components/ReviewMode/ReviewOverlay.tsx
import { useEffect, useMemo, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { useReview } from '../../stores/review'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'
import { useExperiments } from '../../stores/experiments'
import { useModels } from '../../stores/models'

import FieldEditor from './FieldEditor'
import PdfViewer from './PdfViewer'
import ReviewBar from './ReviewBar'

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
  const {
    activeProjectId,
    activeDocId,
    entities,
    evidence,
    notes,
    loading,
    saving,
    err,
    setField,
    setNote,
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
  } = useReview()

  const docs = useDocs(useShallow(s => s.byProject[activeProjectId ?? ''] ?? []))
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

  const displayEntities = activeTabKey === 'active'
    ? entities
    : (predictionsByExp[activeTabKey]?.entities ?? [])
  const displayEvidence = activeTabKey === 'active'
    ? evidence
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

  // ── draggable splitter ──────────────────────────────────────────────
  const bodyRef = useRef<HTMLDivElement>(null)
  const SPLIT_MIN = 22, SPLIT_MAX = 78
  const [splitPct, setSplitPct] = useState(() => {
    const v = parseFloat(localStorage.getItem('emerge.revSplit') ?? '')
    return (v >= SPLIT_MIN && v <= SPLIT_MAX) ? v : 52
  })
  const [splitDrag, setSplitDrag] = useState(false)

  useEffect(() => { localStorage.setItem('emerge.revSplit', String(splitPct)) }, [splitPct])

  useEffect(() => {
    if (!splitDrag) return
    function onMove(e: MouseEvent | TouchEvent) {
      const body = bodyRef.current; if (!body) return
      const rect = body.getBoundingClientRect()
      const x = 'touches' in e ? e.touches[0].clientX : e.clientX
      const pct = ((x - rect.left) / rect.width) * 100
      setSplitPct(Math.max(SPLIT_MIN, Math.min(SPLIT_MAX, pct)))
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
    e.preventDefault()
    setSplitDrag(true)
  }

  useEffect(() => {
    if (!activeProjectId) return
    void loadSchema(activeProjectId)
    void loadExperiments(activeProjectId)
    void loadModels(activeProjectId)
  }, [activeProjectId, loadSchema, loadExperiments, loadModels])

  // Auto-load every non-archived experiment's prediction so all tabs are
  // immediately switchable; loadExperimentPrediction is idempotent per id.
  useEffect(() => {
    if (!activeProjectId || !activeDocId) return
    for (const e of experimentList) {
      if (e.status === 'archived') continue
      void loadExperimentPrediction(e.experiment_id)
    }
  }, [activeProjectId, activeDocId, experimentList, loadExperimentPrediction])

  const filename = docs.find(d => d.doc_id === activeDocId)?.filename

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
        activeDocId={activeDocId}
        activeProjectId={activeProjectId}
        onOpen={open}
        onSave={() => void save()}
        onBack={onBack}
        activeTabKey={activeTabKey}
        availableExperiments={experimentList}
        onSwitchTab={setActiveTab}
        modelLabels={modelLabels}
        leftHidden={leftHidden}
        rightHidden={rightHidden}
        onToggleLeft={onToggleLeft}
        onToggleRight={onToggleRight}
      />

      {err && (
        <div style={{ borderLeft: '2px solid var(--rose)', padding: '8px 16px', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--rose)' }}>
          error: {err}
        </div>
      )}

      <div
        className={'rev-body' + (splitDrag ? ' dragging' : '')}
        ref={bodyRef}
        style={{ '--rev-split': splitPct + '%' } as React.CSSProperties}
      >
        <div className="rev-pdf">
          <PdfViewer />
        </div>
        <div
          className={'rev-split' + (splitDrag ? ' active' : '')}
          onMouseDown={startSplitDrag}
          onTouchStart={startSplitDrag}
          onDoubleClick={() => setSplitPct(52)}
          title="Drag to resize · double-click to reset"
        />
        <div style={{ minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
          {loading ? (
            <div style={{ padding: '16px', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-5)' }}>
              loading…
            </div>
          ) : (
            <FieldEditor
              schema={schema}
              entities={displayEntities}
              notes={notes}
              evidence={displayEvidence ?? null}
              onChange={setField}
              onSetNote={setNote}
              onAddEntity={addEntity}
              onRemoveEntity={removeEntity}
              onJumpToPage={goPage}
              view={view}
              forceOpen={forceOpen}
              readOnly={readOnly}
              filename={filename}
              onAdopt={handleAdoptAll}
              onAdoptField={handleAdoptField}
            />
          )}
        </div>
      </div>
    </div>
  )
}
