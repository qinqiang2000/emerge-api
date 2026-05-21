// frontend/src/components/ReviewMode/ReviewBar.tsx
import { ArrowLeft, MessageSquare, Trash2 } from 'lucide-react'

import type { DocSummary, ExperimentSummary, RunStamp } from '../../types/review'
import { docStatus } from '../../types/review'
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
  /** On-disk filename of the open doc — the only doc handle now. */
  activeFilename: string | null
  activeProjectId: string | null
  onOpen: (pid: string, filename: string) => void
  onSave: () => void
  onBack: () => void
  /** Two-step delete state lives in the parent so the Backspace shortcut and
   *  the trash button drive the same armed/confirm cycle. */
  armedDelete: boolean
  deletingDoc: boolean
  /** Single entry point for "the user wants to delete": first call arms,
   *  second call (within 3 s) confirms. Parent owns the timer + side effect. */
  onDeleteTrigger: () => void
  // ── inline tab strip ──
  activeTabKey: 'active' | '_draft' | '_pending' | string
  availableExperiments: ExperimentSummary[]
  onSwitchTab: (key: 'active' | '_draft' | '_pending' | string) => void
  modelLabels: Record<string, string>
  /** M14 — `_run` envelopes from already-loaded draft + pending blobs; the
   *  tab strip surfaces each as a readonly tab when present. */
  baselineRun?: RunStamp | null
  pendingRun?: RunStamp | null
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
  activeFilename,
  activeProjectId,
  onOpen,
  onSave,
  onBack,
  armedDelete,
  deletingDoc,
  onDeleteTrigger,
  activeTabKey,
  availableExperiments,
  onSwitchTab,
  modelLabels,
  baselineRun,
  pendingRun,
  leftHidden,
  rightHidden,
  onToggleLeft,
  onToggleRight,
}: Props) {
  const idx = docs.findIndex((d) => d.filename === activeFilename)
  const total = docs.length
  const hasPrev = idx > 0
  const hasNext = idx >= 0 && idx < total - 1
  const prevDoc = hasPrev ? docs[idx - 1] : null
  const nextDoc = hasNext ? docs[idx + 1] : null
  const activeDoc = idx >= 0 ? docs[idx] : null

  const handlePrev = () => {
    if (prevDoc && activeProjectId) void onOpen(activeProjectId, prevDoc.filename)
  }
  const handleNext = () => {
    if (nextDoc && activeProjectId) void onOpen(activeProjectId, nextDoc.filename)
  }

  const allExpanded = forceOpen === true

  const status = activeDoc ? docStatus(activeDoc) : null

  return (
    <div className="rev-bar">
      <button className="back back-icon" onClick={onBack} type="button" aria-label="back to chat (Esc)" title="back to chat · Esc">
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

      {activeFilename && (
        <div className="title" title={activeFilename}>
          reviewing
          <span className="doc">{activeFilename}</span>
          {status && <span className={`status ${status}`}>{status}</span>}
          <span className="title-actions">
            <button
              type="button"
              className={'trash' + (armedDelete ? ' armed' : '')}
              onClick={onDeleteTrigger}
              disabled={deletingDoc}
              aria-label={armedDelete ? '⌫ again to confirm delete, Esc to cancel' : 'delete this file (⌫)'}
              title={armedDelete ? "⌫ again to confirm · Esc cancel" : 'delete this file · ⌫'}
            >
              <Trash2 size={13} strokeWidth={1.75} />
              {armedDelete && <span className="trash-confirm">⌫ again to confirm · Esc cancel</span>}
            </button>
          </span>
        </div>
      )}

      {(availableExperiments.some((e) => e.status !== 'archived') ||
        baselineRun ||
        pendingRun) ? (
        <ExperimentTabStrip
          activeTabKey={activeTabKey}
          availableExperiments={availableExperiments}
          onSwitch={onSwitchTab}
          modelLabels={modelLabels}
          baselineRun={baselineRun}
          pendingRun={pendingRun}
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
        <button
          className="arrow"
          onClick={handlePrev}
          disabled={!hasPrev}
          aria-label="previous doc (left arrow)"
          title="previous doc · ←"
          type="button"
        >‹</button>
        {idx >= 0 && total > 0 && (
          <span className="navcount" title="use ← / → to step through docs">
            {idx + 1} / {total}
            <span className="kbd" aria-hidden>← →</span>
          </span>
        )}
        <button
          className="arrow"
          onClick={handleNext}
          disabled={!hasNext}
          aria-label="next doc (right arrow)"
          title="next doc · →"
          type="button"
        >›</button>
      </div>

      <button
        className="save"
        onClick={onSave}
        disabled={saving || !canSave}
        type="button"
        title={!canSave ? 'save only persists on the ✏ reviewed tab — switch to it, or use "adopt as reviewed"' : undefined}
      >
        {saving ? 'saving…' : 'save'}
      </button>
      {rightHidden && onToggleRight && (
        // Review-mode right peek: in review, the right "panel" is the chat
        // column (not ContextSurface). Swap PanelToggle's panel-icon for a
        // chat bubble so the affordance reads correctly.
        <button
          type="button"
          className="spinepeek icon"
          onClick={onToggleRight}
          aria-label="open chat"
          title="open chat (⌘⇧.)"
        >
          <MessageSquare size={14} strokeWidth={1.75} />
        </button>
      )}
    </div>
  )
}
