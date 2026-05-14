// frontend/src/components/ReviewMode/FieldEditor.tsx
// T11: section-iterating wrapper around Section / JsonView.
// - Synthetic single-section fallback: all fields → one section labelled "fields"
// - Multi-entity nav: small strip above sections to swap entityIdx
// - forceOpen and view props wired from ReviewOverlay
// - M5 evidence click-to-page preserved via onJumpToPage
// - Notes editing preserved via onSetNote
// - add/remove entity preserved

import { ArrowLeftToLine } from 'lucide-react'
import { useState, useMemo } from 'react'
import Section, { type SectionField } from './Section'
import JsonView from './JsonView'

interface SchemaField {
  name: string
  type: string
  description?: string
  enum?: string[] | null
}

interface Props {
  schema: SchemaField[]
  entities: Record<string, unknown>[]
  notes?: Record<string, string>
  evidence?: (Record<string, number | null> | undefined)[] | null
  onChange: (entityIdx: number, name: string, value: unknown) => void
  onSetNote?: (name: string, note: string) => void
  onAddEntity: () => void
  onRemoveEntity: (idx: number) => void
  onJumpToPage?: (page: number) => void
  /** 'form' | 'json' — controlled by ReviewOverlay via view toggle */
  view?: 'form' | 'json'
  /** null = natural, true = expand all, false = collapse all */
  forceOpen?: boolean | null
  /** When true, all fields are read-only (experiment tabs) */
  readOnly?: boolean
  /** Document filename — rendered next to entity count for context */
  filename?: string
  /** Bulk-copy the current display (a prediction) into the annotation and
   *  switch to the annotation tab. Only shown when readOnly. */
  onAdopt?: () => void
  /** Per-field copy — used when readOnly to import one prediction value
   *  into the annotation without leaving the comparison tab. */
  onAdoptField?: (entityIdx: number, name: string, value: unknown, evidencePage?: number | null) => void
}

export default function FieldEditor({
  schema,
  entities,
  notes = {},
  evidence,
  onChange,
  onSetNote,
  onAddEntity,
  onRemoveEntity,
  onJumpToPage,
  view = 'form',
  forceOpen = null,
  readOnly = false,
  filename,
  onAdopt,
  onAdoptField,
}: Props) {
  // Active field path for highlighting (local state — one-way field→page, not PDF→field)
  const [activeField, setActiveField] = useState<string | null>(null)

  // Current entity index for multi-entity nav
  const [entityIdx, setEntityIdx] = useState(0)
  const safeIdx = Math.min(entityIdx, Math.max(0, entities.length - 1))
  const currentEntity = entities[safeIdx] ?? {}
  const evidenceForEntity = evidence?.[safeIdx] ?? undefined

  // T11.1: Synthetic single-section — one section labelled "fields" containing all SchemaFields
  const sections = useMemo(() => {
    const fields: SectionField[] = schema.map((f) => ({
      name: f.name,
      type: f.type,
      description: f.description,
      value: currentEntity[f.name] ?? null,
      note: notes[f.name],
      evidencePage: evidenceForEntity?.[f.name] ?? null,
    }))
    // If/when backend grows section support, read from schema; for now, one section.
    return [{ id: 'fields', label: 'fields', fields }]
  }, [schema, currentEntity, notes, evidenceForEntity])

  const handleSetActiveField = (path: string) => {
    setActiveField(prev => prev === path ? null : path)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Top bar: entity navigator + add entity */}
      <header className="px-4 py-2 border-b border-rule flex items-center gap-3">
        {entities.length > 1 ? (
          <>
            <button
              type="button"
              aria-label="previous entity"
              disabled={safeIdx === 0}
              onClick={() => setEntityIdx(i => Math.max(0, i - 1))}
              className="font-mono text-xs px-2 py-1 border border-rule rounded hover:bg-paper-2 disabled:opacity-30"
            >
              ‹
            </button>
            <span className="font-mono text-xs text-ink-4">
              entity {safeIdx + 1} of {entities.length}
            </span>
            <button
              type="button"
              aria-label="next entity"
              disabled={safeIdx === entities.length - 1}
              onClick={() => setEntityIdx(i => Math.min(entities.length - 1, i + 1))}
              className="font-mono text-xs px-2 py-1 border border-rule rounded hover:bg-paper-2 disabled:opacity-30"
            >
              ›
            </button>
            {!readOnly && (
              <button
                type="button"
                aria-label={`remove entity ${safeIdx + 1}`}
                onClick={() => {
                  onRemoveEntity(safeIdx)
                  setEntityIdx(i => Math.max(0, i - 1))
                }}
                className="font-mono text-xs px-2 py-1 border border-rule rounded hover:bg-paper-2 text-rose ml-1"
              >
                − remove
              </button>
            )}
          </>
        ) : (
          <span className="font-mono text-xs text-ink-4">
            {entities.length} {entities.length === 1 ? 'entity' : 'entities'}
          </span>
        )}
        {filename && (
          <span className="font-mono text-xs text-ink-4 truncate min-w-0" title={filename}>
            <span className="text-ink-5 mx-1.5">·</span>
            {filename}
          </span>
        )}
        {!readOnly && (
          <button
            type="button"
            aria-label="add entity"
            onClick={onAddEntity}
            className="ml-auto font-mono text-xs px-2 py-1 border border-rule rounded hover:bg-paper-2"
          >
            + entity
          </button>
        )}
        {readOnly && onAdopt && (
          <button
            type="button"
            aria-label="adopt this prediction as reviewed"
            onClick={onAdopt}
            title="overwrite the reviewed copy with these values and switch to it"
            className="ml-auto adopt-all-btn"
          >
            <ArrowLeftToLine size={11} strokeWidth={1.7} />
            <span>adopt as reviewed</span>
          </button>
        )}
      </header>

      {/* Main content */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {view === 'json' ? (
          <JsonView data={currentEntity} activeField={activeField} readOnly={readOnly} />
        ) : (
          <div className="rev-fields">
            {sections.map((sect) => (
              <Section
                key={sect.id}
                id={sect.id}
                label={sect.label}
                fields={sect.fields}
                activeField={activeField}
                forceOpen={forceOpen}
                entityIdx={safeIdx}
                readOnly={readOnly}
                onChange={onChange}
                onSetNote={onSetNote}
                onJumpToPage={onJumpToPage}
                onSetActiveField={handleSetActiveField}
                onAdoptField={onAdoptField}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
