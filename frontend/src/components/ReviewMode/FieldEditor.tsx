import { type ChangeEvent, useState } from 'react'

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

function FieldInput({
  field,
  initial,
  onChange,
}: {
  field: SchemaField
  initial: string
  onChange: (name: string, value: string) => void
}) {
  const [local, setLocal] = useState(initial)
  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    setLocal(e.target.value)
    onChange(field.name, e.target.value)
  }
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={`f-${field.name}`} className="font-mono text-xs text-fg-secondary">
        {field.name} <span className="text-fg-muted">({field.type})</span>
      </label>
      <input
        id={`f-${field.name}`}
        type="text"
        value={local}
        onChange={handleChange}
        className="bg-surface border border-subtle px-2 py-1 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-accent-primary"
      />
      {field.description && (
        <span className="text-xs text-fg-muted leading-tight">{field.description}</span>
      )}
    </div>
  )
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
          const initial = current == null ? '' : String(current)
          return (
            <FieldInput key={f.name} field={f} initial={initial} onChange={onChange} />
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
