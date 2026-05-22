// Array of objects — stack of row-cards. Each row's body shows the sub-fields
// as a mini FieldRow grid (when `rowSchema` is supplied, i.e. type='array<object>').
// Falls back to JSON-blob rendering when no rowSchema is available.

import { useState, useEffect } from 'react'
import type { SchemaField } from '../../stores/schema'
import { useT } from '../../i18n'

interface ArrayEntry {
  value: unknown
  warn?: string
}

function parseEntries(value: unknown): ArrayEntry[] {
  if (!Array.isArray(value)) return []
  return value.map((v) => ({ value: v }))
}

function summarize(entry: unknown, rowSchema: SchemaField[] | null): string | undefined {
  if (typeof entry === 'string') return entry
  if (!entry || typeof entry !== 'object') return undefined
  const obj = entry as Record<string, unknown>
  // Prefer the first string-typed field in the schema; fall back to any string value.
  if (rowSchema) {
    for (const f of rowSchema) {
      if (!f.name) continue
      const v = obj[f.name]
      if (typeof v === 'string' && v.length > 0) return v
    }
  }
  for (const v of Object.values(obj)) {
    if (typeof v === 'string' && v.length > 0) return v as string
  }
  return undefined
}

interface SubFieldRowProps {
  name: string
  type: string
  value: unknown
  readOnly: boolean
  onChange: (v: unknown) => void
}

function SubFieldRow({ name, type, value, readOnly, onChange }: SubFieldRowProps) {
  const displayValue = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value)
  return (
    <div className="rev-arr-sub">
      <div className="rev-arr-sub-key">
        <span className="rev-arr-sub-name">{name}</span>
        <span className="rev-arr-sub-ty">{type}</span>
      </div>
      <span
        className="rev-arr-sub-val"
        contentEditable={!readOnly}
        suppressContentEditableWarning
        onBlur={(e) => {
          if (readOnly) return
          const next = e.currentTarget.textContent ?? ''
          // Coerce back to the original primitive shape where reasonable.
          if (type === 'number') {
            const n = Number(next)
            onChange(Number.isFinite(n) && next.trim() !== '' ? n : next)
          } else if (type === 'boolean') {
            const trimmed = next.trim().toLowerCase()
            if (trimmed === 'true' || trimmed === 'false') onChange(trimmed === 'true')
            else onChange(next)
          } else {
            onChange(next)
          }
        }}
      >
        {displayValue}
      </span>
    </div>
  )
}

interface RowCardProps {
  index: number
  entry: ArrayEntry
  rowSchema: SchemaField[] | null
  forceOpen?: boolean | null
  readOnly: boolean
  onChangeEntry: (v: unknown) => void
}

function RowCard({ index, entry, rowSchema, forceOpen, readOnly, onChangeEntry }: RowCardProps) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (forceOpen !== null && forceOpen !== undefined) setOpen(forceOpen)
  }, [forceOpen])

  const summary = summarize(entry.value, rowSchema)
  const obj = (entry.value && typeof entry.value === 'object' && !Array.isArray(entry.value))
    ? (entry.value as Record<string, unknown>)
    : null

  // Surface a tabular amount if the row has one — common in line-item arrays.
  const amount = obj
    ? (typeof obj.amount === 'number' ? obj.amount
       : typeof obj.unit_price === 'number' ? obj.unit_price
       : typeof obj.total === 'number' ? obj.total
       : undefined)
    : undefined

  const handleSubChange = (key: string, value: unknown) => {
    const base = obj ?? {}
    onChangeEntry({ ...base, [key]: value })
  }

  return (
    <div className={`rcard${entry.warn ? ' warn' : ''}${open ? ' open' : ''}`}>
      <div className="rhead" onClick={() => setOpen(o => !o)}>
        <span className="ix">#{index + 1}</span>
        <span className="rsum">{summary ?? '—'}</span>
        {entry.warn && <span className="rwarn">{entry.warn}</span>}
        {amount !== undefined && <span className="ramt">{amount}</span>}
        <span className="caret">{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div className="rbody">
          {rowSchema && obj ? (
            <div className="rev-arr-sub-grid">
              {rowSchema.map(child => {
                if (!child.name) return null
                const cname = child.name
                return (
                  <SubFieldRow
                    key={cname}
                    name={cname}
                    type={child.type}
                    value={obj[cname] ?? null}
                    readOnly={readOnly}
                    onChange={(v) => handleSubChange(cname, v)}
                  />
                )
              })}
            </div>
          ) : (
            <RawJsonEditor value={entry.value} readOnly={readOnly} onChange={onChangeEntry} />
          )}
        </div>
      )}
    </div>
  )
}

