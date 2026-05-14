// frontend/src/components/ReviewMode/ReviewBar.tsx
import { ArrowLeft } from 'lucide-react'

import type { DocSummary, ExperimentSummary } from '../../types/review'
import ExperimentTabStrip from './ExperimentTabStrip'
import PanelToggle from '../Shell/PanelToggle'

type Props = {
  saving: boolean
  canSave: boolean
  view: 'form' | 'json'
  onSetView: (v: 'form' | 'json') => void
  forceOpen: boolean | null
  onToggleExpand: () => void
  docs: DocSummary[]
  activeDocId: string | null
  activeProjectId: string | null
  onOpen: (pid: string, docId: string) => void
  onSave: () => void
  onBack: () => void
  // ── inline tab strip ──
  activeTabKey: 'active' | string
  availableExperiments: ExperimentSummary[]
  onSwitchTab: (key: 'active' | string) => void
  modelLabels: Record<string, string>
  // ── panel peek toggles (review mode owns chrome; floating buttons would
  //     overlap back/save, so they live inline in this bar instead) ──
  leftHidden?: boolean
  rightHidden?: boolean
  onToggleLeft?: () => void
  onToggleRight?: () => void
}

export default function ReviewBar({
  saving,
  canSave,
  view,
  onSetView,
  forceOpen,
  onToggleExpand,
  docs,
  activeDocId,
  activeProjectId,
  onOpen,
  onSave,
  onBack,
  activeTabKey,
  availableExperiments,
  onSwitchTab,
  modelLabels,
  leftHidden,
  rightHidden,
  onToggleLeft,
  onToggleRight,
}: Props) {
  const idx = docs.findIndex((d) => d.doc_id === activeDocId)
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

  const allExpanded = forceOpen === true

  return (
    <div className="rev-bar">
      <button className="back back-icon" onClick={onBack} type="button" aria-label="back to chat" title="back to chat">
        <ArrowLeft size={16} strokeWidth={1.75} />
      </button>
      {leftHidden && onToggleLeft && (
        <PanelToggle
          side="left"
          hidden={true}
          onClick={onToggleLeft}
          className="spinepeek icon"
          size={14}
        />
      )}

      {availableExperiments.some((e) => e.status !== 'archived') ? (
        <ExperimentTabStrip
          activeTabKey={activeTabKey}
          availableExperiments={availableExperiments}
          onSwitch={onSwitchTab}
          modelLabels={modelLabels}
        />
      ) : (
        <div className="spacer" />
      )}

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
        <button
          className="ghostbtn"
          onClick={onToggleExpand}
          title={allExpanded ? 'collapse all' : 'expand all'}
          aria-label={allExpanded ? 'collapse all' : 'expand all'}
          type="button"
          style={{ padding: '4px 7px', fontSize: 12 }}
        >
          {allExpanded ? '⤡' : '⤢'}
        </button>
      </div>

      <div className="nav">
        <button className="arrow" onClick={handlePrev} disabled={!hasPrev} aria-label="previous doc" type="button">‹</button>
        <button className="arrow" onClick={handleNext} disabled={!hasNext} aria-label="next doc" type="button">›</button>
      </div>

      <button
        className="save"
        onClick={onSave}
        disabled={saving || !canSave}
        type="button"
        title={!canSave ? 'save only persists on the ✏ reviewed tab — switch to it, or use “adopt as reviewed”' : undefined}
      >
        {saving ? 'saving…' : 'save'}
      </button>
      {rightHidden && onToggleRight && (
        <PanelToggle
          side="right"
          hidden={true}
          onClick={onToggleRight}
          className="spinepeek icon"
          size={14}
        />
      )}
    </div>
  )
}
