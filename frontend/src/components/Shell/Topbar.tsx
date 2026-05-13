import { useState } from 'react'
import HelpPopover from './HelpPopover'

type TopbarProps = {
  projectName: string
  schemaVersion: string   // "v3"
  schemaState: 'draft' | 'frozen'
  watchingCount: number
  improveJob?: { progressLabel: string }  // "/improve · 2 of 4 fields"
  leftHidden: boolean
  rightHidden: boolean
  onToggleLeft: () => void
  onToggleRight: () => void
}

// Inline SVG icons matching pieces.jsx geometry exactly
function IconLeftOpen() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="12" height="10" rx="1.5"/>
      <line x1="6.5" y1="3.4" x2="6.5" y2="12.6"/>
    </svg>
  )
}

function IconLeftCollapsed() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="2.5" y1="4" x2="13.5" y2="4"/>
      <line x1="2.5" y1="8" x2="13.5" y2="8"/>
      <line x1="2.5" y1="12" x2="13.5" y2="12"/>
    </svg>
  )
}

function IconRight() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="12" height="10" rx="1.5"/>
      <line x1="9.5" y1="3.4" x2="9.5" y2="12.6"/>
    </svg>
  )
}

export default function Topbar({
  projectName,
  schemaVersion,
  schemaState,
  watchingCount,
  improveJob,
  leftHidden,
  rightHidden,
  onToggleLeft,
  onToggleRight,
}: TopbarProps) {
  const [helpOpen, setHelpOpen] = useState(false)

  const displayName = projectName
    ? (projectName.endsWith('/') ? projectName : projectName + '/')
    : ''

  return (
    <>
      {/* Left toggle */}
      <button
        className={`side-toggle left${leftHidden ? ' collapsed' : ''}`}
        onClick={onToggleLeft}
        title={leftHidden ? 'Show projects (⌘.)' : 'Hide projects (⌘.)'}
        type="button"
      >
        {leftHidden ? <IconLeftCollapsed /> : <IconLeftOpen />}
      </button>

      {/* Brand */}
      <div className="brand"><span className="dot"></span>emerge</div>

      {/* Crumbs — always render; matches handoff `~/projects/<name>/ schema · v · state` shape */}
      <div className="crumbs">
        <span>~/projects/</span>
        {displayName ? (
          <>
            <span className="here">{displayName}</span>
            <span className="sep">/</span>
            <span>schema</span>
            <span className="sep">·</span>
            <span>{schemaVersion}</span>
            <span className="sep">·</span>
            <span style={{ color: 'var(--ochre-2)' }}>{schemaState}</span>
          </>
        ) : (
          <span style={{ color: 'var(--ink-5)', fontStyle: 'italic' }}>select a project</span>
        )}
      </div>

      <div className="spacer" />

      {/* Improve job pill — only when running */}
      {improveJob && (
        <span className="pill">
          <span className="dotr" />
          /improve · {improveJob.progressLabel}
        </span>
      )}

      {/* Watching docs pill */}
      {watchingCount > 0 && (
        <span className="pill">
          <span className="dotg" />
          watching docs/ · {watchingCount} file{watchingCount !== 1 ? 's' : ''}
        </span>
      )}

      {/* ⌘K pill */}
      <span className="pill">
        ⌘K · ask agent
      </span>

      {/* Help button */}
      <button
        className={'help-btn' + (helpOpen ? ' on' : '')}
        type="button"
        onClick={() => setHelpOpen(o => !o)}
        title="how this works"
        aria-label="how this works"
      >?</button>
      {helpOpen && <HelpPopover onClose={() => setHelpOpen(false)} />}

      {/* Right toggle */}
      <button
        className={`side-toggle right${rightHidden ? ' collapsed' : ''}`}
        onClick={onToggleRight}
        title={rightHidden ? 'Show documents (⌘⇧.)' : 'Hide documents (⌘⇧.)'}
        type="button"
      >
        <IconRight />
      </button>
    </>
  )
}
