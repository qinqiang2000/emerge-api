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
//
// Phase-2 unbound chats: a `scope` prop now switches the popover header
// label (`IN PROJECT` / `UNBOUND`). The caller is responsible for picking
// which chat list to hand in — see `useChatPopoverContents` below.

import { useEffect, useState } from 'react'

import type { ChatSummary } from '../../lib/api'
import { useProjects } from '../../stores/projects'
import { useChat } from '../../stores/chat'
import { useI18n, useT } from '../../i18n'

const IS_MAC =
  typeof navigator !== 'undefined' &&
  /Mac|iPhone|iPad|iPod/i.test(
    (navigator as { userAgentData?: { platform?: string } }).userAgentData?.platform ||
      navigator.platform ||
      navigator.userAgent,
  )
const NEW_CHAT_SHORTCUT = IS_MAC ? '⌘⇧O' : 'Ctrl+Shift+O'
const HISTORY_SHORTCUT = IS_MAC ? '⌘⇧H' : 'Ctrl+Shift+H'

/** Custom DOM event name that opens the (full-variant) popover from anywhere.
 *  Used by the empty-hero "See all" link so the popover surfaces without
 *  requiring a ref handoff up the component tree. Listeners live inside
 *  `ChatHistoryActions` itself. */
const OPEN_POPOVER_EVENT = 'emerge:open-chat-popover'

/** Imperatively open the chat-history popover from any caller. Returns a
 *  cleanup-free promise so the caller can `void openChatPopover()`. */
export function openChatPopover(): void {
  window.dispatchEvent(new CustomEvent(OPEN_POPOVER_EVENT))
}

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
  /** Drives the popover header label:
   *   - `'project'` → "IN PROJECT" + active project name on the right
   *   - `'unbound'` → "UNBOUND"
   *  Defaults to `'project'` so existing callers compile unchanged. */
  scope?: 'project' | 'unbound'
}

function formatChatTs(iso: string, t: (k: string) => string, locale: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) {
    return d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return t('chathistory.yesterday')
  const sameYear = d.getFullYear() === now.getFullYear()
  return d.toLocaleDateString(locale, sameYear ? { month: 'short', day: '2-digit' } : { year: 'numeric', month: 'short', day: '2-digit' })
}

