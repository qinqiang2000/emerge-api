import { useState } from 'react'
import './styles.css'
import type { SchemaField } from '../../stores/schema'

interface Props {
  field: SchemaField
  defaultExpanded?: boolean
}

export default function FieldCard({ field, defaultExpanded = false }: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const hasChildren = field.type === 'array<object>' && Array.isArray(field.children) && field.children.length > 0

  return (
    <div className="ql-field">
      <div className="ql-field-head">
        <span className="ql-field-name">{field.name}</span>
        <span className="ql-field-type">{field.type}</span>
        {field.required && <span className="ql-field-required">REQUIRED</span>}
      </div>

      <div className={`ql-field-desc${field.description ? '' : ' ql-field-desc--empty'}`}>
        {field.description || '(no description)'}
      </div>

      {Array.isArray(field.enum) && field.enum.length > 0 && (
        <div className="ql-field-enum">enum · {field.enum.join(', ')}</div>
      )}

      <div className="ql-field-notes" data-testid="field-notes-hint">—</div>

      {hasChildren && (
        <>
          <button
            type="button"
            className="ql-field-disclosure"
            aria-label={`${expanded ? 'collapse' : 'expand'} ${field.name}`}
            onClick={() => setExpanded(v => !v)}
          >
            {expanded ? '▾' : '▸'}{' '}
            <span>{`children: ${field.children!.length}`}</span>
          </button>
          {expanded && (
            <div className="ql-field-children">
              {field.children!.map(child => (
                <FieldCard key={child.name} field={child} defaultExpanded={defaultExpanded} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
