// frontend/src/components/ReviewMode/ObjectField.tsx
// T11.3 — port of review.jsx:48-76
// Sub-field schema not available in backend today; renders raw object as editable JSON.
// See design-decisions.md 2026-05-10 for rationale.

import { useState, useRef, useEffect } from 'react'

interface Props {
  path: string
  name: string
  value: unknown
  active: boolean
  forceOpen?: boolean | null
  readOnly?: boolean
  onChange: (value: unknown) => void
  onClick: (path: string) => void
}

export default function ObjectField({ path, name, value, active, forceOpen, readOnly = false, onChange, onClick }: Props) {
  const [open, setOpen] = useState(false)
  const preRef = useRef<HTMLPreElement>(null)

  // forceOpen prop sync
  useEffect(() => {
    if (forceOpen !== null && forceOpen !== undefined) setOpen(forceOpen)
  }, [forceOpen])

  const json = value == null ? '{}' : JSON.stringify(value, null, 2)
  const keyCount = value && typeof value === 'object' && !Array.isArray(value)
    ? Object.keys(value as Record<string, unknown>).length
    : 0
  // Summary: first string value for a quick glance
  const summary = value && typeof value === 'object' && !Array.isArray(value)
    ? Object.values(value as Record<string, unknown>).find(v => typeof v === 'string') as string | undefined
    : undefined

  // Sync JSON into pre when value changes externally
  useEffect(() => {
    if (preRef.current && preRef.current !== document.activeElement) {
      preRef.current.textContent = json
    }
  }, [json])

  return (
    <div
      className={`rev-obj${active ? ' active' : ''}`}
      onClick={() => onClick(path)}
    >
      <div
        className="objhead"
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o) }}
      >
        {/* Confidence dot — hard-coded to 'high' per design-decisions.md */}
        <span className="cdot" title="confidence: high" />
        <span className="name">{name}</span>
        <span className="ty">object · {keyCount} keys</span>
        {summary && !open && (
          <span className="objsum" title={summary}>{summary}</span>
        )}
        <span className="caret">{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div className="objbody">
          <pre
            ref={preRef}
            contentEditable={!readOnly}
            suppressContentEditableWarning
            style={{ margin: 0, fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.55, color: 'var(--ink-2)', outline: 'none', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
            onBlur={(e) => {
              if (readOnly) return
              try {
                onChange(JSON.parse(e.currentTarget.textContent ?? '{}'))
              } catch {
                // invalid JSON — restore
                if (preRef.current) preRef.current.textContent = json
              }
            }}
          >
            {json}
          </pre>
        </div>
      )}
    </div>
  )
}
