import { Maximize2, Minimize2, X } from 'lucide-react'
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
        <div className="ql-header-actions">
          <button
            type="button"
            className="ql-icon-btn"
            aria-label={maximized ? 'restore' : 'maximize'}
            title={maximized ? 'restore' : 'maximize'}
            onClick={onToggleMaximized}
          >
            {maximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          <button type="button" className="ql-icon-btn" aria-label="close" onClick={onClose}>
            <X size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}
