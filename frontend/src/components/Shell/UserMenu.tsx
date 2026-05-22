import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronRight, Globe } from 'lucide-react'
import './usermenu.css'

// Fixed identity for now — wired into the popover header.
// (Multi-user auth lives downstream; spec asks for a placeholder.)
const USER_EMAIL = 'docai@piaozone.com'

const LANG_KEY = 'emerge.ui.lang'
type Lang = 'en' | 'zh'
const LANG_OPTIONS: { value: Lang; label: string; hint: string }[] = [
  { value: 'en', label: 'English',  hint: 'English' },
  { value: 'zh', label: '中文',      hint: 'Simplified Chinese' },
]

function readLang(): Lang {
  try {
    const v = localStorage.getItem(LANG_KEY)
    if (v === 'en' || v === 'zh') return v
  } catch { /* ignore */ }
  return 'en'
}

function initialsFromEmail(email: string): string {
  const local = email.split('@')[0] ?? ''
  const ch = local.replace(/[^a-zA-Z0-9]/g, '')[0] ?? '?'
  return ch.toUpperCase()
}

function labelForLang(l: Lang): string {
  return LANG_OPTIONS.find(o => o.value === l)?.label ?? 'English'
}

type Variant = 'expanded' | 'rail'
type Coord = { top: number; left: number }

type Props = { variant?: Variant }

const POP_W = 260
const SUB_W = 180

/**
 * Avatar button (bottom-left of the sidebar / rail) + two-level popover.
 *
 * Variants:
 *   - `rail`     → 36×36 avatar centered in the 52px rail.
 *   - `expanded` → avatar + email row, fills sidebar width.
 *
 * Popover is rendered into a portal on document.body with `position:fixed`
 * so it escapes the rail's `overflow:hidden`. Position is computed from the
 * trigger's `getBoundingClientRect()` on open.
 *
 * Two-level menu: the main popover shows identity + a "Language" row with a
 * chevron. Clicking that row opens a sub-popover (positioned next to the row)
 * with the actual language options. Mirrors claude.ai's submenu pattern.
 */
