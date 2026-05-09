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
  values: Record<string, unknown>
  notes?: Record<string, string>
  onChange: (name: string, value: unknown) => void
  onSetNote?: (name: string, note: string) => void
  onSave: () => void
  saving: boolean
}

export default function FieldEditor({ schema, values, notes = {}, onChange, onSetNote, onSave, saving }: Props) {
  const [openFor, setOpenFor] = useState<string | null>(null)

  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 border-b border-subtle font-heading text-sm uppercase tracking-wide text-fg-muted">
        Fields
      </header>
      <div className="flex-1 overflow-auto px-4 py-3 space-y-3">
        {schema.map((f) => {
          const current = values[f.name]
          const labelEl = (
            <label htmlFor={`f-${f.name}`} className="font-mono text-xs text-fg-secondary">
              {f.name} <span className="text-fg-muted">({f.type})</span>
            </label>
          )
          let control: ReactNode

          if (f.type === 'string' && f.enum && f.enum.length > 0) {
            control = (
              <div className="flex gap-2 flex-wrap">
                {f.enum.map((opt) => (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => onChange(f.name, opt)}
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
                <button type="button" aria-label="-" onClick={() => onChange(f.name, num - 1)}
                        className="px-2 py-1 border border-subtle font-mono">-</button>
                <input
                  id={`f-${f.name}`}
                  type="text"
                  value={display}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(f.name, e.target.value)}
                  className="bg-surface border border-subtle px-2 py-1 font-mono text-sm w-32"
                />
                <button type="button" aria-label="+" onClick={() => onChange(f.name, num + 1)}
                        className="px-2 py-1 border border-subtle font-mono">+</button>
              </div>
            )
          } else if (f.type === 'boolean') {
            const checked = !!current
            control = (
              <button
                role="switch"
                aria-label={f.name}
                aria-checked={checked}
                onClick={() => onChange(f.name, !checked)}
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
                id={`f-${f.name}`}
                type="text"
                value={display}
                onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(f.name, e.target.value)}
                className="bg-surface border border-subtle px-2 py-1 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-accent-primary"
              />
            )
          }

          return (
            <div
              key={f.name}
              className="relative flex flex-col gap-1"
              onContextMenu={(e) => { e.preventDefault(); setOpenFor(f.name) }}
            >
              {labelEl}
              {control}
              {notes[f.name] && (
                <span className="text-xs text-accent-info" title="note">note: {notes[f.name]}</span>
              )}
              {f.description && (
                <span className="text-xs text-fg-muted leading-tight">{f.description}</span>
              )}
              {openFor === f.name && onSetNote && (
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
