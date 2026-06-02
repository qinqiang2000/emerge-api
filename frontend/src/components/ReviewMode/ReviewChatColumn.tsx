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
import ChatHistoryActions from '../Chat/ChatHistoryActions'
import JobProgressCard from '../Chat/JobProgressCard'
import { useChat } from '../../stores/chat'
import { useProjects } from '../../stores/projects'
import { useReviewTune } from '../../stores/reviewTune'
import { useT } from '../../i18n'

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

  // Mount the chat-history + new-chat affordance inside `rev-chat-hd` so a
  // session in review mode can start a fresh thread without leaving the
  // overlay. Persistence is handled by `useChat` (per-project chat id keyed
  // off slug); a fresh chat doesn't lose memory because the agent's extractor
  // skill auto-routes corrections into durable artifacts (per-doc _notes,
  // global_notes, schema descriptions) — see plan
  // image-1-chat-velvety-duckling.md.
  const t = useT()
  const { selectedSlug, projects } = useProjects()
  const chatId = useChat(s => s.chatId)
  const chatsByProject = useChat(s => s.chatsByProject)
  const showHistoryActions = Boolean(selectedSlug) && selectedSlug !== 'p_unset'
  const projectName = projects.find(p => p.slug === selectedSlug)?.name ?? selectedSlug ?? ''
  const chatsForProject = selectedSlug ? (chatsByProject[selectedSlug] ?? []) : []
  const tuneJobIds = useReviewTune((s) => s.jobIds)

  return (
    <>
      <div
        className={'rev-chat-split-v' + (drag ? ' active' : '')}
        onMouseDown={startDrag}
        onTouchStart={startDrag}
        title={t('reviewchat.resize.title')}
        role="separator"
        aria-orientation="vertical"
        aria-label={t('reviewchat.resize.aria')}
      />
      <aside className="rev-chat-col" aria-label={t('reviewchat.aria')}>
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
            <span className="rev-chat-hd-chip muted">{t('reviewchat.noDoc')}</span>
          )}
          {showHistoryActions && selectedSlug && (
            <ChatHistoryActions
              variant="compact"
              activeProject={projectName}
              currentChatId={chatId}
              chats={chatsForProject}
              onNew={() => useChat.getState().newChat(selectedSlug)}
              onSwitch={(cid) => useChat.getState().switchChat(selectedSlug, cid)}
              onOpen={() => { void useChat.getState().listChats(selectedSlug) }}
            />
          )}
          <button
            type="button"
            className="rev-chat-hd-close"
            onClick={onClose}
            aria-label={t('reviewchat.close.aria')}
            title={t('reviewchat.close.title')}
          >
            <X size={13} strokeWidth={1.75} />
          </button>
        </header>
        <div className="rev-chat-body">
          {/* Focused-tune jobs launched from the review bar surface their
              progress here (reusing the chat's JobProgressCard) so the
              non-chat entry point still resolves through the right-hand
              conversation. */}
          {tuneJobIds.length > 0 && (
            <div className="rev-chat-jobs">
              {tuneJobIds.map((id) => (
                <JobProgressCard key={id} jobId={id} />
              ))}
            </div>
          )}
          <ChatPanel compact />
        </div>
      </aside>
    </>
  )
}
