import type { ChangeEvent } from 'react'

interface SchemaField {
  name: string
  type: string
  description: string
  enum?: string[] | null
}

interface Props {
  schema: SchemaField[]
  values: Record<string, unknown>
  onChange: (name: string, value: string) => void
  onSave: () => void
  saving: boolean
}

export default function FieldEditor({ schema, values, onChange, onSave, saving }: Props) {
  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 border-b border-subtle font-heading text-sm uppercase tracking-wide text-fg-muted">
        Fields
      </header>
      <div className="flex-1 overflow-auto px-4 py-3 space-y-3">
        {schema.map((f) => {
          const current = values[f.name]
          const display = current == null ? '' : String(current)
          return (
            <div key={f.name} className="flex flex-col gap-1">
              <label htmlFor={`f-${f.name}`} className="font-mono text-xs text-fg-secondary">
                {f.name} <span className="text-fg-muted">({f.type})</span>
              </label>
              <input
                id={`f-${f.name}`}
                type="text"
                value={display}
                onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(f.name, e.target.value)}
                className="bg-surface border border-subtle px-2 py-1 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-accent-primary"
              />
              {f.description && (
                <span className="text-xs text-fg-muted leading-tight">{f.description}</span>
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
