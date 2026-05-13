import type { QuickLookTarget } from '../../stores/quicklook'

interface Props {
  target: QuickLookTarget
  activeVersionId: string | null
  derivedFrom: string | null
  onClose: () => void
}

export default function QuickLookHeader({ target, activeVersionId, derivedFrom, onClose }: Props) {
  let title: string
  if (target.kind === 'version') {
    title = `versions/${target.versionId}`
  } else if (target.kind === 'prompt') {
    title = `prompts/${target.promptId}`
  } else {
    title = 'prompts/active'
  }

  let badge: { text: string; tone: 'active' | 'frozen' | 'draft' }
  if (target.kind === 'version') {
    badge = { text: `${target.versionId} · frozen`, tone: 'frozen' }
  } else if (target.kind === 'prompt') {
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
        <button type="button" className="ql-close" aria-label="close" onClick={onClose}>✕</button>
      </div>
      <div className="ql-lineage">derived from: {derivedFrom ?? '—'}</div>
    </div>
  )
}
