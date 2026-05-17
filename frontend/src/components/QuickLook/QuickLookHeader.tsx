import type { QuickLookTarget } from '../../stores/quicklook'

interface Props {
  target: QuickLookTarget
  activeVersionId: string | null
  maximized: boolean
  onToggleMaximized: () => void
  onClose: () => void
}

export default function QuickLookHeader({ target, activeVersionId, maximized, onToggleMaximized, onClose }: Props) {
  let title: string
  if (target.kind === 'version') {
    title = `versions/${target.versionId}`
  } else if (target.promptId) {
    title = `prompts/${target.promptId}`
  } else {
    title = 'prompts/active'
  }

  let badge: { text: string; tone: 'active' | 'frozen' | 'draft' }
  if (target.kind === 'version') {
    badge = { text: `${target.versionId} · frozen`, tone: 'frozen' }
  } else if (target.promptId) {
    badge = { text: 'variant', tone: 'draft' }
  } else if (activeVersionId) {
    badge = { text: `${activeVersionId} · active`, tone: 'active' }
  } else {
    badge = { text: 'v0 · draft', tone: 'draft' }
  }

  return (
    <div className="ql-header">
      <div className="ql-header-row">
        <span className="ql-title">{title}</span>
        <span className={`ql-badge ql-badge--${badge.tone}`}>{badge.text}</span>
        <button
          type="button"
          className="ql-maximize"
          aria-label={maximized ? 'restore' : 'maximize'}
          title={maximized ? 'restore' : 'maximize'}
          onClick={onToggleMaximized}
        >
          {maximized ? '⤡' : '⤢'}
        </button>
        <button type="button" className="ql-close" aria-label="close" onClick={onClose}>✕</button>
      </div>
    </div>
  )
}
