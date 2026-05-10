// frontend/src/components/ReviewMode/ArrayField.tsx
// T11.4 — port of review.jsx:78-137
// Array sub-field schema not available; each entry renders as collapsible JSON card.
// See design-decisions.md 2026-05-10 for rationale.

import { useState, useRef, useEffect } from 'react'

interface ArrayEntry {
  value: unknown
  warn?: string
}

function parseEntries(value: unknown): ArrayEntry[] {
  if (!Array.isArray(value)) return []
  return value.map((v) => ({ value: v }))
}

interface Props {
  path: string
  name: string
  value: unknown
  active: boolean
  forceOpen?: boolean | null
  onChange: (value: unknown) => void
  onClick: (path: string) => void
}

function RowCard({
  index,
  entry,
  forceOpen,
  onChangeEntry,
}: {
  index: number
  entry: ArrayEntry
  forceOpen?: boolean | null
  onChangeEntry: (v: unknown) => void
}) {
  const [open, setOpen] = useState(false)
  const preRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (forceOpen !== null && forceOpen !== undefined) setOpen(forceOpen)
  }, [forceOpen])

  const json = JSON.stringify(entry.value, null, 2)
  const summary = typeof entry.value === 'string'
    ? entry.value
    : entry.value && typeof entry.value === 'object'
      ? Object.values(entry.value as Record<string, unknown>).find(v => typeof v === 'string') as string | undefined
      : undefined

  useEffect(() => {
    if (preRef.current && preRef.current !== document.activeElement) {
      preRef.current.textContent = json
    }
  }, [json])

  return (
    <div className={`rcard${entry.warn ? ' warn' : ''}${open ? ' open' : ''}`}>
      <div className="rhead" onClick={() => setOpen(o => !o)}>
        <span className="ix">#{index + 1}</span>
        <span className="rsum">{summary ?? '—'}</span>
        {entry.warn && <span className="rwarn">{entry.warn}</span>}
        <span className="caret">{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div className="rbody">
          <pre
            ref={preRef}
            contentEditable
            suppressContentEditableWarning
            style={{ margin: 0, fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.55, color: 'var(--ink-2)', outline: 'none', whiteSpace: 'pre-wrap', wordBreak: 'break-all', padding: '4px 8px' }}
            onBlur={(e) => {
              try {
                onChangeEntry(JSON.parse(e.currentTarget.textContent ?? 'null'))
              } catch {
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

export default function ArrayField({ path, name, value, active, forceOpen, onChange, onClick }: Props) {
  const [open, setOpen] = useState(true)

  useEffect(() => {
    if (forceOpen !== null && forceOpen !== undefined) setOpen(forceOpen)
  }, [forceOpen])

  const entries = parseEntries(value)
  const arrValue = Array.isArray(value) ? (value as unknown[]) : []

  const handleChangeEntry = (index: number, v: unknown) => {
    const next = arrValue.map((item, i) => i === index ? v : item)
    onChange(next)
  }

  const handleAddRow = (e: React.MouseEvent) => {
    e.stopPropagation()
    onChange([...arrValue, {}])
  }

  const handleDuplicateRow = (e: React.MouseEvent, index: number) => {
    e.stopPropagation()
    const copy = JSON.parse(JSON.stringify(arrValue[index]))
    const next = [...arrValue.slice(0, index + 1), copy, ...arrValue.slice(index + 1)]
    onChange(next)
  }

  const handleDeleteRow = (e: React.MouseEvent, index: number) => {
    e.stopPropagation()
    onChange(arrValue.filter((_, i) => i !== index))
  }

  return (
    <div
      className={`rev-arr${active ? ' active' : ''}`}
      onClick={() => onClick(path)}
    >
      <div className="arrhead" onClick={(e) => { e.stopPropagation(); setOpen(o => !o) }}>
        {/* Confidence dot — hard-coded to 'high' per design-decisions.md */}
        <span className="cdot" title="confidence: high" />
        <span className="name">{name}</span>
        <span className="ty">array · {entries.length} rows</span>
        <div className="actions" onClick={(e) => e.stopPropagation()}>
          <button type="button" className="rowbtn" onClick={handleAddRow} aria-label="add row">
            + row
          </button>
        </div>
        <span className="caret">{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div className="arrlist">
          {entries.length === 0 && (
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-5)', padding: '8px 10px' }}>
              no items
            </div>
          )}
          {entries.map((entry, idx) => (
            <div key={idx} style={{ position: 'relative' }}>
              <RowCard
                index={idx}
                entry={entry}
                forceOpen={forceOpen}
                onChangeEntry={(v) => handleChangeEntry(idx, v)}
              />
              <div className="rfoot">
                <button
                  type="button"
                  className="rowbtn"
                  aria-label={`duplicate row ${idx + 1}`}
                  onClick={(e) => handleDuplicateRow(e, idx)}
                >
                  duplicate
                </button>
                <button
                  type="button"
                  className="rowbtn danger"
                  aria-label={`delete row ${idx + 1}`}
                  onClick={(e) => handleDeleteRow(e, idx)}
                >
                  delete row
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
