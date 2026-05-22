import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronRight } from 'lucide-react'
import './usermenu.css'

// Heroicons outline `globe-alt` — claude.ai uses this exact icon for the
// Language row. Lucide's `Globe` has a different meridian geometry; inlining
// the heroicons path lets us match pixel-for-pixel.
function GlobeAlt({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M12 21a9.004 9.004 0 0 0 8.716-6.747M12 21a9.004 9.004 0 0 1-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 0 1 7.843 4.582M12 3a8.997 8.997 0 0 0-7.843 4.582m15.686 0A11.953 11.953 0 0 1 12 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0 1 21 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0 1 12 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 0 1 3 12c0-1.605.42-3.113 1.157-4.418" />
    </svg>
  )
}

// Fixed identity for now — wired into the popover header.
// (Multi-user auth lives downstream; spec asks for a placeholder.)
const USER_EMAIL = 'docai@piaozone.com'

const LANG_KEY = 'emerge.ui.lang'
type Lang = 'en' | 'zh'
// Single-label rows, claude.ai-style: native script + optional region in parens.
// The sub-popover does NOT carry a second muted "English/Simplified Chinese"
// hint column — that produced cramped two-column rows and "中..." truncation.
const LANG_OPTIONS: { value: Lang; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'zh', label: '中文（简体）' },
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

// Short label for the main popover's "Language → English" hint column.
// Strips the parenthetical region — keeps the row trim.
function labelForLang(l: Lang): string {
  if (l === 'zh') return '中文'
  return 'English'
}

type Variant = 'expanded' | 'rail'
type Coord = { top: number; left: number }

type Props = { variant?: Variant }

const POP_W = 260
const SUB_W = 200

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
          <GlobeAlt size={16} className="up-row-ic" />
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
