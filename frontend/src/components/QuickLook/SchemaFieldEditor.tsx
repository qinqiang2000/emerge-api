// Inline editor for prompts/active. Always-on edit; blur=save via store.
// Read-only branches (versions/{id}, prompts/{id}) use FieldCard instead.

import { useEffect, useRef, useState } from 'react'
import { useSchema, type SchemaField, type SaveError } from '../../stores/schema'

const TYPES = ['string', 'number', 'boolean', 'date', 'array<object>'] as const
type TypeName = (typeof TYPES)[number]

const SNAKE_RE = /^[a-z][a-z0-9_]*$/

function isSnake(name: string): boolean {
  return SNAKE_RE.test(name)
}

function csvSplit(v: string): string[] {
  return v.split(',').map(s => s.trim()).filter(s => s.length > 0)
}

function csvJoin(arr?: string[] | null): string {
  return (arr ?? []).join(', ')
}

function emptyField(name = 'new_field'): SchemaField {
  return {
    name,
    type: 'string',
    description: '',
    required: false,
    enum: null,
    children: null,
  }
}

interface Props {
  pid: string
  fields: SchemaField[]
}

export default function SchemaFieldEditor({ pid, fields }: Props) {
  const saveActive = useSchema(s => s.saveActive)
  const [error, setError] = useState<SaveError | null>(null)
  const [pending, setPending] = useState(false)

  // The committed list mirrors the store's byProject. Local edits round-trip
  // through `commit()` rather than living in component state — keeps store
  // as the single source of truth, avoids drift across multiple cards.
  const commit = async (next: SchemaField[]) => {
    setPending(true)
    setError(null)
    const err = await saveActive(pid, next)
    setPending(false)
    if (err) setError(err)
  }

  const handleChange = (index: number, patch: Partial<SchemaField>) => {
    const next = fields.map((f, i) => i === index ? { ...f, ...patch } : f)
    void commit(next)
  }

  const handleDelete = (index: number) => {
    void commit(fields.filter((_, i) => i !== index))
  }

  const handleAdd = () => {
    let n = 1
    let name = 'new_field'
    const taken = new Set(fields.map(f => f.name))
    while (taken.has(name)) { n += 1; name = `new_field_${n}` }
    void commit([...fields, emptyField(name)])
  }

  if (fields.length === 0) {
    return (
      <div>
        <div className="ql-edit-empty">
          no fields yet — add one to start, or type /init in the chat for an agent-assisted draft.
        </div>
        <FooterAdd onAdd={handleAdd} />
        {error && <ErrorBanner err={error} />}
      </div>
    )
  }

  return (
    <div className="ql-edit-list">
      {fields.map((f, idx) => (
        <SchemaCardEditor
          key={`${f.name}-${idx}`}
          field={f}
          onChange={(patch) => handleChange(idx, patch)}
          onDelete={() => handleDelete(idx)}
        />
      ))}
      <FooterAdd onAdd={handleAdd} pending={pending} />
      {error && <ErrorBanner err={error} />}
    </div>
  )
}

function FooterAdd({ onAdd, pending }: { onAdd: () => void; pending?: boolean }) {
  return (
    <div className="ql-edit-foot">
      <button type="button" className="ql-edit-add" onClick={onAdd} disabled={pending}>
        + field
      </button>
      {pending && <span className="ql-edit-pending">saving…</span>}
    </div>
  )
}

function ErrorBanner({ err }: { err: SaveError }) {
  return (
    <div className="ql-edit-err" role="alert">
      <span className="ql-edit-err-code">{err.error_code}</span>
      {err.error_message_en && <span className="ql-edit-err-msg">{err.error_message_en}</span>}
    </div>
  )
}

interface CardProps {
  field: SchemaField
  onChange: (patch: Partial<SchemaField>) => void
  onDelete: () => void
}

