import { useState } from 'react'
import type { ChangeEvent, ReactNode } from 'react'

import NotesPopover from './NotesPopover'

interface SchemaField {
  name: string
  type: string
  description: string
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
  onSave: () => void
  saving: boolean
}

export default function FieldEditor({ schema, entities, notes = {}, evidence, onChange, onSetNote, onAddEntity, onRemoveEntity, onJumpToPage, onSave, saving }: Props) {
  const [openFor, setOpenFor] = useState<string | null>(null)

  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 border-b border-subtle flex items-center justify-between">
        <span className="font-heading text-sm uppercase tracking-wide text-fg-muted">
          {entities.length} {entities.length === 1 ? 'entity' : 'entities'}
        </span>
        <button
          type="button"
          aria-label="add entity"
          onClick={onAddEntity}
          className="text-xs px-2 py-1 border border-subtle rounded hover:bg-subtle font-mono"
        >
          + entity
        </button>
      </header>
      <div className="flex-1 overflow-auto px-4 py-3 space-y-4">
        {entities.map((values, entityIdx) => {
          const evidenceForEntity = evidence?.[entityIdx] ?? undefined
          return (
          <section key={entityIdx} className="border border-subtle rounded p-3 space-y-3">
            {entities.length > 1 && (
              <div className="flex items-center justify-between pb-1 border-b border-subtle">
                <span className="font-mono text-xs text-fg-muted">entity #{entityIdx + 1}</span>
                <button
                  type="button"
                  aria-label={`remove entity ${entityIdx + 1}`}
                  onClick={() => onRemoveEntity(entityIdx)}
                  className="text-xs px-2 py-0.5 border border-subtle rounded hover:bg-subtle font-mono text-accent-danger"
                >
                  −
                </button>
              </div>
            )}
            {schema.map((f) => {
              const current = values[f.name]
              const popoverKey = `${entityIdx}-${f.name}`
              const labelEl = (
                <label htmlFor={`f-${entityIdx}-${f.name}`} className="font-mono text-xs text-fg-secondary">
                  {f.name} <span className="text-fg-muted">({f.type})</span>
                </label>
              )
              const evidencePage = evidenceForEntity?.[f.name] ?? null
              const labelRow = (
                <div className="flex items-center gap-2">
                  {labelEl}
                  {evidencePage != null && (
                    <button
                      type="button"
                      onClick={() => onJumpToPage?.(evidencePage)}
                      className="inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono border border-subtle rounded text-fg-muted hover:bg-subtle"
                      aria-label={`jump to page ${evidencePage}`}
                    >
                      p{evidencePage}
                    </button>
                  )}
                </div>
              )
              let control: ReactNode

              if (f.type === 'string' && f.enum && f.enum.length > 0) {
                control = (
                  <div className="flex gap-2 flex-wrap">
                    {f.enum.map((opt) => (
                      <button
                        key={opt}
                        type="button"
                        onClick={() => onChange(entityIdx, f.name, opt)}
                        className={
                          'px-2 py-1 border text-xs rounded ' +
                          (current === opt ? 'bg-accent-primary text-canvas border-transparent' : 'border-subtle hover:bg-subtle')
                        }
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                )
              } else if (f.type === 'number') {
                const display = current == null ? '' : String(current)
                const num = typeof current === 'number' ? current : Number(current ?? 0)
                control = (
                  <div className="flex items-center gap-2">
                    <button type="button" aria-label="-" onClick={() => onChange(entityIdx, f.name, num - 1)}
                            className="px-2 py-1 border border-subtle font-mono">-</button>
                    <input
                      id={`f-${entityIdx}-${f.name}`}
                      type="text"
                      value={display}
                      onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(entityIdx, f.name, e.target.value)}
                      className="bg-surface border border-subtle px-2 py-1 font-mono text-sm w-32"
                    />
                    <button type="button" aria-label="+" onClick={() => onChange(entityIdx, f.name, num + 1)}
                            className="px-2 py-1 border border-subtle font-mono">+</button>
                  </div>
                )
              } else if (f.type === 'boolean') {
                const checked = !!current
                control = (
                  <button
                    role="switch"
                    aria-label={`${entityIdx}-${f.name}`}
                    aria-checked={checked}
                    onClick={() => onChange(entityIdx, f.name, !checked)}
                    className={
                      'inline-flex items-center w-10 h-5 rounded-full transition-colors ' +
                      (checked ? 'bg-accent-success' : 'bg-subtle')
                    }
                  >
                    <span className={`inline-block w-4 h-4 rounded-full bg-canvas transform transition-transform ${checked ? 'translate-x-5' : 'translate-x-1'}`} />
                  </button>
                )
              } else {
                const display = current == null ? '' : String(current)
                control = (
                  <input
                    id={`f-${entityIdx}-${f.name}`}
                    type="text"
                    value={display}
                    onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(entityIdx, f.name, e.target.value)}
                    className="bg-surface border border-subtle px-2 py-1 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-accent-primary"
                  />
                )
              }

              return (
                <div
                  key={f.name}
                  className="relative flex flex-col gap-1"
                  onContextMenu={(e) => { e.preventDefault(); setOpenFor(popoverKey) }}
                >
                  {labelRow}
                  {control}
                  {notes[f.name] && (
                    <span className="text-xs text-accent-info" title="note">note: {notes[f.name]}</span>
                  )}
                  {f.description && (
                    <span className="text-xs text-fg-muted leading-tight">{f.description}</span>
                  )}
                  {openFor === popoverKey && onSetNote && (
                    <NotesPopover
                      fieldName={f.name}
                      initial={notes[f.name] ?? ''}
                      onSave={(t) => onSetNote(f.name, t)}
                      onClose={() => setOpenFor(null)}
                    />
                  )}
                </div>
              )
            })}
          </section>
          )
        })}
      </div>
      <footer className="px-4 py-3 border-t border-subtle">
        <button
          type="button"
          onClick={onSave}
          disabled={saving}
          className="px-4 py-2 bg-accent-primary text-canvas font-heading text-sm uppercase tracking-wide rounded hover:opacity-90 disabled:opacity-50"
        >
          {saving ? 'saving…' : 'save reviewed'}
        </button>
      </footer>
    </div>
  )
}
