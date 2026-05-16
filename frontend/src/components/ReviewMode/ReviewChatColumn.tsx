// frontend/src/components/ReviewMode/ReviewChatColumn.tsx
//
// Third column in review mode: <PDF | Fields | ReviewChatColumn>. The form
// stays full-height while the chat appears alongside it — the user explicitly
// asked for "talking with the form fully visible", which rules out a bottom
// drawer or vertical split. Horizontal docking only compresses width, never
// height.
//
// Mounts a single <ChatPanel compact />; this is the same chat surface as the
// main shell — Phase B will inject `review_context` into the send envelope.
// Phase A keeps `send` on its existing signature so the chat stays usable as
// soon as this column lands.

import { useEffect, useRef, useState } from 'react'
import { MessageSquare, X } from 'lucide-react'

import ChatPanel from '../Chat/ChatPanel'

export const REV_CHAT_WIDTH_KEY = 'emerge.revChatW'
export const REV_CHAT_DEFAULT_W = 360
export const REV_CHAT_MIN_W = 280
export const REV_CHAT_MAX_W = 560

export function readRevChatWidth(): number {
  try {
    const v = parseFloat(localStorage.getItem(REV_CHAT_WIDTH_KEY) ?? '')
    if (Number.isFinite(v) && v >= REV_CHAT_MIN_W && v <= REV_CHAT_MAX_W) return v
  } catch { /* ignore */ }
  return REV_CHAT_DEFAULT_W
}

export function writeRevChatWidth(px: number): void {
  try { localStorage.setItem(REV_CHAT_WIDTH_KEY, String(px)) } catch { /* ignore */ }
}

interface Props {
  /** Active doc filename — rendered in the header chip. */
  filename: string | null
  /** Currently-selected field path; null when no row is active. */
  activeField: string | null
  /** Value of the currently-active field — read from the entity at
   *  `activeEntityIdx`, supplied by the parent so this column doesn't need to
   *  reach into the schema. */
  activeValue?: unknown
  /** Width of the column in px. The column owns the visual splitter on its
   *  left edge; this is the negotiated number after drag. */
  width: number
  /** Owner persists the width via localStorage. */
  onWidthChange: (px: number) => void
  /** Hide the column (mirrors the "right hidden" toggle in review mode). */
  onClose: () => void
}

export default function ReviewChatColumn({
  filename,
  activeField,
  activeValue,
  width,
  onWidthChange,
  onClose,
}: Props) {
  // The splitter lives on the column's *left* edge (between Fields and Chat).
  // We don't need a ref to the body — the splitter only consumes
  // pointer-move-X relative to the viewport's right edge and feeds the parent
  // width state.
  const [drag, setDrag] = useState(false)
  const startX = useRef(0)
  const startW = useRef(width)

  useEffect(() => {
    if (!drag) return
    function onMove(e: MouseEvent | TouchEvent) {
      const x = 'touches' in e ? e.touches[0].clientX : e.clientX
      const dx = startX.current - x // drag-left → grow
      const next = Math.max(REV_CHAT_MIN_W, Math.min(REV_CHAT_MAX_W, startW.current + dx))
      onWidthChange(next)
      if (e.cancelable) e.preventDefault()
    }
    function onUp() { setDrag(false) }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    window.addEventListener('touchmove', onMove, { passive: false })
    window.addEventListener('touchend', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('touchend', onUp)
    }
  }, [drag, onWidthChange])

  function startDrag(e: React.MouseEvent | React.TouchEvent) {
    startX.current = 'touches' in e ? e.touches[0].clientX : e.clientX
    startW.current = width
    setDrag(true)
    e.preventDefault()
  }

  const displayValue = activeValue == null
    ? ''
    : typeof activeValue === 'object'
      ? JSON.stringify(activeValue)
      : String(activeValue)

  return (
    <>
      <div
        className={'rev-chat-split-v' + (drag ? ' active' : '')}
        onMouseDown={startDrag}
        onTouchStart={startDrag}
        title="Drag to resize"
        role="separator"
        aria-orientation="vertical"
        aria-label="resize chat column"
      />
      <aside className="rev-chat-col" aria-label="review chat">
        <header className="rev-chat-hd">
          <MessageSquare size={13} strokeWidth={1.75} className="rev-chat-hd-icon" />
          {filename ? (
            <span className="rev-chat-hd-chip" title={filename}>
              <span className="fname">{filename}</span>
              {activeField && (
                <>
                  <span className="sep">·</span>
                  <span className="fld">{activeField}</span>
                  {displayValue && (
                    <>
                      <span className="eq">=</span>
                      <span className="val" title={displayValue}>{displayValue}</span>
                    </>
                  )}
                </>
              )}
            </span>
          ) : (
            <span className="rev-chat-hd-chip muted">no doc selected</span>
          )}
          <button
            type="button"
            className="rev-chat-hd-close"
            onClick={onClose}
            aria-label="close chat"
            title="close chat (⌘⇧.)"
          >
            <X size={13} strokeWidth={1.75} />
          </button>
        </header>
        <div className="rev-chat-body">
          <ChatPanel compact />
        </div>
      </aside>
    </>
  )
}
