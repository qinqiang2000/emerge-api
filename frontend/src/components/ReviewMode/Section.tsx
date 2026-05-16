// frontend/src/components/ReviewMode/Section.tsx
// T11.5 — port of review.jsx:140-183
// Sticky section header with count chip, optional flag pill.
// Dispatches to FieldRow / ObjectField / ArrayField by type.

import { useState, useEffect } from 'react'
import FieldRow from './FieldRow'
import ObjectField from './ObjectField'
import ArrayField from './ArrayField'
import type { SchemaField } from '../../stores/schema'

export interface SectionField {
  name: string
  type: string
  description?: string
  value: unknown
  /** Loaded for future hover hint; FieldRow no longer offers inline editing. */
  note?: string
  evidencePage?: number | null
  /** Row sub-schema for type='array<object>'. */
  children?: SchemaField[] | null
}

interface Props {
  id: string
  label: string
  fields: SectionField[]
  activeField: string | null
  forceOpen?: boolean | null
  flag?: string
  entityIdx: number
  readOnly?: boolean
  onChange: (entityIdx: number, name: string, value: unknown) => void
  onJumpToPage?: (page: number) => void
  onSetActiveField: (path: string) => void
  /** Per-field copy from prediction → annotation (only meaningful when readOnly). */
  onAdoptField?: (entityIdx: number, name: string, value: unknown, evidencePage?: number | null) => void
}

export default function Section({
  id: _id,
  label,
  fields,
  activeField,
  forceOpen,
  flag,
  entityIdx,
  readOnly = false,
  onChange,
  onJumpToPage,
  onSetActiveField,
  onAdoptField,
}: Props) {
  const [open, setOpen] = useState(true)

  // forceOpen syncs from ReviewOverlay expand-all / collapse-all
  useEffect(() => {
    if (forceOpen !== null && forceOpen !== undefined) setOpen(forceOpen)
  }, [forceOpen])

  const flagCount = fields.length

  return (
    <div className="rev-sect">
      <div className="sect-h" onClick={() => setOpen(o => !o)}>
        <span className="caret">{open ? '▾' : '▸'}</span>
        <span className="lab">{label}</span>
        <span className="cnt">{flagCount} fields</span>
        {flag && <span className="flag">{flag}</span>}
      </div>
      {open && (
        <div className="sect-body">
          {fields.map((f) => {
            const path = f.name
            const isActive = activeField === path

            if (f.type === 'object') {
              return (
                <ObjectField
                  key={f.name}
                  path={path}
                  name={f.name}
                  value={f.value}
                  active={isActive}
                  forceOpen={forceOpen}
                  readOnly={readOnly}
                  onChange={(v) => onChange(entityIdx, f.name, v)}
                  onClick={onSetActiveField}
                />
              )
            }

            if (f.type === 'array<object>' || f.type === 'array') {
              return (
                <ArrayField
                  key={f.name}
                  path={path}
                  name={f.name}
                  value={f.value}
                  rowSchema={f.children ?? null}
                  active={isActive}
                  forceOpen={forceOpen}
                  readOnly={readOnly}
                  onChange={(v) => onChange(entityIdx, f.name, v)}
                  onClick={onSetActiveField}
                />
              )
            }

            return (
              <FieldRow
                key={f.name}
                path={path}
                name={f.name}
                type={f.type}
                value={f.value}
                evidencePage={f.evidencePage}
                active={isActive}
                readOnly={readOnly}
                onChange={(v) => onChange(entityIdx, f.name, v)}
                onJumpToPage={onJumpToPage}
                onClick={onSetActiveField}
                onAdopt={
                  onAdoptField
                    ? () => onAdoptField(entityIdx, f.name, f.value, f.evidencePage ?? null)
                    : undefined
                }
              />
            )
          })}
        </div>
      )}
    </div>
  )
}
