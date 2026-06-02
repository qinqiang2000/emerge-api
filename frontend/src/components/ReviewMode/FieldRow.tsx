// frontend/src/components/ReviewMode/FieldRow.tsx
// T11.2 — port of review.jsx:14-46
// Confidence dots are hard-coded to 'high' (moss) — backend doesn't emit per-field
// confidence yet. See design-decisions.md 2026-05-10 entry.
//
// Inline note input was removed when the review chat column landed: per-doc
// note traffic is 1–2 entries on average and far better captured in NL via the
// new "/" -anchored chat column. The `notes` map still loads from disk for
// future display (e.g., hover hint), but no longer has a UI editor here.

import { ArrowLeftToLine } from 'lucide-react'
import { useRef, useState, useEffect } from 'react'
import { useT } from '../../i18n'

export interface FieldRowProps {
  path: string           // dot-separated key path (e.g. "invoice_number")
  name: string           // display name
  type: string
  value: unknown
  evidencePage?: number | null
  active: boolean
  /** Present when this field was corrected on the open doc (persisted
   *  `_corrections`). Renders a "corrected" badge + before→after on hover. */
  corrected?: { before: unknown; after: unknown }
  nested?: boolean
  readOnly?: boolean
  onChange: (value: string) => void
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
  evidencePage,
  active,
  corrected,
  nested = false,
  readOnly = false,
  onChange,
  onJumpToPage,
  onClick,
  onAdopt,
}: FieldRowProps) {
  const t = useT()
  const valRef = useRef<HTMLSpanElement>(null)

  const displayValue = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value)
  const fmt = (v: unknown): string =>
    v == null || v === '' ? t('review.tune.empty') : typeof v === 'object' ? JSON.stringify(v) : String(v)

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
      data-fpath={path}
      className={`rev-fld${active ? ' active' : ''}${nested ? ' nested' : ''}${corrected ? ' corrected' : ''}`}
      onClick={() => onClick(path)}
    >
      <div className="kv">
        <div className="ktop">
          {/* Confidence dot — hard-coded to 'high' (moss) per design-decisions.md */}
          <span className="cdot" title="confidence: high (backend not yet providing per-field score)" />
          <span className="name" title={name}>{name}</span>
          <span className="ty">{type}</span>
          {corrected && (
            <span
              className="corrbadge"
              title={`${fmt(corrected.before)} → ${fmt(corrected.after)}`}
            >
              {t('review.field.corrected')}
            </span>
          )}
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
            onBlur={(e) => {
              if (!readOnly) {
                onChange(e.currentTarget.textContent ?? '')
              }
            }}
          >
            {displayValue}
          </span>
          {isEdited && <span className="edstamp" title="edited">●</span>}
        </div>
      </div>
      {readOnly && onAdopt && (
        <button
          type="button"
          className="copy-pred-btn"
          aria-label={`copy ${name} to reviewed`}
          title="copy this value to reviewed"
          onClick={(e) => { e.stopPropagation(); onAdopt() }}
        >
          <ArrowLeftToLine size={11} strokeWidth={1.7} />
          <span>use</span>
        </button>
      )}
    </div>
  )
}
