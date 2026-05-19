// Inline editor for prompts/active. Always-on edit; blur=save via store.
// Read-only branches (versions/{id}, prompts/{id}) use FieldCard instead.

import { useEffect, useRef, useState } from 'react'
import { useSchema, type SchemaField, type SaveError } from '../../stores/schema'

// `date / date-time / time` are virtual: selecting one patches the field to
// {type:'string', format:'…'}. Internally we keep type=='string' and lift the
// format up in the dropdown.
const TYPES = ['string', 'integer', 'number', 'boolean', 'date', 'date-time', 'time', 'object', 'array'] as const
type TypeName = (typeof TYPES)[number]

// Subset of TYPES used as the array.items type sub-selector. Nested
// `array<array>` is allowed by the backend but the editor doesn't expose it —
// any user who genuinely needs that can drop to raw JSON. Object/array
// nesting via properties (e.g. `line_items[].address.country`) is fully
// supported through the recursive ChildrenEditor.
const ITEMS_TYPES = ['string', 'integer', 'number', 'boolean', 'object'] as const
type ItemsTypeName = (typeof ITEMS_TYPES)[number]

const NAME_RE = /^[a-zA-Z][a-zA-Z0-9_]*$/

function isValidName(name: string): boolean {
  return NAME_RE.test(name)
}

function csvSplit(v: string): string[] {
  return v.split(',').map(s => s.trim()).filter(s => s.length > 0)
}

function csvJoin(arr?: string[] | null): string {
  return (arr ?? []).join(', ')
}

function emptyField(name: string | null = 'new_field'): SchemaField {
  return {
    name,
    type: 'string',
    description: '',
    required: false,
    format: null,
    enum: null,
    properties: null,
    items: null,
  }
}

function emptyObjectChild(name: string): SchemaField {
  return emptyField(name)
}

function emptyArrayItems(innerType: ItemsTypeName): SchemaField {
  const base: SchemaField = { name: null, type: innerType, description: '', required: false, format: null, enum: null, properties: null, items: null }
  if (innerType === 'object') {
    base.properties = [emptyObjectChild('sub_field')]
  }
  return base
}

// Translate a virtual UI type into a SchemaField patch.
function patchForType(prev: SchemaField, t: TypeName): Partial<SchemaField> {
  // Virtual string+format entries
  if (t === 'date' || t === 'date-time' || t === 'time') {
    return { type: 'string', format: t, properties: null, items: null }
  }
  if (t === 'object') {
    const existing = prev.properties
    return {
      type: 'object',
      format: null,
      enum: null,
      properties: existing && existing.length > 0 ? existing : [emptyObjectChild('sub_field')],
      items: null,
    }
  }
  if (t === 'array') {
    const existing = prev.items
    return {
      type: 'array',
      format: null,
      enum: null,
      properties: null,
      items: existing ?? emptyArrayItems('string'),
    }
  }
  // Plain scalar — wipe nested + format/enum-irrelevant carry
  return {
    type: t,
    format: null,
    enum: t === 'string' ? prev.enum ?? null : null,
    properties: null,
    items: null,
  }
}

// Map the SchemaField to the dropdown's virtual type value.
function virtualType(f: SchemaField): TypeName {
  if (f.type === 'string' && (f.format === 'date' || f.format === 'date-time' || f.format === 'time')) {
    return f.format
  }
  if (TYPES.includes(f.type as TypeName)) return f.type as TypeName
  return 'string'
}

interface Props {
  pid: string
  fields: SchemaField[]
}

