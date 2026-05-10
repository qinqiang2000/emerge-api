// frontend/src/components/ReviewMode/ReviewBar.tsx
import type { DocSummary } from '../../types/review'

// Inline SVG icons reused from Topbar geometry
function IconLeftOpen() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="12" height="10" rx="1.5"/>
      <line x1="6.5" y1="3.4" x2="6.5" y2="12.6"/>
    </svg>
  )
}

function IconRightPanel() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="12" height="10" rx="1.5"/>
      <line x1="9.5" y1="3.4" x2="9.5" y2="12.6"/>
    </svg>
  )
}

type Props = {
  filename?: string
  page: number
  pageCount: number
  saving: boolean
  leftPeek: boolean
  setLeftPeek: (fn: (v: boolean) => boolean) => void
  rightPeek: boolean
  setRightPeek: (fn: (v: boolean) => boolean) => void
  view: 'form' | 'json'
  onSetView: (v: 'form' | 'json') => void
  onExpandAll: () => void
  onCollapseAll: () => void
  docs: DocSummary[]
  activeDocId: string | null
  activeProjectId: string | null
  onOpen: (pid: string, docId: string) => void
  onSave: () => void
  onBack: () => void
}

export default function ReviewBar({
  filename,
  page,
  pageCount,
  saving,
  leftPeek,
  setLeftPeek,
  rightPeek,
  setRightPeek,
  view,
  onSetView,
  onExpandAll,
  onCollapseAll,
  docs,
  activeDocId,
  activeProjectId,
  onOpen,
  onSave,
  onBack,
}: Props) {
  const idx = docs.findIndex(d => d.doc_id === activeDocId)
  const total = docs.length
  const hasPrev = idx > 0
  const hasNext = idx >= 0 && idx < total - 1
  const prevDoc = hasPrev ? docs[idx - 1] : null
  const nextDoc = hasNext ? docs[idx + 1] : null

  const handlePrev = () => {
    if (prevDoc && activeProjectId) void onOpen(activeProjectId, prevDoc.doc_id)
  }
  const handleNext = () => {
    if (nextDoc && activeProjectId) void onOpen(activeProjectId, nextDoc.doc_id)
  }

  return (
    <div className="rev-bar">
      <button className="back" onClick={onBack}>← back</button>

      <span className="title">
        <em>Reviewing</em>
        <span className="doc">{filename ?? activeDocId} · pg {page}/{pageCount || '?'}</span>
      </span>

      <button
        className={'spinepeek icon' + (leftPeek ? ' on' : '')}
        onClick={() => setLeftPeek(v => !v)}
        title={leftPeek ? 'hide spine' : 'peek spine'}
        type="button"
      >
        <IconLeftOpen />
      </button>

      <button
        className={'spinepeek icon' + (rightPeek ? ' on' : '')}
        onClick={() => setRightPeek(v => !v)}
        title={rightPeek ? 'hide context' : 'peek context'}
        type="button"
      >
        <IconRightPanel />
      </button>

      <div className="rev-toolbar">
        <div className="seg">
          <button
            className={view === 'form' ? 'on' : ''}
            onClick={() => onSetView('form')}
            type="button"
          >
            form
          </button>
          <button
            className={view === 'json' ? 'on' : ''}
            onClick={() => onSetView('json')}
            type="button"
          >
            json
          </button>
        </div>
        <button className="ghostbtn" onClick={onExpandAll} type="button">expand all</button>
        <button className="ghostbtn" onClick={onCollapseAll} type="button">collapse</button>
      </div>

      <div className="spacer" />

      <div className="nav">
        <button className="arrow" onClick={handlePrev} disabled={!hasPrev} type="button">‹</button>
        <span>doc {idx >= 0 ? idx + 1 : '–'} / {total}</span>
        <button className="arrow" onClick={handleNext} disabled={!hasNext} type="button">›</button>
      </div>

      <button className="save" onClick={onSave} disabled={saving} type="button">
        {saving ? 'saving…' : 'save'}
      </button>
    </div>
  )
}
