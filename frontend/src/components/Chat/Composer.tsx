import { useState, useRef, useEffect, useMemo, type ClipboardEvent, type DragEvent, type KeyboardEvent } from 'react'

import SlashMenu, { COMMANDS } from './SlashMenu'

// Phosphor-style icons lifted from claude.ai's composer so the send/stop
// affordances are visually familiar. Both render at 14px in a 28x28 button.
const SendIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 256 256" aria-hidden>
    <path d="M208.49,120.49a12,12,0,0,1-17,0L140,69V216a12,12,0,0,1-24,0V69L64.49,120.49a12,12,0,0,1-17-17l72-72a12,12,0,0,1,17,0l72,72A12,12,0,0,1,208.49,120.49Z" />
  </svg>
)
const StopIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 256 256" aria-hidden>
    <path d="M128,20A108,108,0,1,0,236,128,108.12,108.12,0,0,0,128,20Zm0,192a84,84,0,1,1,84-84A84.09,84.09,0,0,1,128,212Zm40-112v56a12,12,0,0,1-12,12H100a12,12,0,0,1-12-12V100a12,12,0,0,1,12-12h56A12,12,0,0,1,168,100Z" />
  </svg>
)
// claude.ai's "add files" plus glyph — 20×20 in a 32×32 ghost button.
const PlusIcon = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden>
    <path d="M10 3a.5.5 0 0 1 .5.5v6h6l.1.01a.5.5 0 0 1 0 .98l-.1.01h-6v6a.5.5 0 0 1-1 0v-6h-6a.5.5 0 0 1 0-1h6v-6A.5.5 0 0 1 10 3" />
  </svg>
)
// claude.ai's close glyph — used to remove a pending attachment.
const XIcon = () => (
  <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden>
    <path d="M15.147 4.146a.5.5 0 0 1 .707.707L10.707 10l5.147 5.147a.5.5 0 0 1-.63.771l-.078-.064L10 10.707l-5.146 5.147a.5.5 0 0 1-.708-.707L9.293 10 4.146 4.853a.5.5 0 0 1 .708-.707L10 9.293z" />
  </svg>
)
const PdfIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M3 1.5h5.5L13 6v8a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1z" />
    <path d="M8.5 1.5V6H13" />
  </svg>
)
const ImageIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" />
    <circle cx="5.25" cy="6" r="1.1" />
    <path d="M2.2 12.2l3.4-3.4 3 3 2.2-2.2L14 11.6" />
  </svg>
)

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
  /** Remove the i-th pending attachment. Optional so legacy callers compile. */
  onRemove?: (index: number) => void
  /** When provided + `disabled` is true, renders a Stop pill + binds Esc at
   *  window level to cancel the in-flight turn. Optional so existing call
   *  sites (and tests) without cancel support still compile. */
  onCancel?: () => void
}

