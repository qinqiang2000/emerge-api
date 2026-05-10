// frontend/src/components/ReviewMode/ReviewOverlay.tsx
import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { useReview } from '../../stores/review'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'

import FieldEditor from './FieldEditor'
import PdfViewer from './PdfViewer'
import ReviewBar from './ReviewBar'

type Props = {
  onBack: () => void
  leftPeek: boolean
  setLeftPeek: (fn: (v: boolean) => boolean) => void
  rightPeek: boolean
  setRightPeek: (fn: (v: boolean) => boolean) => void
}

export default function ReviewOverlay({ onBack, leftPeek, setLeftPeek, rightPeek, setRightPeek }: Props) {
  const {
    activeProjectId,
    activeDocId,
    entities,
    evidence,
    notes,
    page,
    pageCount,
    saving,
    err,
    setField,
    setNote,
    addEntity,
    removeEntity,
    goPage,
    save,
    open,
  } = useReview()

  const docs = useDocs(s => s.byProject[activeProjectId ?? ''] ?? [])
  const schema = useSchema(useShallow((s) => (activeProjectId ? s.byProject[activeProjectId] ?? [] : [])))
  const loadSchema = useSchema((s) => s.load)

  // view: 'form' | 'json' — consumed in T11, threaded through now
  const [view, setView] = useState<'form' | 'json'>('form')
  // _forceOpen: null = natural state, true = all expanded, false = all collapsed — plumbed in T11
  const [_forceOpen, setForceOpen] = useState<boolean | null>(null)

  useEffect(() => {
    if (!activeProjectId) return
    void loadSchema(activeProjectId)
  }, [activeProjectId, loadSchema])

  const filename = docs.find(d => d.doc_id === activeDocId)?.filename

  const handleExpandAll = () => setForceOpen(true)
  const handleCollapseAll = () => setForceOpen(false)
  const handleSetView = (v: 'form' | 'json') => {
    setView(v)
    setForceOpen(null)
  }

  return (
    <div className="rev-overlay">
      <ReviewBar
        filename={filename}
        page={page ?? 1}
        pageCount={pageCount ?? 0}
        saving={saving}
        leftPeek={leftPeek}
        setLeftPeek={setLeftPeek}
        rightPeek={rightPeek}
        setRightPeek={setRightPeek}
        view={view}
        onSetView={handleSetView}
        onExpandAll={handleExpandAll}
        onCollapseAll={handleCollapseAll}
        docs={docs}
        activeDocId={activeDocId}
        activeProjectId={activeProjectId}
        onOpen={open}
        onSave={() => void save()}
        onBack={onBack}
      />

      {err && (
        <div style={{ borderLeft: '2px solid var(--rose)', padding: '8px 16px', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--rose)' }}>
          error: {err}
        </div>
      )}

      <div className="rev-body">
        <div className="rev-pdf">
          <PdfViewer />
        </div>
        <div style={{ minHeight: 0, overflow: 'auto' }}>
          {/* forceOpen={forceOpen} and view={view} plumbed in T11 */}
          <FieldEditor
            schema={schema}
            entities={entities}
            notes={notes}
            evidence={evidence ?? null}
            onChange={setField}
            onSetNote={setNote}
            onAddEntity={addEntity}
            onRemoveEntity={removeEntity}
            onJumpToPage={goPage}
            onSave={save}
            saving={saving}
          />
        </div>
      </div>
    </div>
  )
}
