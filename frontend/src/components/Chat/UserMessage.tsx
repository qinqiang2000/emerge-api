import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Check, Copy, Info, Pencil, RotateCcw } from 'lucide-react'

import { useChat } from '../../stores/chat'
import { useProjects } from '../../stores/projects'

interface Props {
  text: string
  /** 0-indexed ordinal of this user item among all user items in the chat —
   *  passed through to `rewindAndSend` so retry/edit can target this specific
   *  message (not just the latest one). */
  userIndex: number
}

/** User message bubble with claude.ai-style hover actions (retry / edit /
 *  copy). Edit / retry rewinds the chat log at this user message — server
 *  truncates events.jsonl from this user line onward; local state drops the
 *  same range — then re-sends `text`. Available on any user bubble while the
 *  chat is idle. Truncation is destructive (no branching). */
export default function UserMessage({ text, userIndex }: Props) {
  const busy = useChat(s => s.busy)
  const selectedId = useProjects(s => s.selectedId)
  const rewindAndSend = useChat(s => s.rewindAndSend)

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(text)
  const [copied, setCopied] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)

  const showActions = !busy && !editing

  // Auto-grow textarea when entering edit + on input
  useEffect(() => {
    if (!editing) return
    const el = taRef.current
    if (!el) return
    el.focus()
    const len = el.value.length
    el.setSelectionRange(len, len)
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 220) + 'px'
  }, [editing])

  function onDraftChange(v: string) {
    setDraft(v)
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 220) + 'px'
  }

  function cancel() {
    setDraft(text)
    setEditing(false)
  }

  async function save() {
    const trimmed = draft.trim()
    if (!trimmed || trimmed === text.trim()) return
    setEditing(false)
    await rewindAndSend(selectedId ?? 'p_unset', trimmed, userIndex)
  }

  async function retry() {
    await rewindAndSend(selectedId ?? 'p_unset', text, userIndex)
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 800)
    } catch (err) {
      console.warn('copy failed', err)
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      cancel()
      return
    }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void save()
    }
  }

  if (editing) {
    const canSave = draft.trim().length > 0 && draft.trim() !== text.trim()
    return (
      <div className="msg-edit">
        <textarea
          ref={taRef}
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={onKey}
          rows={1}
        />
        <div className="row">
          <span className="hint">
            <Info size={14} aria-hidden />
            <span>编辑会丢弃下方的 agent 回复。</span>
          </span>
          <div className="btns">
            <button type="button" className="cancel" onClick={cancel}>Cancel</button>
            <button type="button" className="save" onClick={() => void save()} disabled={!canSave}>
              Save
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="umsg flex flex-col items-end w-full">
      <div className="msg user">{text}</div>
      {showActions && (
        <div className="msg-actions" role="group" aria-label="Message actions">
          <button type="button" onClick={() => void retry()} title="Retry" aria-label="Retry">
            <RotateCcw size={16} aria-hidden />
          </button>
          <button type="button" onClick={() => setEditing(true)} title="Edit" aria-label="Edit">
            <Pencil size={16} aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => void copy()}
            title={copied ? 'Copied' : 'Copy'}
            aria-label="Copy"
            className={copied ? 'copied' : undefined}
          >
            {copied ? <Check size={16} aria-hidden /> : <Copy size={16} aria-hidden />}
          </button>
        </div>
      )}
    </div>
  )
}