export default function UserMenu({ variant = 'expanded' }: Props) {
  const [open, setOpen] = useState(false)
  const [subOpen, setSubOpen] = useState(false)
  const [lang, setLang] = useState<Lang>(() => readLang())
  const [popPos, setPopPos] = useState<Coord | null>(null)
  const [subPos, setSubPos] = useState<Coord | null>(null)

  const btnRef = useRef<HTMLButtonElement>(null)
  const popRef = useRef<HTMLDivElement>(null)
  const subRef = useRef<HTMLDivElement>(null)
  const langRowRef = useRef<HTMLButtonElement>(null)
  // Tracks the deferred sub-menu close so a stray onMouseLeave doesn't yank
  // the submenu while the cursor is in transit to it.
  const subCloseTimer = useRef<number | null>(null)

  const cancelSubClose = useCallback(() => {
    if (subCloseTimer.current !== null) {
      window.clearTimeout(subCloseTimer.current)
      subCloseTimer.current = null
    }
  }, [])
  const scheduleSubClose = useCallback(() => {
    cancelSubClose()
    subCloseTimer.current = window.setTimeout(() => setSubOpen(false), 140)
  }, [cancelSubClose])
  const openSubNow = useCallback(() => { cancelSubClose(); setSubOpen(true) }, [cancelSubClose])

  // Compute popup position from trigger rect. Runs after the popup mounts so
  // we can read its actual height for above-button placement.
  useLayoutEffect(() => {
    if (!open) { setPopPos(null); return }
    const b = btnRef.current?.getBoundingClientRect()
    if (!b) return
    const popH = popRef.current?.getBoundingClientRect().height ?? 180
    if (variant === 'rail') {
      // Right of the 52px rail, bottom-aligned with the avatar.
      setPopPos({ top: Math.max(8, b.bottom - popH), left: b.right + 6 })
    } else {
      // Above the avatar row, left-aligned. Clamp to viewport top.
      setPopPos({ top: Math.max(8, b.top - popH - 6), left: b.left })
    }
  }, [open, variant])

  // Sub-popover position keyed off the Language row.
  useLayoutEffect(() => {
    if (!subOpen) { setSubPos(null); return }
    const r = langRowRef.current?.getBoundingClientRect()
    if (!r) return
    const subH = subRef.current?.getBoundingClientRect().height ?? 90
    let left = r.right + 4
    // Flip to left side if overflowing viewport right edge.
    if (left + SUB_W > window.innerWidth - 8) left = r.left - SUB_W - 4
    const top = Math.min(Math.max(8, r.top - 4), window.innerHeight - subH - 8)
    setSubPos({ top, left })
  }, [subOpen])

  // Outside click + Escape close. Trigger and both popovers are "inside".
  useEffect(() => {
    if (!open) return
    function onMouseDown(e: MouseEvent) {
      const t = e.target as Node | null
      if (!t) return
      if (btnRef.current?.contains(t)) return
      if (popRef.current?.contains(t)) return
      if (subRef.current?.contains(t)) return
      setSubOpen(false)
      setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (subOpen) setSubOpen(false)
        else setOpen(false)
      }
    }
    // Defer one tick so the click that opened us doesn't immediately close us.
    const id = setTimeout(() => window.addEventListener('mousedown', onMouseDown), 0)
    window.addEventListener('keydown', onKey)
    return () => {
      clearTimeout(id)
      window.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [open, subOpen])

  const pickLang = useCallback((next: Lang) => {
    setLang(next)
    try { localStorage.setItem(LANG_KEY, next) } catch { /* ignore */ }
    try { window.dispatchEvent(new CustomEvent('emerge:lang', { detail: next })) } catch { /* ignore */ }
    cancelSubClose()
    setSubOpen(false)
    setOpen(false)
  }, [cancelSubClose])

  // Tear down any pending sub-close timer when the main popover closes.
  useEffect(() => { if (!open) cancelSubClose() }, [open, cancelSubClose])
  // And on unmount.
  useEffect(() => () => cancelSubClose(), [cancelSubClose])

  const initial = initialsFromEmail(USER_EMAIL)
  const wrapperClass = variant === 'rail' ? 'user-menu rail' : 'user-menu expanded'

  const popover = open && (
    <div
      ref={popRef}
      className="user-pop"
      role="menu"
      style={popPos
        ? { position: 'fixed', top: popPos.top, left: popPos.left, width: POP_W }
        : { position: 'fixed', visibility: 'hidden', width: POP_W }}
      onClick={e => e.stopPropagation()}
    >
      <div className="up-email-pill">{USER_EMAIL}</div>
      <div className="up-section">
        <button
          ref={langRowRef}
          type="button"
          role="menuitem"
          aria-haspopup="menu"
          aria-expanded={subOpen}
          className={'up-row sub-trigger' + (subOpen ? ' on' : '')}
          onClick={() => (subOpen ? setSubOpen(false) : openSubNow())}
          onMouseEnter={openSubNow}
          onMouseLeave={scheduleSubClose}
        >
          <Globe size={16} strokeWidth={1.75} className="up-row-ic" />
          <span className="up-row-label">Language</span>
          <span className="up-row-hint">{labelForLang(lang)}</span>
          <ChevronRight size={14} strokeWidth={1.75} className="up-row-chev" />
        </button>
      </div>
    </div>
  )

  const submenu = open && subOpen && (
    <div
      ref={subRef}
      className="user-pop user-pop-sub"
      role="menu"
      style={subPos
        ? { position: 'fixed', top: subPos.top, left: subPos.left, width: SUB_W }
        : { position: 'fixed', visibility: 'hidden', width: SUB_W }}
      onClick={e => e.stopPropagation()}
      onMouseEnter={cancelSubClose}
      onMouseLeave={scheduleSubClose}
    >
      <div className="up-section">
        {LANG_OPTIONS.map(opt => (
          <button
            key={opt.value}
            type="button"
            role="menuitemradio"
            aria-checked={lang === opt.value}
            className={'up-row' + (lang === opt.value ? ' on' : '')}
            onClick={() => pickLang(opt.value)}
          >
            <span className="up-row-label">{opt.label}</span>
            <span className="up-row-hint">{opt.hint}</span>
            {lang === opt.value && <Check size={14} strokeWidth={2} className="up-row-check" />}
          </button>
        ))}
      </div>
    </div>
  )

  return (
    <div className={wrapperClass}>
      <button
        ref={btnRef}
        type="button"
        className={'user-btn' + (open ? ' on' : '')}
        onClick={() => { setSubOpen(false); setOpen(o => !o) }}
        aria-label="Account menu"
        aria-haspopup="menu"
        aria-expanded={open}
        title={USER_EMAIL}
      >
        <span className="avatar" aria-hidden="true">{initial}</span>
        {variant === 'expanded' && (
          <span className="email">{USER_EMAIL}</span>
        )}
      </button>

      {popover && createPortal(popover, document.body)}
      {submenu && createPortal(submenu, document.body)}
    </div>
  )
}
