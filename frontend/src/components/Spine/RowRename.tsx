// frontend/src/components/Spine/RowRename.tsx
import { useEffect, useRef, useState } from 'react'

/**
 * Rename in place: the row's label becomes an input, Enter commits, Escape
 * reverts. No dialog — a modal to change one string is the kind of ceremony
 * the pointer path exists to avoid.
 *
 * `selectLen` pre-selects the first N characters. Docs pass the basename
 * length so the extension survives the first keystroke (Finder / VS Code
 * behaviour); everything else selects the whole label.
 *
 * Blur commits rather than cancels: clicking away from a field you just typed
 * into means "that's it", and an accidental discard costs the user the retype.
 * Escape is the explicit undo, and an unchanged value exits silently.
 */
export default function RowRename({
  initial,
  selectLen,
  onCommit,
  onCancel,
}: {
  initial: string
  selectLen?: number
  /** Rejecting with an Error keeps the editor open so the value can be fixed. */
  onCommit: (next: string) => Promise<void>
  onCancel: () => void
}) {
  const [value, setValue] = useState(initial)
  const [busy, setBusy] = useState(false)
  const ref = useRef<HTMLInputElement>(null)
  // Guards the blur handler: without it, the blur that follows a successful
  // Enter fires a second commit against a name that no longer exists.
  const done = useRef(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.focus()
    el.setSelectionRange(0, selectLen ?? initial.length)
  }, [initial, selectLen])

  async function commit() {
    if (done.current || busy) return
    const next = value.trim()
    if (!next || next === initial) { done.current = true; onCancel(); return }
    setBusy(true)
    try {
      await onCommit(next)
      done.current = true
    } catch {
      // Caller has surfaced the reason (toast); stay open on the bad value so
      // it can be corrected rather than retyped from scratch.
      setBusy(false)
      ref.current?.focus()
    }
  }

  return (
    <input
      ref={ref}
      className={'row-rename-input' + (busy ? ' busy' : '')}
      value={value}
      disabled={busy}
      spellCheck={false}
      autoComplete="off"
      onChange={e => setValue(e.target.value)}
      // The row underneath navigates / toggles on click; keep every event in.
      onClick={e => e.stopPropagation()}
      onMouseDown={e => e.stopPropagation()}
      onBlur={() => { void commit() }}
      onKeyDown={e => {
        e.stopPropagation()
        if (e.key === 'Enter') { e.preventDefault(); void commit() }
        else if (e.key === 'Escape') { e.preventDefault(); done.current = true; onCancel() }
      }}
    />
  )
}