function SchemaCardEditor({ field, onChange, onDelete }: CardProps) {
  const nameRef = useRef<HTMLSpanElement>(null)
  const descRef = useRef<HTMLSpanElement>(null)
  const enRef = useRef<HTMLSpanElement>(null)
  const [nameError, setNameError] = useState<string | null>(null)

  // Keep contentEditable DOM in sync with store when value changes externally
  // (e.g. a peer card edit triggers a store refresh).
  useEffect(() => {
    if (nameRef.current && nameRef.current !== document.activeElement) {
      nameRef.current.textContent = field.name
    }
  }, [field.name])
  useEffect(() => {
    if (descRef.current && descRef.current !== document.activeElement) {
      descRef.current.textContent = field.description ?? ''
    }
  }, [field.description])
  useEffect(() => {
    if (enRef.current && enRef.current !== document.activeElement) {
      enRef.current.textContent = csvJoin(field.enum)
    }
  }, [field.enum])

  const isArrayOfObj = field.type === 'array<object>'

  return (
    <div className="ql-edit-card">
      <div className="ql-edit-head">
        <span
          ref={nameRef}
          className={`ql-edit-name${nameError ? ' err' : ''}`}
          contentEditable
          suppressContentEditableWarning
          spellCheck={false}
          onBlur={(e) => {
            const v = (e.currentTarget.textContent ?? '').trim()
            if (!v) {
              setNameError('name required')
              e.currentTarget.textContent = field.name
              return
            }
            if (!isSnake(v)) {
              setNameError('snake_case only')
              e.currentTarget.textContent = field.name
              return
            }
            setNameError(null)
            if (v !== field.name) onChange({ name: v })
          }}
        >
          {field.name}
        </span>
        <select
          className="ql-edit-type"
          value={TYPES.includes(field.type as TypeName) ? field.type : 'string'}
          onChange={(e) => {
            const t = e.target.value as TypeName
            // array<object> requires non-empty children — seed a placeholder
            // so backend pydantic validator doesn't reject the save.
            if (t === 'array<object>' && (!field.children || field.children.length === 0)) {
              onChange({ type: t, children: [emptyField('item')] })
            } else if (t !== 'array<object>') {
              onChange({ type: t, children: null })
            } else {
              onChange({ type: t })
            }
          }}
        >
          {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <label className="ql-edit-req">
          <input
            type="checkbox"
            checked={!!field.required}
            onChange={(e) => onChange({ required: e.target.checked })}
          />
          required
        </label>
        <button
          type="button"
          className="ql-edit-del"
          onClick={onDelete}
          aria-label={`delete field ${field.name}`}
          title="delete field"
        >
          ✕
        </button>
      </div>

      {nameError && <div className="ql-edit-name-err">{nameError}</div>}

      <span
        ref={descRef}
        className={`ql-edit-desc${field.description ? '' : ' empty'}`}
        data-placeholder="describe what this field captures — this is the prompt"
        contentEditable
        suppressContentEditableWarning
        onBlur={(e) => {
          const v = e.currentTarget.textContent ?? ''
          if (v !== (field.description ?? '')) onChange({ description: v })
        }}
      >
        {field.description ?? ''}
      </span>

      <div className="ql-edit-row">
        <span className="ql-edit-row-lab">enum</span>
        <span
          ref={enRef}
          className="ql-edit-row-val"
          contentEditable
          suppressContentEditableWarning
          data-placeholder="comma-separated…"
          onBlur={(e) => {
            const arr = csvSplit(e.currentTarget.textContent ?? '')
            const next = arr.length > 0 ? arr : null
            if (csvJoin(next) !== csvJoin(field.enum)) onChange({ enum: next })
          }}
        >
          {csvJoin(field.enum)}
        </span>
      </div>

      {isArrayOfObj && (
        <ChildrenEditor
          items={field.children ?? []}
          onChange={(next) => onChange({ children: next })}
        />
      )}
    </div>
  )
}

function ChildrenEditor({
  items,
  onChange,
}: {
  items: SchemaField[]
  onChange: (next: SchemaField[]) => void
}) {
  const handleChildChange = (idx: number, patch: Partial<SchemaField>) => {
    onChange(items.map((c, i) => i === idx ? { ...c, ...patch } : c))
  }
  const handleDelete = (idx: number) => {
    // array<object> requires non-empty children; keep at least one stub.
    if (items.length <= 1) return
    onChange(items.filter((_, i) => i !== idx))
  }
  const handleAdd = () => {
    let n = 1
    let name = 'sub_field'
    const taken = new Set(items.map(c => c.name))
    while (taken.has(name)) { n += 1; name = `sub_field_${n}` }
    onChange([...items, emptyField(name)])
  }
  return (
    <div className="ql-edit-children">
      <div className="ql-edit-children-lab">children</div>
      {items.map((c, idx) => (
        <SchemaCardEditor
          key={`${c.name}-${idx}`}
          field={c}
          onChange={(patch) => handleChildChange(idx, patch)}
          onDelete={() => handleDelete(idx)}
        />
      ))}
      <button type="button" className="ql-edit-add ql-edit-add--sm" onClick={handleAdd}>
        + child
      </button>
    </div>
  )
}