function RawJsonEditor({
  value,
  readOnly,
  onChange,
}: { value: unknown; readOnly: boolean; onChange: (v: unknown) => void }) {
  const json = JSON.stringify(value, null, 2)
  return (
    <pre
      className="rev-arr-rawpre"
      contentEditable={!readOnly}
      suppressContentEditableWarning
      onBlur={(e) => {
        if (readOnly) return
        try {
          onChange(JSON.parse(e.currentTarget.textContent ?? 'null'))
        } catch {
          e.currentTarget.textContent = json
        }
      }}
    >
      {json}
    </pre>
  )
}

interface Props {
  path: string
  name: string
  value: unknown
  rowSchema: SchemaField[] | null
  active: boolean
  forceOpen?: boolean | null
  readOnly?: boolean
  onChange: (value: unknown) => void
  onClick: (path: string) => void
}

export default function ArrayField({
  path,
  name,
  value,
  rowSchema,
  active,
  forceOpen,
  readOnly = false,
  onChange,
  onClick,
}: Props) {
  const t = useT()
  const [open, setOpen] = useState(true)

  useEffect(() => {
    if (forceOpen !== null && forceOpen !== undefined) setOpen(forceOpen)
  }, [forceOpen])

  const entries = parseEntries(value)
  const arrValue = Array.isArray(value) ? (value as unknown[]) : []

  const handleChangeEntry = (index: number, v: unknown) => {
    onChange(arrValue.map((item, i) => i === index ? v : item))
  }

  const handleAddRow = (e: React.MouseEvent) => {
    e.stopPropagation()
    // Seed with empty values keyed by the schema so the row renders sensibly.
    const seed: Record<string, unknown> = {}
    if (rowSchema) {
      for (const f of rowSchema) {
        if (!f.name) continue
        seed[f.name] = null
      }
    }
    onChange([...arrValue, seed])
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
        <span className="cdot" title={t('field.confidence.high')} />
        <span className="name">{name}</span>
        <span className="ty">{t('field.array.rows', { n: entries.length })}</span>
        {!readOnly && (
          <div className="actions" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="rowbtn" onClick={handleAddRow} aria-label={t('field.row.add')}>
              {t('field.row.add.label')}
            </button>
          </div>
        )}
        <span className="caret">{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div className="arrlist">
          {entries.length === 0 && (
            <div className="rev-arr-empty">{t('field.row.empty')}</div>
          )}
          {entries.map((entry, idx) => (
            <div key={idx} className="rev-arr-rowwrap">
              <RowCard
                index={idx}
                entry={entry}
                rowSchema={rowSchema}
                forceOpen={forceOpen}
                readOnly={readOnly}
                onChangeEntry={(v) => handleChangeEntry(idx, v)}
              />
              {!readOnly && (
                <div className="rfoot">
                  <button
                    type="button"
                    className="rowbtn"
                    aria-label={t('field.row.duplicate', { idx: idx + 1 })}
                    onClick={(e) => handleDuplicateRow(e, idx)}
                  >
                    {t('field.row.duplicate.label')}
                  </button>
                  <button
                    type="button"
                    className="rowbtn danger"
                    aria-label={t('field.row.delete', { idx: idx + 1 })}
                    onClick={(e) => handleDeleteRow(e, idx)}
                  >
                    {t('field.row.delete.label')}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
