// frontend/src/components/Empty/EmptyHero.tsx
import { useState } from 'react'

const STARTERS = [
  'Extract invoices from these PDFs — vendor, totals, line items',
  "Build me a schema, then I'll edit it before extraction",
  'Pull contract terms — parties, effective date, renewal clause',
]

interface Props {
  projectName?: string
  onAttach: (files: File[]) => void
  onStarter: (text: string) => void
}

export default function EmptyHero({ projectName = '', onAttach, onStarter }: Props) {
  const [dragOver, setDragOver] = useState(false)

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(true)
  }

  function handleDragLeave() {
    setDragOver(false)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) onAttach(files)
  }

  const eyebrow = projectName ? `~/projects/${projectName}/` : '~/projects/'

  return (
    <div className="empty-hero">
      <div className="ey">{eyebrow}</div>
      <h1>
        An empty folder, a willing agent, <em>and a stack of PDFs.</em>
      </h1>
      <p>
        Drop documents in. Tell the agent what you want. It&apos;ll derive a schema, run the first
        extractions, and come back to you for review.
      </p>
      <div
        className="invite"
        onClick={() => onStarter('/init')}
        role="button"
        tabIndex={0}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onStarter('/init') }}
      >
        <span className="cmd">/init</span>
        <span style={{ color: 'var(--ink-3)' }}>derive a schema from the first few documents</span>
        <span style={{ color: 'var(--ink-5)', marginLeft: 'auto' }}>↵</span>
      </div>
      <div
        className="drop"
        style={dragOver ? { borderColor: 'var(--ochre-2)', background: 'var(--ochre-soft)' } : undefined}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <b>drop PDFs or images here</b>
        <span>
          or run{' '}
          <span style={{ color: 'var(--ochre-2)', fontWeight: 500 }}>
            cp ~/Downloads/*.pdf docs/
          </span>
        </span>
      </div>
      <div className="starters">
        <div className="lbl">or try saying ·</div>
        {STARTERS.map((s, i) => (
          <button key={i} className="starter" onClick={() => onStarter(s)}>
            <span className="quote">&quot;</span>
            <span>{s}</span>
            <span className="arr">↵</span>
          </button>
        ))}
      </div>
    </div>
  )
}
