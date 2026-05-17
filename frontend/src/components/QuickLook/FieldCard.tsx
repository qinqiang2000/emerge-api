import { useState } from 'react'
import './styles.css'
import type { SchemaField } from '../../stores/schema'

interface Props {
  field: SchemaField
  defaultExpanded?: boolean
}

function _children(field: SchemaField): SchemaField[] | null {
  // Legacy ARRAY_OBJECT shape carried `children`. New shape:
  //  - type=object → properties
  //  - type=array & items.type=object → items.properties
  if (Array.isArray(field.children) && field.children.length > 0) return field.children
  if (field.type === 'object' && Array.isArray(field.properties) && field.properties.length > 0) return field.properties
  if (field.type === 'array' && field.items?.type === 'object' && Array.isArray(field.items.properties) && field.items.properties.length > 0) {
    return field.items.properties
  }
  return null
}

function _typeLabel(field: SchemaField): string {
  if (field.type === 'string' && field.format) return `string<${field.format}>`
  if (field.type === 'array' && field.items) {
    const inner = field.items.type === 'string' && field.items.format ? `string<${field.items.format}>` : field.items.type
    return `array<${inner}>`
  }
  return field.type as string
}

export default function FieldCard({ field, defaultExpanded = false }: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const kids = _children(field)
  const hasChildren = kids !== null

  return (
    <div className="ql-field">
      <div className="ql-field-head">
        <span className="ql-field-name">{field.name}</span>
        <span className="ql-field-type">{_typeLabel(field)}</span>
        {field.required && <span className="ql-field-required">REQUIRED</span>}
      </div>

      <div className={`ql-field-desc${field.description ? '' : ' ql-field-desc--empty'}`}>
        {field.description || '(no description)'}
      </div>

      {Array.isArray(field.enum) && field.enum.length > 0 && (
        <div className="ql-field-enum">enum · {field.enum.join(', ')}</div>
      )}

      <div className="ql-field-notes" data-testid="field-notes-hint">—</div>

      {hasChildren && kids && (
        <>
          <button
            type="button"
            className="ql-field-disclosure"
            aria-label={`${expanded ? 'collapse' : 'expand'} ${field.name}`}
            onClick={() => setExpanded(v => !v)}
          >
            {expanded ? '▾' : '▸'}{' '}
            <span>{`children: ${kids.length}`}</span>
          </button>
          {expanded && (
            <div className="ql-field-children">
              {kids.map((child, i) => (
                <FieldCard key={child.name ?? `item-${i}`} field={child} defaultExpanded={defaultExpanded} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