export default function ChatHistoryActions({
  activeProject,
  currentChatId,
  chats,
  onNew,
  onSwitch,
  onOpen,
  variant = 'full',
  scope = 'project',
}: Props) {
  const t = useT()
  const locale = useI18n(s => s.locale)
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)

  function toggleOpen() {
    setOpen(o => {
      const next = !o
      if (next) onOpen?.()
      return next
    })
  }

  // Cmd/Ctrl+Shift+H → toggle history popover (always-on)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.code === 'KeyH') {
        e.preventDefault()
        setOpen(o => {
          const next = !o
          if (next) onOpen?.()
          return next
        })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onOpen])

  // Click-outside + Escape to close
  useEffect(() => {
    if (!open) return
    function onClick(e: MouseEvent) {
      const target = e.target as Element | null
      // Match either variant's wrapper so click-outside fires correctly inside
      // the review overlay too (`.rev-chat-hd-actions`).
      if (
        !target?.closest('.hist-pop') &&
        !target?.closest('.conv-hd .hist-btn') &&
        !target?.closest('.rev-chat-hd-actions .hist-btn')
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

  // Programmatic open hook: EmptyHero's "See all" link dispatches
  // `emerge:open-chat-popover` so the popover surfaces without the user
  // having to find the corner chip. Custom event keeps the coupling
  // one-way + scope-aware (the popover that listens is the one currently
  // mounted, which by App.tsx routing matches the user's mode). Only the
  // `full` variant listens — the review-overlay compact variant has its
  // own context and shouldn't pop from a hero click.
  useEffect(() => {
    if (variant !== 'full') return
    const handler = () => {
      onOpen?.()
      setOpen(true)
    }
    window.addEventListener(OPEN_POPOVER_EVENT, handler)
    return () => window.removeEventListener(OPEN_POPOVER_EVENT, handler)
  }, [variant, onOpen])

  // ↑/↓/Enter keyboard navigation inside the popover
  useEffect(() => {
    if (!open || chats.length === 0) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveIdx(i => Math.min(i + 1, chats.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIdx(i => Math.max(i - 1, 0))
      } else if (e.key === 'Enter' && activeIdx >= 0 && chats[activeIdx]) {
        e.preventDefault()
        onSwitch(chats[activeIdx].chat_id)
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, chats, activeIdx, onSwitch])

  // Reset keyboard cursor when popover closes or project changes
  useEffect(() => { if (!open) setActiveIdx(-1) }, [open])
  useEffect(() => { setOpen(false) }, [activeProject])

  const compact = variant === 'compact'
  const wrapperClass = compact ? 'rev-chat-hd-actions' : 'conv-hd'
  // Full variant uses the existing `.chip` class for the 30px button style;
  // compact variant uses bare buttons styled by `.rev-chat-hd-actions button`.
  const chipBase = compact ? '' : 'chip '

  // Scope label shown in the popover header. Single uppercase word, no
  // decorations — matches the visual weight of the existing "history" label.
  const scopeLabel = scope === 'project' ? t('chathistory.inProject') : t('chathistory.unbound')
  // Right-hand scope hint: project name for project scope, intentionally
  // blank for unbound (the "UNBOUND" label is already the disambiguator).
  const scopeHint = scope === 'project' ? activeProject : ''
  const emptyHint = scope === 'project' ? t('chathistory.empty.project') : t('chathistory.empty.unbound')

  const popover = open ? (
    <div className="hist-pop" onClick={e => e.stopPropagation()}>
      <div className="h-hd">
        <span className="lab">{scopeLabel}</span>
        <span className="scope">{scopeHint}</span>
      </div>
      {chats.length === 0 ? (
        <div className="h-empty">{emptyHint}</div>
      ) : (
        <div className="h-list">
          {chats.map((c, idx) => (
            <div
              key={c.chat_id}
              className={['h-row', c.chat_id === currentChatId ? 'active' : '', idx === activeIdx ? 'focused' : ''].filter(Boolean).join(' ')}
              onClick={() => { onSwitch(c.chat_id); setOpen(false) }}
            >
              <span className="kind">{c.kind}</span>
              <span className="lbl">{c.label}</span>
              {/* live turn → pulsing dot so a chat left mid-run is recognisable */}
              {c.running && <span className="run-dot" title={t('chathistory.running')} />}
              <span className="ts">{formatChatTs(c.ts_iso, t, locale)}</span>
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
          aria-label={t('chathistory.aria')}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="8" cy="8" r="5.5" />
            <polyline points="8,4.5 8,8 10.5,9.5" />
          </svg>
          {!compact && <span className="tip">{t('chathistory.aria')} <span className="kbd">{HISTORY_SHORTCUT}</span></span>}
        </button>
        <button
          type="button"
          className={chipBase.trim()}
          onClick={onNew}
          aria-label={t('chathistory.newChat')}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="8" y1="3" x2="8" y2="13" />
            <line x1="3" y1="8" x2="13" y2="8" />
          </svg>
          {!compact && (
            <span className="tip">{t('chathistory.newChat')} <span className="kbd">{NEW_CHAT_SHORTCUT}</span></span>
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

/** Resolve the popover's listing source + the "New chat" CTA dispatch based
 *  on the current route. Lives next to `ChatHistoryActions` so callers don't
 *  hand-branch on the URL — they grab `{chats, scope, onNew, onSwitch}` and
 *  pass them straight to the component.
 *
 *  Three scopes:
 *   - `/p/<slug>` → chats inside `<slug>`; new chat mints inside `<slug>`
 *   - `/c/<cid>`  → other unbound chats; new chat mints a fresh unbound id
 *   - `/`         → recent unbound chats; "new chat" is lazy — clicking it
 *                   leaves the URL at `/`, and the first user message is
 *                   what actually creates the chat (matches today's project
 *                   "new chat" pattern).
 *
 *  The chat store actions called here (`newChat`, `switchChat`, `listChats`,
 *  `newUnboundChat`, `enterUnboundChat`, `listUnbound`) all do the right
 *  thing in their respective modes — the hook is purely glue. */
export function useChatPopoverContents(): {
  scope: 'project' | 'unbound'
  activeProject: string
  chats: ChatSummary[]
  onNew: () => void
  onSwitch: (chatId: string) => void
  onOpen: () => void
} {
  const selectedSlug = useProjects(s => s.selectedSlug)
  const projects = useProjects(s => s.projects)
  const chatsByProject = useChat(s => s.chatsByProject)
  const chatsUnbound = useChat(s => s.chatsUnbound)

  if (selectedSlug) {
    const name = projects.find(p => p.slug === selectedSlug)?.name ?? ''
    return {
      scope: 'project',
      activeProject: name,
      chats: chatsByProject[selectedSlug] ?? [],
      onNew: () => useChat.getState().newChat(selectedSlug),
      onSwitch: (cid) => useChat.getState().switchChat(selectedSlug, cid),
      onOpen: () => { void useChat.getState().listChats(selectedSlug) },
    }
  }
  // Unbound / root scope. `chatsUnbound` is the same array for both — the
  // current chat is excluded from the rendered list inside the popover by
  // its `currentChatId === c.chat_id` active-marker logic (a row is still
  // shown but flagged active rather than filtered).
  return {
    scope: 'unbound',
    activeProject: '',
    chats: chatsUnbound,
    onNew: () => {
      // Lazy mint:
      //  - on `/c/<cid>` → mint a fresh local id, App.tsx pushes `/c/<new>`
      //  - on `/` (no current unbound chat) → no-op; user is already on an
      //    empty slate. Matches the project-side "new chat" lazy pattern.
      if (useChat.getState().loadedUnboundChatId) {
        useChat.getState().newUnboundChat()
      }
    },
    onSwitch: (cid) => useChat.getState().enterUnboundChat(cid),
    onOpen: () => { void useChat.getState().listUnbound() },
  }
}
