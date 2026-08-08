// frontend/src/components/Spine/RowMenu.tsx
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MoreVertical } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import './rowmenu.css'

export type RowAction = {
  key: string
  label: string
  icon: LucideIcon
  /** Single letter, shown right-aligned and typeable while the menu is open. */
  shortcut?: string
  danger?: boolean
  disabled?: boolean
  /** Why it's disabled. Shown as the row's title — a greyed item that won't
   *  say what's blocking it is worse than no item at all. */
  disabledReason?: string
  onSelect: () => void
}

type Coord = { top: number; left: number }

const MENU_W = 184
const ROW_H = 30

/**
 * The `⋮` affordance on a spine row: invisible until the row is hovered,
 * opens a portal menu of row actions (claude.ai's chat-row pattern).
 *
 * Why this exists in an AI-native product: chat can do everything, but
 * "delete this file" is three words the user shouldn't have to type and a
 * turn they shouldn't have to wait for. Pointer and keyboard are two more
 * clients of the same operations layer the tools speak to.
 *
 * Rendered into a portal on document.body with `position:fixed` so it escapes
 * the sidebar's `overflow:hidden`, positioned off the trigger's rect — same
 * mechanics as `UserMenu`.
 */
export default function RowMenu({
  actions,
  label,
}: {
  actions: RowAction[]
  /** Accessible name, e.g. "actions for invoice.pdf". */
  label: string
}) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<Coord | null>(null)
  const [cursor, setCursor] = useState(-1)
  const btnRef = useRef<HTMLButtonElement>(null)
  const popRef = useRef<HTMLDivElement>(null)

  const close = useCallback(() => {
    setOpen(false)
    setCursor(-1)
  }, [])

  // Focus the menu itself so ↑ ↓ / R / D / Esc land on its keydown handler.
  // Explicit rather than `autoFocus`: that attribute is only reliable on form
  // controls, and this is a div — the keyboard path would silently not work.
  //
  // Gated on `pos`, NOT just `open`: the first frame renders at
  // `visibility:hidden` while we measure, and a hidden element cannot take
  // focus. React flushes pending passive effects before the synchronous
  // re-render that `setPos` (a layout effect) schedules, so an `[open]`-only
  // effect fires against the hidden frame and the focus() is silently dropped
  // — verified in the browser, focus stayed on the trigger.
  useEffect(() => {
    if (open && pos) popRef.current?.focus()
  }, [open, pos])

  // Position under the trigger, right-aligned to it; flip above when the
  // menu would run past the viewport bottom (rows near the foot of a long
  // project list are the common case).
  useLayoutEffect(() => {
    if (!open) { setPos(null); return }
    const b = btnRef.current?.getBoundingClientRect()
    if (!b) return
    const h = popRef.current?.getBoundingClientRect().height ?? actions.length * ROW_H + 10
    const left = Math.max(8, Math.min(b.right - MENU_W, window.innerWidth - MENU_W - 8))
    const below = b.bottom + 4
    const top = below + h > window.innerHeight - 8
      ? Math.max(8, b.top - h - 4)
      : below
    setPos({ top, left })
  }, [open, actions.length])

  // Outside click / Escape / scroll close. Scroll matters here in a way it
  // doesn't for UserMenu: the spine scrolls under a fixed-position menu, so
  // a menu left open would visually detach from its row.
  useEffect(() => {
    if (!open) return
    function onMouseDown(e: MouseEvent) {
      const n = e.target as Node | null
      if (!n) return
      if (btnRef.current?.contains(n) || popRef.current?.contains(n)) return
      close()
    }
    const id = setTimeout(() => window.addEventListener('mousedown', onMouseDown), 0)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      clearTimeout(id)
      window.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [open, close])

  const enabled = actions.filter(a => !a.disabled)

  const fire = useCallback((a: RowAction) => {
    if (a.disabled) return
    close()
    a.onSelect()
  }, [close])

  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); close(); btnRef.current?.focus(); return }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!enabled.length) return
      const dir = e.key === 'ArrowDown' ? 1 : -1
      setCursor(c => {
        const idxs = actions.map((a, i) => (a.disabled ? -1 : i)).filter(i => i >= 0)
        const at = idxs.indexOf(c)
        const next = at < 0
          ? (dir > 0 ? 0 : idxs.length - 1)
          : (at + dir + idxs.length) % idxs.length
        return idxs[next]
      })
      return
    }
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      const a = actions[cursor]
      if (a) fire(a)
      return
    }
    // Type the letter shown on the row (R / D), claude.ai-style.
    if (e.key.length === 1) {
      const hit = actions.find(a => a.shortcut?.toLowerCase() === e.key.toLowerCase())
      if (hit) { e.preventDefault(); fire(hit) }
    }
  }, [actions, cursor, enabled.length, fire, close])

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        className={'row-menu-btn' + (open ? ' open' : '')}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={e => {
          // The row itself navigates on click; the ⋮ must never trigger that.
          e.stopPropagation()
          setOpen(o => !o)
          setCursor(-1)
        }}
        onKeyDown={e => {
          // While the menu is open the trigger is still a plausible focus
          // owner (Tab-in, or any future focus race), so route its keys to the
          // same handler. Closed, keys fall through — Enter / Space then do
          // their native thing and click the trigger open.
          if (!open) return
          e.stopPropagation()
          onKeyDown(e)
        }}
      >
        <MoreVertical size={14} strokeWidth={2} />
      </button>
      {open && createPortal(
        <div
          ref={popRef}
          className="row-menu-pop"
          role="menu"
          aria-label={label}
          tabIndex={-1}
          style={{
            top: pos?.top ?? -9999,
            left: pos?.left ?? -9999,
            width: MENU_W,
            visibility: pos ? 'visible' : 'hidden',
          }}
          onKeyDown={onKeyDown}
          onClick={e => e.stopPropagation()}
        >
          {actions.map((a, i) => {
            const Icon = a.icon
            return (
              <button
                key={a.key}
                type="button"
                role="menuitem"
                className={
                  'row-menu-item'
                  + (a.danger ? ' danger' : '')
                  + (i === cursor ? ' cursor' : '')
                }
                disabled={a.disabled}
                title={a.disabled ? a.disabledReason : undefined}
                onMouseEnter={() => setCursor(a.disabled ? -1 : i)}
                onClick={() => fire(a)}
              >
                <Icon size={14} strokeWidth={1.75} className="row-menu-icon" />
                <span className="row-menu-label">{a.label}</span>
                {a.shortcut && <span className="row-menu-kbd">{a.shortcut}</span>}
              </button>
            )
          })}
        </div>,
        document.body,
      )}
    </>
  )
}
