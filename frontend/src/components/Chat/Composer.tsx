import { useState, useRef, useEffect, useMemo, type DragEvent, type KeyboardEvent } from 'react'

import SlashMenu, { COMMANDS } from './SlashMenu'

// Mac shows ⌘, everything else shows Ctrl. Falls back to non-Mac when
// `navigator` is unavailable (SSR, tests pre-jsdom-platform-shim).
const IS_MAC =
  typeof navigator !== 'undefined' &&
  /Mac|iPhone|iPad|iPod/i.test(
    (navigator as { userAgentData?: { platform?: string } }).userAgentData?.platform ||
      navigator.platform ||
      navigator.userAgent,
  )

interface Props {
  disabled: boolean
  pending: { filename: string }[]
  onAttach: (files: File[]) => void
  onSubmit: (text: string) => void
}

export default function Composer({ disabled, pending, onAttach, onSubmit }: Props) {
  const [text, setText] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const taRef = useRef<HTMLTextAreaElement>(null)

  // The autocomplete menu is open only while the user is still typing a command
  // name. Once a full command prefixes the text (`/eval` or `/eval …`), the
  // menu closes and plain Enter inserts a newline like a normal textarea —
  // only ⌘/Ctrl+Enter submits, matching the footer hint.
  const completedCommand = COMMANDS.some(c => text === c.cmd || text.startsWith(c.cmd + ' '))
  const showSlash = text.startsWith('/') && !completedCommand

  // Auto-grow textarea up to 220px
  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    const max = 220
    el.style.height = Math.min(el.scrollHeight, max) + 'px'
    el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
  }, [text])

  // Reset active index when slash menu opens/closes
  useEffect(() => { setActiveIdx(0) }, [showSlash])

  const slashMatches = useMemo(() => {
    if (!showSlash) return COMMANDS
    const q = text.trim().toLowerCase()
    const filtered = COMMANDS.filter(s => s.cmd.toLowerCase().startsWith(q))
    return filtered.length ? filtered : COMMANDS
  }, [showSlash, text])

  function pickSlash(cmd: string) {
    setText(cmd + ' ')
    taRef.current?.focus()
  }

  function submit() {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSubmit(trimmed)
    setText('')
  }

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Cmd/Ctrl+Enter always submits
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
      return
    }

    if (showSlash) {
      // Arrow navigation
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveIdx(i => (i + 1) % slashMatches.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIdx(i => (i - 1 + slashMatches.length) % slashMatches.length)
        return
      }
      // Enter or Tab picks the active item (fills "<cmd> " and closes the menu).
      if ((e.key === 'Enter' || e.key === 'Tab') && !e.shiftKey) {
        e.preventDefault()
        const pick = slashMatches[Math.min(activeIdx, slashMatches.length - 1)]
        if (pick) pickSlash(pick.cmd)
        return
      }
      // Esc clears text
      if (e.key === 'Escape') {
        e.preventDefault()
        setText('')
        return
      }
    } else {
      // Plain Enter inserts a newline (default textarea behavior);
      // submission requires ⌘/Ctrl+Enter, handled at the top of this function.
      // Esc blurs
      if (e.key === 'Escape') {
        e.preventDefault()
        taRef.current?.blur()
        return
      }
    }
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    onAttach(Array.from(e.dataTransfer.files))
  }

  return (
    <div
      className="composer-wrap"
      style={dragOver ? { background: 'linear-gradient(to top, var(--paper-2) 70%, rgba(253,253,252,0))' } : undefined}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <div className="composer">
        {showSlash && (
          <SlashMenu
            query={text}
            activeIdx={activeIdx}
            onPick={pickSlash}
            onHover={setActiveIdx}
          />
        )}

        {/* Pending attachment chips */}
        {pending.length > 0 && (
          <div className="flex flex-wrap gap-1 px-3 pt-2">
            {pending.map((a, i) => (
              <span
                key={i}
                className="font-mono text-[11px] px-2 py-1 bg-paper-2 border border-rule rounded"
              >
                {a.filename}
              </span>
            ))}
          </div>
        )}

        <div className="row1">
          <span className="caret">▸</span>
          <textarea
            ref={taRef}
            rows={1}
            value={text}
            disabled={disabled}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKey}
            placeholder="say something to the agent, or type / for a command…"
          />
        </div>

        <div className="row2">
          <div className="slashes">
            <span className="slash"><b>/init</b></span>
            <span className="slash"><b>/extract</b></span>
            <span className="slash"><b>/review</b></span>
            <span className="slash"><b>/improve</b></span>
            <span className="slash"><b>/publish</b></span>
          </div>
          <div className="send">
            <kbd>{IS_MAC ? '⌘' : 'Ctrl'}</kbd><kbd>↵</kbd> send
          </div>
        </div>
      </div>
    </div>
  )
}
