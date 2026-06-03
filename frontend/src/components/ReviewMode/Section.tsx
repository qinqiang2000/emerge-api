// frontend/src/components/ReviewMode/Section.tsx
// T11.5 — port of review.jsx:140-183
// Sticky section header with count chip, optional flag pill.
// Dispatches to FieldRow / ObjectField / ArrayField by type.

import { useState, useEffect } from 'react'
import { Pencil } from 'lucide-react'
import FieldRow from './FieldRow'
import ObjectField from './ObjectField'
import ArrayField from './ArrayField'
import type { SchemaField } from '../../stores/schema'
import { useReview } from '../../stores/review'
import { useQuickLook } from '../../stores/quicklook'
import { useT } from '../../i18n'

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
  /** Per-field before/after of the open doc's persisted corrections; a row
   *  whose path is a key here renders a "corrected" badge. */
  corrections?: Record<string, { before: unknown; after: unknown }>
  forceOpen?: boolean | null
  flag?: string
  entityIdx: number
  readOnly?: boolean
  onChange: (entityIdx: number, name: string, value: unknown) => void
  onJumpToPage?: (page: number) => void
  onSetActiveField: (path: string) => void
  /** Per-field copy from prediction → annotation (only meaningful when readOnly). */
  onAdoptField?: (entityIdx: number, name: string, value: unknown, evidencePage?: number | null) => void
  /** Resolve a leaf path (incl. array children like `lines[].name`) to its
   *  evidence page, for the p1 jump link on nested rows. */
  getEvidencePage?: (path: string) => number | null
}

export default function Section({
  id: _id,
  label,
  fields,
  activeField,
  corrections,
  forceOpen,
  flag,
  entityIdx,
  readOnly = false,
  onChange,
  onJumpToPage,
  onSetActiveField,
  onAdoptField,
  getEvidencePage,
}: Props) {
  const t = useT()
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
        <button
          type="button"
          className="sect-edit"
          aria-label={t('schema.editFields')}
          title={t('schema.editFields')}
          onClick={(e) => {
            e.stopPropagation()
            const pid = useReview.getState().activeProjectId
            if (pid) useQuickLook.getState().openPrompt(pid)
          }}
        >
          <Pencil size={10} strokeWidth={1.8} />
        </button>
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
                  getEvidencePage={getEvidencePage}
                  activeField={activeField}
                  onSetActiveField={onSetActiveField}
                  onJumpToPage={onJumpToPage}
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
                corrected={corrections?.[path]}
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
