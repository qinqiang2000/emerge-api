// Inline editor for prompts/active. Always-on edit; blur=save via store.
// Read-only branches (versions/{id}, prompts/{id}) use FieldCard instead.

import { useEffect, useRef, useState } from 'react'
import { useSchema, type SchemaField, type SaveError } from '../../stores/schema'
import { Reminder } from '../Reminder'

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

type Status = 'idle' | 'saving' | 'saved' | 'error'

const SAVED_HOLD_MS = 1500

interface Props {
  pid: string
  fields: SchemaField[]
}

export default function SchemaFieldEditor({ pid, fields }: Props) {
  const saveActive = useSchema(s => s.saveActive)
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<SaveError | null>(null)
  const savedTimerRef = useRef<number | null>(null)

  useEffect(() => () => {
    if (savedTimerRef.current !== null) window.clearTimeout(savedTimerRef.current)
  }, [])

  // The committed list mirrors the store's byProject. Local edits round-trip
  // through `commit()` rather than living in component state — keeps store
  // as the single source of truth, avoids drift across multiple cards.
  const commit = async (next: SchemaField[]) => {
    if (savedTimerRef.current !== null) {
      window.clearTimeout(savedTimerRef.current)
      savedTimerRef.current = null
    }
    setStatus('saving')
    setError(null)
    const err = await saveActive(pid, next)
    if (err) {
      setError(err)
      setStatus('error')
      return
    }
    setStatus('saved')
    savedTimerRef.current = window.setTimeout(() => {
      savedTimerRef.current = null
      setStatus('idle')
    }, SAVED_HOLD_MS)
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

  const statusPill = (
    <>
      {status === 'saving' && <Reminder form="inline" intent="note">saving…</Reminder>}
      {status === 'saved'  && <Reminder form="inline" intent="tip">saved</Reminder>}
    </>
  )

  if (fields.length === 0) {
    return (
      <div>
        <div className="ql-fields-lab">fields {statusPill}</div>
        <div className="ql-edit-empty">
          还没字段。仅 notes 也能工作（适用于分类、匹配等无须结构化输出的任务）。需要结构化输出时点 + add fields。
        </div>
        <FooterAdd onAdd={handleAdd} disabled={status === 'saving'} label="+ add fields" />
        {status === 'error' && error && <ErrorBanner err={error} />}
      </div>
    )
  }

  return (
    <div className="ql-edit-list">
      <div className="ql-fields-lab">fields {statusPill}</div>
      {fields.map((f, idx) => (
        <SchemaCardEditor
          key={`${f.name}-${idx}`}
          field={f}
          onChange={(patch) => handleChange(idx, patch)}
          onDelete={() => handleDelete(idx)}
        />
      ))}
      <FooterAdd onAdd={handleAdd} disabled={status === 'saving'} />
      {status === 'error' && error && <ErrorBanner err={error} />}
    </div>
  )
}

function FooterAdd({ onAdd, disabled, label }: { onAdd: () => void; disabled?: boolean; label?: string }) {
  return (
    <div className="ql-edit-foot">
      <button type="button" className="ql-edit-add" onClick={onAdd} disabled={disabled}>
        {label ?? '+ field'}
      </button>
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
