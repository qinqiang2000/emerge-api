// frontend/src/components/DocList/DocItem.tsx
import { docStatus, type DocSummary } from '../../types/review'

interface Props {
  doc: DocSummary
  onClick: (docId: string) => void
}

export default function DocItem({ doc, onClick }: Props) {
  const status = docStatus(doc)
  const badge =
    status === 'reviewed' ? 'reviewed'
    : status === 'predicted' ? 'draft'
    : 'pending'
  const badgeClass =
    status === 'reviewed' ? 'text-accent-success'
    : status === 'predicted' ? 'text-accent-info'
    : 'text-fg-muted'
  return (
    <button
      onClick={() => onClick(doc.doc_id)}
      className="w-full text-left px-3 py-2 hover:bg-subtle border-b border-subtle"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-sm truncate">{doc.filename}</span>
        <span className={`text-xs uppercase tracking-wide ${badgeClass}`}>{badge}</span>
      </div>
      <span className="text-xs text-fg-muted">{doc.page_count} page{doc.page_count !== 1 ? 's' : ''}</span>
    </button>
  )
}
