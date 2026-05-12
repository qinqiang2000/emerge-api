import { useState } from 'react'

import type { ExperimentSummary } from '../../types/review'

type Props = {
  activeTabKey: 'active' | string
  attachedExperimentIds: string[]
  availableExperiments: ExperimentSummary[]
  onSwitch: (key: 'active' | string) => void
  onAttach: (experimentId: string) => void
  onDetach: (experimentId: string) => void
  modelLabels: Record<string, string>  // model_id → display label
}

export default function ExperimentTabStrip({
  activeTabKey,
  attachedExperimentIds,
  availableExperiments,
  onSwitch,
  onAttach,
  onDetach,
  modelLabels,
}: Props) {
  const [popoverOpen, setPopoverOpen] = useState(false)
  const attachedSet = new Set(attachedExperimentIds)

  // Preserve attached order, dropping any ids that aren't in availableExperiments
  // (defensive — keeps the strip resilient if useExperiments and useReview drift).
  const attachedExperiments = attachedExperimentIds
    .map((id) => availableExperiments.find((e) => e.experiment_id === id))
    .filter((e): e is ExperimentSummary => Boolean(e))

  const candidates = availableExperiments.filter(
    (e) => !attachedSet.has(e.experiment_id) && e.status !== 'archived',
  )

  return (
    <div className="rev-tabstrip" role="tablist">
      <button
        role="tab"
        aria-selected={activeTabKey === 'active'}
        className={'rev-tab' + (activeTabKey === 'active' ? ' on' : '')}
        onClick={() => onSwitch('active')}
        type="button"
      >
        <span className="star">⭐</span> Active
      </button>

      {attachedExperiments.map((e) => (
        <button
          key={e.experiment_id}
          role="tab"
          aria-selected={activeTabKey === e.experiment_id}
          className={'rev-tab' + (activeTabKey === e.experiment_id ? ' on' : '')}
          onClick={() => onSwitch(e.experiment_id)}
          onContextMenu={(ev) => {
            ev.preventDefault()
            onDetach(e.experiment_id)
          }}
          title={`${modelLabels[e.model_id] ?? e.model_id} · ${e.prompt_id}`}
          type="button"
        >
          {e.label}
        </button>
      ))}

      <div className="rev-tab-add">
        <button
          aria-label="+"
          className="rev-tab-plus"
          onClick={() => setPopoverOpen((o) => !o)}
          type="button"
        >
          +
        </button>
        {popoverOpen && (
          <div className="rev-tab-popover" role="menu">
            {candidates.length === 0 && (
              <div className="rev-tab-empty">no more experiments to attach</div>
            )}
            {candidates.map((e) => (
              <button
                key={e.experiment_id}
                role="menuitem"
                className="rev-tab-popover-item"
                onClick={() => {
                  onAttach(e.experiment_id)
                  setPopoverOpen(false)
                }}
                type="button"
              >
                {e.label} <span className="meta">{e.status}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
