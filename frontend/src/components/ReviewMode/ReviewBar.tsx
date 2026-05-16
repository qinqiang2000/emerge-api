// frontend/src/components/ReviewMode/ReviewBar.tsx
import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, MessageSquare, Trash2 } from 'lucide-react'

import type { DocSummary, ExperimentSummary } from '../../types/review'
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
  /** Delete the currently-open doc. Receives the filename so the parent can
   *  decide what to navigate to next (next doc, prev doc, or back to chat). */
  onDelete: (filename: string) => Promise<void> | void
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
  activeFilename,
  activeProjectId,
  onOpen,
  onSave,
  onBack,
  onDelete,
  activeTabKey,
  availableExperiments,
  onSwitchTab,
  modelLabels,
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

  // ── two-step delete confirm ──
  // First click reveals the confirm popover anchored to the trash icon; second
  // click runs the delete. A 3 s no-action timer rolls it back so an accidental
  // first click can't sit waiting forever. We track `armed` on the button (not
  // the popover) so clicking elsewhere also dismisses.
  const [armed, setArmed] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const armTimer = useRef<number | null>(null)
  useEffect(() => {
    if (!armed) return
    armTimer.current = window.setTimeout(() => setArmed(false), 3000)
    return () => {
      if (armTimer.current != null) window.clearTimeout(armTimer.current)
    }
  }, [armed])
  // Reset arm state when the active doc changes (navigating past a half-armed
  // confirm should never carry over to the next doc).
  useEffect(() => { setArmed(false) }, [activeFilename])

  const handleTrashClick = () => {
    if (!activeFilename || deleting) return
    if (!armed) { setArmed(true); return }
    setArmed(false)
    setDeleting(true)
    Promise.resolve(onDelete(activeFilename)).finally(() => setDeleting(false))
  }

  const status = activeDoc ? docStatus(activeDoc) : null

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

      {activeFilename && (
        <div className="title" title={activeFilename}>
          reviewing
          <span className="doc">{activeFilename}</span>
          {status && <span className={`status ${status}`}>{status}</span>}
          <span className="title-actions">
            <button
              type="button"
              className={'trash' + (armed ? ' armed' : '')}
              onClick={handleTrashClick}
              disabled={deleting}
              aria-label={armed ? 'click again to confirm delete' : 'delete this file'}
              title={armed ? "click again — can't be undone" : 'delete this file'}
            >
              <Trash2 size={13} strokeWidth={1.75} />
              {armed && <span className="trash-confirm">confirm · can't be undone</span>}
            </button>
          </span>
        </div>
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