export default function SchemaFieldEditor({ pid, fields }: Props) {
  // Save state lives in the store now so the QuickLookHeader can render a
  // pinned status pill that stays visible while this list scrolls. The
  // ErrorBanner inside the list still reads error_code + message from the
  // same source (saveError keyed by pid).
  const saveActive = useSchema(s => s.saveActive)
  const status = useSchema(s => s.saveStatus[pid] ?? 'idle')
  const error = useSchema(s => s.saveError[pid] ?? null)
  // Track the most-recently inserted card by index so its initial mount can
  // surface the enum row by default — that's the "configuring from scratch"
  // moment. Existing cards without enum keep no enum UI at all.
  const [freshIdx, setFreshIdx] = useState<number | null>(null)

  const commit = (next: SchemaField[]) => {
    // saveActive owns the saving → saved/error transitions; we don't need to
    // await the result for UI feedback. Errors propagate via the store's
    // saveStatus + saveError.
    void saveActive(pid, next)
  }

  const handleChange = (index: number, patch: Partial<SchemaField>) => {
    const next = fields.map((f, i) => i === index ? { ...f, ...patch } : f)
    commit(next)
  }

  const handleDelete = (index: number) => {
    if (freshIdx !== null) {
      if (freshIdx === index) setFreshIdx(null)
      else if (freshIdx > index) setFreshIdx(freshIdx - 1)
    }
    commit(fields.filter((_, i) => i !== index))
  }

  const pickFreshName = () => {
    let n = 1
    let name = 'new_field'
    const taken = new Set(fields.map(f => f.name).filter((s): s is string => !!s))
    while (taken.has(name)) { n += 1; name = `new_field_${n}` }
    return name
  }

  const handleAdd = () => {
    setFreshIdx(fields.length)
    commit([...fields, emptyField(pickFreshName())])
  }

  const handleInsertAt = (idx: number) => {
    setFreshIdx(idx)
    const name = pickFreshName()
    const next = [...fields.slice(0, idx), emptyField(name), ...fields.slice(idx)]
    commit(next)
  }

  if (fields.length === 0) {
    return (
      <div>
        <div className="ql-fields-lab">fields</div>
        <div className="ql-edit-empty">
          还没字段。仅 notes 也能工作（适用于分类、匹配等无须结构化输出的任务）。需要结构化输出时点 + 添加。
        </div>
        <FooterAdd onAdd={handleAdd} disabled={status === 'saving'} />
        {status === 'error' && error && <ErrorBanner err={error} />}
      </div>
    )
  }

  return (
    <div className="ql-edit-list">
      <div className="ql-fields-lab">fields</div>
      {fields.map((f, idx) => (
        <SchemaCardEditor
          key={`${f.name ?? '_'}-${idx}`}
          field={f}
          onChange={(patch) => handleChange(idx, patch)}
          onDelete={() => handleDelete(idx)}
          onInsertAfter={() => handleInsertAt(idx + 1)}
          isFresh={idx === freshIdx}
        />
      ))}
      <FooterAdd onAdd={handleAdd} disabled={status === 'saving'} />
      {status === 'error' && error && <ErrorBanner err={error} />}
    </div>
  )
}

