// frontend/src/components/Chat/ChatHistoryActions.tsx
//
// Two-chip cluster (history popover trigger + new-chat) extracted from
// ConvHeader so both the main shell header AND the review-overlay chat header
// (`rev-chat-hd`) can mount the same affordance. Variants only affect
// chrome/sizing — semantics, popover, store-hookup are identical.
//
// `variant="full"`    — main shell: 30px chip with `.tip` hover labels.
//                       Popover anchors absolute under `.conv` (legacy
//                       positioning), so it lives as a sibling of the
//                       chip wrapper inside the same parent.
// `variant="compact"` — review overlay: 24px icon-only chip that fits the
//                       26px header row. Popover anchors to the cluster's
//                       right edge (via `.rev-chat-hd-actions .hist-pop`)
//                       so it doesn't clip in a 280px-min column; it lives
//                       INSIDE the cluster so the absolute coords resolve
//                       against the cluster, not the column.

import { useEffect, useState } from 'react'

import type { ChatSummary } from '../../lib/api'

const IS_MAC =
  typeof navigator !== 'undefined' &&
  /Mac|iPhone|iPad|iPod/i.test(
    (navigator as { userAgentData?: { platform?: string } }).userAgentData?.platform ||
      navigator.platform ||
      navigator.userAgent,
  )
const NEW_CHAT_SHORTCUT = IS_MAC ? '⌘⇧O' : 'Ctrl+Shift+O'

interface Props {
  activeProject: string
  currentChatId: string
  chats: ChatSummary[]
  onNew: () => void
  onSwitch: (chatId: string) => void
  /** Called when the history popover transitions to open — parent refreshes the list. */
  onOpen?: () => void
  /** 'full' for main shell chrome (default), 'compact' for the review overlay's
   *  narrow 26px header row — icon-only chips, no `.tip` labels. */
  variant?: 'full' | 'compact'
}

function formatChatTs(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  const sameYear = d.getFullYear() === now.getFullYear()
  return d.toLocaleDateString([], sameYear ? { month: 'short', day: '2-digit' } : { year: 'numeric', month: 'short', day: '2-digit' })
}

export default function ChatHistoryActions({
  activeProject,
  currentChatId,
  chats,
  onNew,
  onSwitch,
  onOpen,
  variant = 'full',
}: Props) {
  const [open, setOpen] = useState(false)

  function toggleOpen() {
    setOpen(o => {
      const next = !o
      if (next) onOpen?.()
      return next
    })
  }

  useEffect(() => {
    if (!open) return
    function onClick(e: MouseEvent) {
      const t = e.target as Element | null
      // Match either variant's wrapper so click-outside fires correctly inside
      // the review overlay too (`.rev-chat-hd-actions`).
      if (
        !t?.closest('.hist-pop') &&
        !t?.closest('.conv-hd .hist-btn') &&
        !t?.closest('.rev-chat-hd-actions .hist-btn')
      ) setOpen(false)
    }
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') setOpen(false) }
    const id = setTimeout(() => window.addEventListener('mousedown', onClick), 0)
    window.addEventListener('keydown', onKey)
    return () => {
      clearTimeout(id)
      window.removeEventListener('mousedown', onClick)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  useEffect(() => { setOpen(false) }, [activeProject])

  const compact = variant === 'compact'
  const wrapperClass = compact ? 'rev-chat-hd-actions' : 'conv-hd'
  // Full variant uses the existing `.chip` class for the 30px button style;
  // compact variant uses bare buttons styled by `.rev-chat-hd-actions button`.
  const chipBase = compact ? '' : 'chip '

  const popover = open ? (
    <div className="hist-pop" onClick={e => e.stopPropagation()}>
      <div className="h-hd">
        <span className="lab">history</span>
        <span className="scope">{activeProject}</span>
      </div>
      {chats.length === 0 ? (
        <div className="h-empty">No sessions yet.</div>
      ) : (
        <div className="h-list">
          {chats.map(c => (
            <div
              key={c.chat_id}
              className={'h-row ' + (c.chat_id === currentChatId ? 'active' : '')}
              onClick={() => { onSwitch(c.chat_id); setOpen(false) }}
            >
              <span className="kind">{c.kind}</span>
              <span className="lbl">{c.label}</span>
              <span className="ts">{formatChatTs(c.ts_iso)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  ) : null

  return (
    <>
      <div className={wrapperClass}>
        <button
          type="button"
          className={chipBase + 'hist-btn ' + (open ? 'on' : '')}
          onClick={toggleOpen}
          aria-label="Chat history"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="8" cy="8" r="5.5" />
            <polyline points="8,4.5 8,8 10.5,9.5" />
          </svg>
          {!compact && <span className="tip">Chat history</span>}
        </button>
        <button
          type="button"
          className={chipBase.trim()}
          onClick={onNew}
          aria-label="New chat"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="8" y1="3" x2="8" y2="13" />
            <line x1="3" y1="8" x2="13" y2="8" />
          </svg>
          {!compact && (
            <span className="tip">New chat <span className="kbd">{NEW_CHAT_SHORTCUT}</span></span>
          )}
        </button>
        {/* compact variant: popover lives INSIDE the cluster so its absolute
         *  positioning resolves against the cluster (anchors right). */}
        {compact && popover}
      </div>
      {/* full variant: popover lives as a sibling — preserves the legacy
       *  absolute positioning relative to `.conv`. */}
      {!compact && popover}
    </>
  )
}
