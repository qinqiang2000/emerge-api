// frontend/src/components/Empty/EmptyHero.tsx
import { useState } from 'react'

import type { UnboundChatSummary } from '../../lib/api'

const STARTERS = [
  'Extract invoices from these PDFs — vendor, totals, line items',
  "Build me a schema, then I'll edit it before extraction",
  'Pull contract terms — parties, effective date, renewal clause',
]

const IS_MAC =
  typeof navigator !== 'undefined' &&
  /Mac|iPhone|iPad|iPod/i.test(
    (navigator as { userAgentData?: { platform?: string } }).userAgentData?.platform ||
      navigator.platform ||
      navigator.userAgent,
  )

/** Cheap "<n>m / <n>h / yesterday / <date>" formatter. Mirrors the popover's
 *  formatChatTs spirit but compresses harder for the empty-hero strip — the
 *  strip is one row, so every char counts. */
function formatRelTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const diffMin = Math.round((now.getTime() - d.getTime()) / 60_000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m`
  const diffHr = Math.round(diffMin / 60)
  if (diffHr < 24 && d.toDateString() === now.toDateString()) return `${diffHr}h`
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return 'yesterday'
  const sameYear = d.getFullYear() === now.getFullYear()
  return d.toLocaleDateString([], sameYear
    ? { month: 'short', day: '2-digit' }
    : { year: 'numeric', month: 'short', day: '2-digit' })
}

interface Props {
  projectName?: string
  onAttach: (files: File[]) => void
  onStarter: (text: string) => void
  /** Most-recent unbound chats (newest-first). Up to 5 are rendered as a
   *  quiet single-row strip above the tagline. Hidden entirely when empty —
   *  the example chips already serve the "you can start typing" cue. */
  recentConversations?: UnboundChatSummary[]
  /** Click handler for a strip row. Receives the unbound chat id; caller
   *  navigates to `/c/<cid>`. */
  onOpenConversation?: (chatId: string) => void
  /** Click handler for the "See all" link — opens the popover for the full
   *  list. Optional so callers without a popover binding can omit it. */
  onSeeAllConversations?: () => void
}

export default function EmptyHero({
  projectName = '',
  onAttach,
  onStarter,
  recentConversations,
  onOpenConversation,
  onSeeAllConversations,
}: Props) {
  const [dragOver, setDragOver] = useState(false)

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(true)
  }

  function handleDragLeave() {
    setDragOver(false)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) onAttach(files)
  }

  const eyebrow = projectName ? `~/projects/${projectName}/` : '~/projects/'

  // Up to 5 strip rows — anything beyond is reachable via "See all".
  const stripItems = (recentConversations ?? []).slice(0, 5)

  return (
    <div className="empty-hero">
      {stripItems.length > 0 && onOpenConversation && (
        <div className="recent-strip" role="navigation" aria-label="Recent conversations">
          {stripItems.map((c, i) => {
            const shortcut = `${IS_MAC ? '⌘' : 'Ctrl+'}${i + 1}`
            return (
              <button
                key={c.chat_id}
                type="button"
                className="recent-item"
                onClick={() => onOpenConversation(c.chat_id)}
                title={c.label}
              >
                <span className="sep">·</span>
                <span className="lbl">{c.label}</span>
                <span className="ts">{formatRelTime(c.ts_iso)}</span>
                <span className="kbd">{shortcut}</span>
              </button>
            )
          })}
          {onSeeAllConversations && (
            <button
              type="button"
              className="recent-see-all"
              onClick={onSeeAllConversations}
            >
              See all
            </button>
          )}
        </div>
      )}
      <div className="ey">{eyebrow}</div>
      <h1>
        An empty folder, a willing agent, <em>and a stack of PDFs.</em>
      </h1>
      <p>
        Drop documents in. Tell the agent what you want. It&apos;ll derive a schema, run the first
        extractions, and come back to you for review.
      </p>
      <div
        className="invite"
        onClick={() => onStarter('/init')}
        role="button"
        tabIndex={0}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onStarter('/init') }}
      >
        <span className="cmd">/init</span>
        <span style={{ color: 'var(--ink-3)' }}>derive a schema from the first few documents</span>
        <span style={{ color: 'var(--ink-5)', marginLeft: 'auto' }}>↵</span>
      </div>
      <div
        className="drop"
        style={dragOver ? { borderColor: 'var(--ochre-2)', background: 'var(--ochre-soft)' } : undefined}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <b>drop PDFs or images here</b>
        <span>
          or run{' '}
          <span style={{ color: 'var(--ochre-2)', fontWeight: 500 }}>
            cp ~/Downloads/*.pdf docs/
          </span>
        </span>
      </div>
      <div className="starters">
        <div className="lbl">or try saying ·</div>
        {STARTERS.map((s, i) => (
          <button key={i} className="starter" onClick={() => onStarter(s)}>
            <span className="quote">&quot;</span>
            <span>{s}</span>
            <span className="arr">↵</span>
          </button>
        ))}
      </div>
    </div>
  )
}