function FooterAdd({ onAdd, disabled }: { onAdd: () => void; disabled?: boolean }) {
  return (
    <div className="ql-edit-foot">
      <button
        type="button"
        className="ql-edit-add"
        onClick={onAdd}
        disabled={disabled}
        aria-label="add field"
        title="add field"
      >+</button>
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
  /** When true, this card represents an array.items element — the name editor
   *  is hidden (JSON Schema array elements have no name). */
  nameless?: boolean
  /** Render a hover-visible `+` on the card's bottom edge that inserts a new
   *  sibling field below this one. Only wired on top-level cards. */
  onInsertAfter?: () => void
  /** True only for the card that was just inserted via the parent's `+`.
   *  Surfaces the enum row by default at mount so the new field can be
   *  configured end-to-end in one place. Existing cards default to hiding
   *  enum (and never auto-expose it) since most fields don't use enum. */
  isFresh?: boolean
}

function SchemaCardEditor({ field, onChange, onDelete, nameless = false, onInsertAfter, isFresh = false }: CardProps) {
  const nameRef = useRef<HTMLSpanElement>(null)
  const descRef = useRef<HTMLSpanElement>(null)
  const enRef = useRef<HTMLSpanElement>(null)
  const [nameError, setNameError] = useState<string | null>(null)
  const hasEnum = (field.enum?.length ?? 0) > 0
  // Initialized once at mount: open if the field already carries enum values
  // (load from storage / tool-edit) or this card is the just-inserted one.
  // Stays open after that — never auto-collapses mid-session even if the user
  // clears the enum; the explicit `×` is how they dismiss it.
  const [enumOpen, setEnumOpen] = useState(() => hasEnum || isFresh)
  // Tool-driven prompt edits may add enum to an existing card; widen on that.
  useEffect(() => { if (hasEnum) setEnumOpen(true) }, [hasEnum])

  useEffect(() => {
    if (nameRef.current && nameRef.current !== document.activeElement) {
      nameRef.current.textContent = field.name ?? ''
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

  const vt = virtualType(field)
  const isObject = field.type === 'object'
  const isArray = field.type === 'array'
  const isString = field.type === 'string'
  const itemsType: ItemsTypeName = (field.items?.type as ItemsTypeName) ?? 'string'
  const arrayItemsIsObject = isArray && field.items?.type === 'object'

  return (
    <div className="ql-edit-card">
      <div className="ql-edit-head">
        {!nameless && (
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
                e.currentTarget.textContent = field.name ?? ''
                return
              }
              if (!isValidName(v)) {
                setNameError('letters/digits/underscore only; must start with a letter')
                e.currentTarget.textContent = field.name ?? ''
                return
              }
              setNameError(null)
              if (v !== field.name) onChange({ name: v })
            }}
          >
            {field.name ?? ''}
          </span>
        )}
        <select
          className="ql-edit-type"
          value={vt}
          onChange={(e) => {
            const t = e.target.value as TypeName
            onChange(patchForType(field, t))
          }}
        >
          {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        {isArray && (
          <select
            className="ql-edit-type"
            value={itemsType}
            onChange={(e) => {
              const it = e.target.value as ItemsTypeName
              onChange({ items: emptyArrayItems(it) })
            }}
            title="array item type"
          >
            {ITEMS_TYPES.map(t => <option key={t} value={t}>items: {t}</option>)}
          </select>
        )}
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
          aria-label={`delete field ${field.name ?? 'item'}`}
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
        // innerText (not textContent): Enter inside contentEditable inserts
        // <br>/<div>; textContent skips those entirely, so multi-line input
        // round-trips to the server as a single squashed line.
        onBlur={(e) => {
          const v = e.currentTarget.innerText ?? ''
          if (v !== (field.description ?? '')) onChange({ description: v })
        }}
      >
        {field.description ?? ''}
      </span>

      {isString && enumOpen && (
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
          <button
            type="button"
            className="ql-edit-row-clear"
            onClick={() => {
              if (hasEnum) onChange({ enum: null })
              setEnumOpen(false)
            }}
            aria-label="remove enum"
            title="remove enum"
          >×</button>
        </div>
      )}

      {isObject && (
        <ChildrenEditor
          items={field.properties ?? []}
          onChange={(next) => onChange({ properties: next })}
        />
      )}

      {isArray && arrayItemsIsObject && field.items && (
        <ChildrenEditor
          items={field.items.properties ?? []}
          onChange={(next) => onChange({ items: { ...field.items!, properties: next } })}
        />
      )}

      {isArray && !arrayItemsIsObject && field.items && (
        <ArrayScalarItemEditor
          item={field.items}
          onChange={(patch) => onChange({ items: { ...field.items!, ...patch } })}
        />
      )}

      {onInsertAfter && (
        <button
          type="button"
          className="ql-edit-insert"
          onClick={onInsertAfter}
          aria-label="insert field below"
          title="insert field below"
        >+</button>
      )}
    </div>
  )
}

function ArrayScalarItemEditor({
  item,
  onChange,
}: {
  item: SchemaField
  onChange: (patch: Partial<SchemaField>) => void
}) {
  const descRef = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (descRef.current && descRef.current !== document.activeElement) {
      descRef.current.textContent = item.description ?? ''
    }
  }, [item.description])
  return (
    <div className="ql-edit-children">
      <div className="ql-edit-children-lab">items</div>
      <span
        ref={descRef}
        className={`ql-edit-desc${item.description ? '' : ' empty'}`}
        data-placeholder="describe a single array element"
        contentEditable
        suppressContentEditableWarning
        onBlur={(e) => {
          const v = e.currentTarget.innerText ?? ''
          if (v !== (item.description ?? '')) onChange({ description: v })
        }}
      >
        {item.description ?? ''}
      </span>
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
    if (items.length <= 1) return
    onChange(items.filter((_, i) => i !== idx))
  }
  const handleAdd = () => {
    let n = 1
    let name = 'sub_field'
    const taken = new Set(items.map(c => c.name).filter((s): s is string => !!s))
    while (taken.has(name)) { n += 1; name = `sub_field_${n}` }
    onChange([...items, emptyObjectChild(name)])
  }
  return (
    <div className="ql-edit-children">
      <div className="ql-edit-children-lab">properties</div>
      {items.map((c, idx) => (
        <SchemaCardEditor
          key={`${c.name ?? '_'}-${idx}`}
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
