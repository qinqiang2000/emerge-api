import { useEffect, useState } from 'react'

import type { ChatSummary } from '../../lib/api'

interface Props {
  activeProject: string
  currentChatId: string
  chats: ChatSummary[]
  onNew: () => void
  onSwitch: (chatId: string) => void
  /** Called when the history popover transitions to open — parent refreshes the list. */
  onOpen?: () => void
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

export default function ConvHeader({ activeProject, currentChatId, chats, onNew, onSwitch, onOpen }: Props) {
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
      if (!t?.closest('.hist-pop') && !t?.closest('.conv-hd .hist-btn')) setOpen(false)
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

  return (
    <>
      <div className="conv-hd">
        <button
          className={'chip hist-btn ' + (open ? 'on' : '')}
          onClick={toggleOpen}
          aria-label="Chat history"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="8" cy="8" r="5.5" />
            <polyline points="8,4.5 8,8 10.5,9.5" />
          </svg>
          <span className="tip">Chat history</span>
        </button>
        <button className="chip" onClick={onNew} aria-label="New chat">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="8" y1="3" x2="8" y2="13" />
            <line x1="3" y1="8" x2="13" y2="8" />
          </svg>
          <span className="tip">New chat</span>
        </button>
      </div>
      {open && (
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
      )}
    </>
  )
}