export default function Composer({ disabled, pending, onAttach, onSubmit, onRemove, onCancel }: Props) {
  const [text, setText] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const [plusOpen, setPlusOpen] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const pdfRef = useRef<HTMLInputElement>(null)
  const imgRef = useRef<HTMLInputElement>(null)
  const plusWrapRef = useRef<HTMLDivElement>(null)

  // The autocomplete menu is open only while the user is still typing a command
  // name. Once a full command prefixes the text (`/eval` or `/eval …`), the
  // menu closes and plain Enter inserts a newline like a normal textarea —
  // only ⌘/Ctrl+Enter submits, matching the footer hint.
  const completedCommand = COMMANDS.some(c => text === c.cmd || text.startsWith(c.cmd + ' '))
  const showSlash = text.startsWith('/') && !completedCommand

  // Auto-grow textarea up to 384px (claude.ai max-h-96)
  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    const max = 384
    el.style.height = Math.min(el.scrollHeight, max) + 'px'
    el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
  }, [text])

  // Reset active index when slash menu opens/closes
  useEffect(() => { setActiveIdx(0) }, [showSlash])

  // While the agent is responding (`disabled` true) and a cancel handler is
  // wired, Esc at the window level stops the turn. The textarea is disabled
  // and can't receive focus during streaming, so its own onKeyDown won't fire.
  useEffect(() => {
    if (!disabled || !onCancel) return
    const handler = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onCancel()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [disabled, onCancel])

  // Click-outside dismissal for the + menu.
  useEffect(() => {
    if (!plusOpen) return
    const handler = (e: MouseEvent) => {
      if (!plusWrapRef.current?.contains(e.target as Node)) setPlusOpen(false)
    }
    window.addEventListener('mousedown', handler)
    return () => window.removeEventListener('mousedown', handler)
  }, [plusOpen])

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

  // Paste: if the clipboard carries files (drag-from-finder, copied attachment,
  // or a screenshot blob), intercept and route through onAttach. If it's just
  // text, fall through to the textarea's default paste.
  function handlePaste(e: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(e.clipboardData?.files ?? [])
    if (files.length > 0) {
      e.preventDefault()
      onAttach(files)
    }
  }

  function handleFilePick(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    if (files.length > 0) onAttach(files)
    // reset so picking the same filename twice still fires onChange
    e.target.value = ''
  }

  return (
    <div
      className={'composer-wrap' + (dragOver ? ' dragover' : '')}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <div className="composer" onClick={(e) => {
        // claude.ai: clicking anywhere inside the card focuses the textarea
        if (e.target === e.currentTarget) taRef.current?.focus()
      }}>
        {showSlash && (
          <SlashMenu
            query={text}
            activeIdx={activeIdx}
            onPick={pickSlash}
            onHover={setActiveIdx}
          />
        )}

        <div className="composer-body">
          {/* Pending attachment chips */}
          {pending.length > 0 && (
            <div className="att-row">
              {pending.map((a, i) => (
                <span key={i} className="att-chip">
                  <span className="att-name">{a.filename}</span>
                  {onRemove && (
                    <button
                      type="button"
                      className="att-x"
                      onClick={() => onRemove(i)}
                      aria-label={`Remove ${a.filename}`}
                      title="Remove"
                    >
                      <XIcon />
                    </button>
                  )}
                </span>
              ))}
            </div>
          )}

          <div className="composer-text">
            <textarea
              ref={taRef}
              rows={1}
              value={text}
              disabled={disabled}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKey}
              onPaste={handlePaste}
              placeholder="say something to the agent, or type / for a command…"
            />
          </div>

          <div className="composer-actions">
            <div className="left">
              <div className="plus-wrap" ref={plusWrapRef}>
                <input
                  ref={pdfRef}
                  type="file"
                  accept="application/pdf,.pdf"
                  multiple
                  hidden
                  onChange={handleFilePick}
                />
                <input
                  ref={imgRef}
                  type="file"
                  accept="image/*"
                  multiple
                  hidden
                  onChange={handleFilePick}
                />
                <button
                  type="button"
                  className="iconbtn ghost"
                  onClick={() => setPlusOpen(o => !o)}
                  disabled={disabled}
                  title="Add files"
                  aria-label="Add files"
                  aria-haspopup="menu"
                  aria-expanded={plusOpen}
                >
                  <PlusIcon />
                </button>
                {plusOpen && (
                  <div className="plus-menu" role="menu">
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => { setPlusOpen(false); pdfRef.current?.click() }}
                    >
                      <span className="ic"><PdfIcon /></span>
                      <span>Upload PDF</span>
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => { setPlusOpen(false); imgRef.current?.click() }}
                    >
                      <span className="ic"><ImageIcon /></span>
                      <span>Upload image</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
            <div className="right">
              {disabled && onCancel ? (
                <button
                  type="button"
                  className="iconbtn stop"
                  onClick={onCancel}
                  title="Stop response  Esc"
                  aria-label="Stop response"
                >
                  <StopIcon />
                </button>
              ) : (
                <button
                  type="button"
                  className="iconbtn send"
                  onClick={submit}
                  disabled={!text.trim()}
                  title={`Send  ${IS_MAC ? '⌘' : 'Ctrl'}↵`}
                  aria-label="Send message"
                >
                  <SendIcon />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
