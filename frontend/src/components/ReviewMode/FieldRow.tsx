// frontend/src/components/ReviewMode/FieldRow.tsx
// T11.2 — port of review.jsx:14-46
// Confidence dots are hard-coded to 'high' (moss) — backend doesn't emit per-field
// confidence yet. See design-decisions.md 2026-05-10 entry.

import { ArrowLeftToLine } from 'lucide-react'
import { useRef, useState, useEffect } from 'react'

export interface FieldRowProps {
  path: string           // dot-separated key path (e.g. "invoice_number")
  name: string           // display name
  type: string
  value: unknown
  note?: string
  evidencePage?: number | null
  active: boolean
  nested?: boolean
  readOnly?: boolean
  onChange: (value: string) => void
  onSetNote?: (note: string) => void
  onJumpToPage?: (page: number) => void
  onClick: (path: string) => void
  /** When readOnly, render a hover-revealed button to copy this single value
   *  from the prediction into the annotation. */
  onAdopt?: () => void
}

export default function FieldRow({
  path,
  name,
  type,
  value,
  note,
  evidencePage,
  active,
  nested = false,
  readOnly = false,
  onChange,
  onSetNote,
  onJumpToPage,
  onClick,
  onAdopt,
}: FieldRowProps) {
  const [showNotes, setShowNotes] = useState(false)
  const valRef = useRef<HTMLSpanElement>(null)
  const noteRef = useRef<HTMLSpanElement>(null)

  // Show notes field when there's a note or the row is active
  const notesVisible = showNotes || !!note || active

  const displayValue = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value)

  // Capture the value once on mount for edited-state tracking
  const [originalValue] = useState(() => displayValue)
  // Track current live text (updated on every blur via onChange → store → re-render)
  const isEdited = displayValue !== originalValue

  // Sync value into the DOM when it changes externally (store is source of truth)
  useEffect(() => {
    if (valRef.current && valRef.current !== document.activeElement) {
      valRef.current.textContent = displayValue
    }
  }, [displayValue])

  return (
    <div
      className={`rev-fld${active ? ' active' : ''}${nested ? ' nested' : ''}`}
      onClick={() => onClick(path)}
    >
      <div className="kv">
        <div className="ktop">
          {/* Confidence dot — hard-coded to 'high' (moss) per design-decisions.md */}
          <span className="cdot" title="confidence: high (backend not yet providing per-field score)" />
          <span className="name" title={name}>{name}</span>
          <span className="ty">{type}</span>
          {evidencePage != null && (
            <button
              type="button"
              className="ev"
              aria-label={`jump to page ${evidencePage}`}
              onClick={(e) => { e.stopPropagation(); onJumpToPage?.(evidencePage) }}
            >
              p{evidencePage}
            </button>
          )}
        </div>
        <div className="valwrap">
          <span
            ref={valRef}
            className={`val${isEdited ? ' edited' : ''}`}
            contentEditable={!readOnly}
            suppressContentEditableWarning
            onFocus={() => setShowNotes(true)}
            onBlur={(e) => {
              if (!readOnly) {
                onChange(e.currentTarget.textContent ?? '')
                setShowNotes(false)
              }
            }}
          >
            {displayValue}
          </span>
          {isEdited && <span className="edstamp" title="edited">●</span>}
        </div>
      </div>
      {notesVisible && (
        <span
          ref={noteRef}
          className="notes"
          contentEditable={!readOnly}
          suppressContentEditableWarning
          onBlur={(e) => { if (!readOnly) onSetNote?.(e.currentTarget.textContent ?? '') }}
          onClick={(e) => e.stopPropagation()}
        >
          {note ?? ''}
        </span>
      )}
      {readOnly && onAdopt && (
        <button
          type="button"
          className="copy-pred-btn"
          aria-label={`copy ${name} to annotation`}
          title="copy this value to annotation"
          onClick={(e) => { e.stopPropagation(); onAdopt() }}
        >
          <ArrowLeftToLine size={11} strokeWidth={1.7} />
          <span>use</span>
        </button>
      )}
    </div>
  )
}
