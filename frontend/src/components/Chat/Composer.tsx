import { useState, useRef, useEffect, useMemo, type ClipboardEvent, type DragEvent, type KeyboardEvent } from 'react'

import { listProjectTree, type TreeEntry } from '../../lib/api'
import MentionMenu from './MentionMenu'
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
// Paperclip glyph lifted from claude.ai's "Add files or photos" menu — one
// option for both PDFs and images because users can rarely tell which a given
// scan/screenshot is. Backend (`/lab/projects/{pid}/upload`) accepts both.
const PaperclipIcon = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden>
    <path d="M6.068 2.161a2.72 2.72 0 0 1 3.524 1.533l3.206 8.14a1.61 1.61 0 0 1-.907 2.087l-.076.03a1.61 1.61 0 0 1-2.087-.908L8.027 8.726a.5.5 0 0 1 .93-.367l1.702 4.318a.61.61 0 0 0 .79.343l.076-.03a.61.61 0 0 0 .343-.79L8.662 4.06a1.72 1.72 0 0 0-2.227-.968l-.154.06a1.72 1.72 0 0 0-.97 2.228l3.87 9.821a2.826 2.826 0 0 0 3.665 1.594l.23-.09a2.83 2.83 0 0 0 1.595-3.666l-2.363-6a.5.5 0 1 1 .93-.366l2.363 6a3.826 3.826 0 0 1-2.158 4.962l-.23.09a3.827 3.827 0 0 1-4.963-2.157L4.382 5.747a2.72 2.72 0 0 1 1.532-3.525z" />
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
const UPLOAD_SHORTCUT_LABEL = IS_MAC ? '⌘U' : 'Ctrl+U'

interface PendingChip {
  filename: string
  /** 'uploading' / 'staging' = still in flight; 'uploaded' / 'staged' = ready;
   *  'failed' = error, retryable. Missing = treat as ready (legacy callers /
   *  tests that pass plain filenames). */
  status?: 'staging' | 'staged' | 'uploading' | 'uploaded' | 'failed'
  error?: string
}

interface Props {
  disabled: boolean
  pending: PendingChip[]
  onAttach: (files: File[]) => void
  onSubmit: (text: string) => void
  /** Remove the i-th pending attachment. Optional so legacy callers compile. */
  onRemove?: (index: number) => void
  /** Re-run the upload for a failed pending entry. Optional. */
  onRetry?: (index: number) => void
  /** When provided + `disabled` is true, renders a Stop pill + binds Esc at
   *  window level to cancel the in-flight turn. Optional so existing call
   *  sites (and tests) without cancel support still compile. */
  onCancel?: () => void
  /** Current project id — needed for `@` mention's tree fetch. When absent
   *  or `p_unset`, the mention menu does not open (typing `@` is plain text). */
  projectId?: string
}

// Per-chip status indicator. Lives next to the filename so the row reads
// left-to-right as "this file → its state".
const SpinnerIcon = () => (
  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden>
    <circle cx="8" cy="8" r="6" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
    <path d="M14 8a6 6 0 0 0-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <animateTransform attributeName="transform" type="rotate" from="0 8 8" to="360 8 8" dur="0.8s" repeatCount="indefinite" />
    </path>
  </svg>
)
const CheckIcon = () => (
  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden>
    <path d="M3 8.5L6.5 12L13 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const RetryIcon = () => (
  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden>
    <path d="M3 8a5 5 0 1 0 1.5-3.5M3 3v3h3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

/** Parse the textarea around `caret` and return the current mention context
 *  (dir + query) if the active token starts with `@`. The active token is the
 *  run of non-whitespace chars left of the caret. Returns null if the caret is
 *  not on a mention token. */
function parseMentionToken(text: string, caret: number): { token: string; tokenStart: number; dir: string; query: string } | null {
  let start = caret
  while (start > 0 && !/\s/.test(text[start - 1])) start -= 1
  const token = text.slice(start, caret)
  if (!token.startsWith('@')) return null
  const body = token.slice(1)
  const slash = body.lastIndexOf('/')
  const dir = slash >= 0 ? body.slice(0, slash) : ''
  const query = slash >= 0 ? body.slice(slash + 1) : body
  return { token, tokenStart: start, dir, query }
}

export default function Composer({ disabled, pending, onAttach, onSubmit, onRemove, onRetry, onCancel, projectId }: Props) {
  const [text, setText] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const [plusOpen, setPlusOpen] = useState(false)
  // `caret` mirrors the textarea's selectionStart so the mention token can be
  // recomputed on every keystroke / click. Updated from onChange / onKeyUp /
  // onClick / onSelect.
  const [caret, setCaret] = useState(0)
  const [mentionEntries, setMentionEntries] = useState<TreeEntry[]>([])
  const [mentionLoading, setMentionLoading] = useState(false)
  const [mentionMissing, setMentionMissing] = useState(false)
  // Position of an `@` the user explicitly dismissed with Esc. The menu stays
  // closed for that token until the user types a fresh `@` elsewhere (which
  // produces a different `tokenStart`) or the token disappears entirely.
  const [dismissedAt, setDismissedAt] = useState<number | null>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const plusWrapRef = useRef<HTMLDivElement>(null)
  // Per-(pid+dir) cache so re-opening the menu in the same dir is instant.
  const treeCacheRef = useRef<Map<string, TreeEntry[]>>(new Map())

  // The autocomplete menu is open only while the user is still typing a command
  // name. Once a full command prefixes the text (`/eval` or `/eval …`), the
  // menu closes and plain Enter inserts a newline like a normal textarea —
  // only ⌘/Ctrl+Enter submits, matching the footer hint.
  const completedCommand = COMMANDS.some(c => text === c.cmd || text.startsWith(c.cmd + ' '))
  const showSlash = text.startsWith('/') && !completedCommand

  // `@` mention state is derived from the textarea content + caret position.
  // The mention menu opens only when a project is selected and the slash menu
  // is closed (the two are mutually exclusive).
  const hasProject = !!projectId && projectId !== 'p_unset'
  const mentionToken = useMemo(() => {
    if (!hasProject || showSlash) return null
    return parseMentionToken(text, caret)
  }, [hasProject, showSlash, text, caret])
  // Clear an Esc-dismissal once the user removes the `@` token or starts a new
  // one at a different position — those are signals that the previous dismissal
  // no longer applies.
  useEffect(() => {
    if (dismissedAt === null) return
    if (!mentionToken || mentionToken.tokenStart !== dismissedAt) setDismissedAt(null)
  }, [mentionToken, dismissedAt])
  const showMention =
    mentionToken !== null && mentionToken.tokenStart !== dismissedAt

  // Filter the fetched dir entries by the trailing query segment, case-insensitive.
  const mentionMatches = useMemo<TreeEntry[]>(() => {
    if (!mentionToken) return []
    const q = mentionToken.query.toLowerCase()
    if (!q) return mentionEntries
    return mentionEntries.filter(e => e.name.toLowerCase().startsWith(q))
  }, [mentionToken, mentionEntries])

  // Lazy fetch: when the active dir changes (or projectId changes), pull entries
  // from cache or hit `/lab/projects/{pid}/tree?dir=…`. 404 → "no such directory".
  useEffect(() => {
    if (!showMention || !mentionToken || !projectId) {
      setMentionEntries([])
      setMentionLoading(false)
      setMentionMissing(false)
      return
    }
    const dir = mentionToken.dir
    const key = projectId + '|' + dir
    const cached = treeCacheRef.current.get(key)
    if (cached) {
      setMentionEntries(cached)
      setMentionLoading(false)
      setMentionMissing(false)
      return
    }
    let alive = true
    setMentionLoading(true)
    setMentionMissing(false)
    listProjectTree(projectId, dir)
      .then(entries => {
        if (!alive) return
        treeCacheRef.current.set(key, entries)
        setMentionEntries(entries)
        setMentionMissing(false)
        setMentionLoading(false)
      })
      .catch(err => {
        if (!alive) return
        // 404 → dir doesn't exist; show an empty list with a hint. Other errors:
        // fall back to empty list silently (network blips shouldn't crash the UI).
        const msg = err instanceof Error ? err.message : String(err)
        setMentionEntries([])
        setMentionMissing(/404/.test(msg))
        setMentionLoading(false)
      })
    return () => {
      alive = false
    }
  }, [showMention, projectId, mentionToken?.dir])

  // Auto-grow textarea up to 384px (claude.ai max-h-96). Recalc on text
  // change AND on container resize — without the resize hook the textarea
  // sticks at whatever height was set when it was last narrower (e.g.,
  // during responsive media-query transitions), making the composer balloon.
  useEffect(() => {
    const el = taRef.current
    if (!el) return
    const recalc = () => {
      el.style.height = 'auto'
      const max = 384
      el.style.height = Math.min(el.scrollHeight, max) + 'px'
      el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
    }
    recalc()
    const ro = new ResizeObserver(recalc)
    if (el.parentElement) ro.observe(el.parentElement)
    return () => ro.disconnect()
  }, [text])

  // Reset active index when slash menu opens/closes
  useEffect(() => { setActiveIdx(0) }, [showSlash])

  // Reset the mention activeIdx on dir / query change so the highlight always
  // tracks the first match — same UX as CC.
  useEffect(() => {
    if (showMention) setActiveIdx(0)
  }, [showMention, mentionToken?.dir, mentionToken?.query])

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

  // Global ⌘U / Ctrl+U opens the file picker, matching claude.ai. We hijack
  // the browser's default (View Source) intentionally — same trade-off claude
  // makes, since the composer is the primary action on the page.
  useEffect(() => {
    if (disabled) return
    const handler = (e: globalThis.KeyboardEvent) => {
      if ((e.key === 'u' || e.key === 'U') && (e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey) {
        e.preventDefault()
        fileRef.current?.click()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [disabled])

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

  /** Replace the current `@…` token with `@<entry.path>` + suffix and move
   *  the caret to just after the suffix. For dirs we keep the menu open by
   *  appending `/`; for files we close it by appending a space. */
  function pickMention(entry: TreeEntry) {
    if (!mentionToken) return
    const suffix = entry.kind === 'dir' ? '/' : ' '
    const insert = '@' + entry.path + suffix
    const before = text.slice(0, mentionToken.tokenStart)
    const after = text.slice(caret)
    const next = before + insert + after
    const nextCaret = before.length + insert.length
    setText(next)
    // Defer caret restore until after React commits the new value so the
    // textarea's DOM selectionStart matches the state we just set.
    queueMicrotask(() => {
      const ta = taRef.current
      if (!ta) return
      ta.focus()
      ta.setSelectionRange(nextCaret, nextCaret)
      setCaret(nextCaret)
    })
  }

  function submit() {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSubmit(trimmed)
    setText('')
  }

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Cmd/Ctrl+Enter always submits. If a mention menu is open we close it
    // first so the textarea state is clean for the next turn.
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
      return
    }

    if (showMention && mentionToken) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        const n = mentionMatches.length
        if (n > 0) setActiveIdx(i => (i + 1) % n)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        const n = mentionMatches.length
        if (n > 0) setActiveIdx(i => (i - 1 + n) % n)
        return
      }
      if ((e.key === 'Enter' || e.key === 'Tab') && !e.shiftKey) {
        // Only pick if we have a match; otherwise fall through so Tab/Enter
        // behave like the textarea's default (Enter inserts newline, Tab moves focus).
        if (mentionMatches.length > 0) {
          e.preventDefault()
          const pick = mentionMatches[Math.min(activeIdx, mentionMatches.length - 1)]
          if (pick) pickMention(pick)
          return
        }
      }
      if (e.key === 'Escape') {
        // Close the menu, text untouched. The dismissal is keyed to the `@`'s
        // position so the menu stays closed for this token but reopens if the
        // user starts a new one elsewhere.
        e.preventDefault()
        if (mentionToken) setDismissedAt(mentionToken.tokenStart)
        return
      }
      // All other keys fall through — typing continues to mutate the text
      // and the derived token / query stay in sync via onChange.
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
        {showMention && mentionToken && (
          <MentionMenu
            entries={mentionMatches}
            activeIdx={activeIdx}
            dir={mentionToken.dir}
            loading={mentionLoading}
            emptyHint={mentionMissing ? 'no such directory' : (mentionToken.query ? 'no match' : 'empty')}
            onPick={pickMention}
            onHover={setActiveIdx}
          />
        )}

        <div className="composer-body">
          {/* Pending attachment chips. Status mapping:
               - staging / uploading → spinner, chip not interactive (in flight)
               - staged / uploaded   → check, chip can be removed
               - failed              → retry button (re-runs the upload) + remove
               Legacy callers (tests, older code paths) pass plain { filename }
               and we treat that as "ready". */}
          {pending.length > 0 && (
            <div className="att-row">
              {pending.map((a, i) => {
                const status = a.status ?? 'uploaded'
                const inFlight = status === 'staging' || status === 'uploading'
                const failed = status === 'failed'
                return (
                  <span
                    key={i}
                    className={'att-chip' + (failed ? ' att-chip-failed' : '')}
                    title={failed ? (a.error || 'upload failed') : a.filename}
                  >
                    <span className="att-status" aria-hidden>
                      {inFlight ? <SpinnerIcon /> : failed ? null : <CheckIcon />}
                    </span>
                    <span className="att-name">{a.filename}</span>
                    {failed && onRetry && (
                      <button
                        type="button"
                        className="att-retry"
                        onClick={() => onRetry(i)}
                        aria-label={`Retry ${a.filename}`}
                        title={a.error ? `Retry — ${a.error}` : 'Retry'}
                      >
                        <RetryIcon />
                      </button>
                    )}
                    {onRemove && !inFlight && (
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
                )
              })}
            </div>
          )}

          <div className="composer-text">
            <textarea
              ref={taRef}
              rows={1}
              value={text}
              disabled={disabled}
              onChange={(e) => {
                setText(e.target.value)
                setCaret(e.target.selectionStart ?? e.target.value.length)
              }}
              onKeyUp={(e) => setCaret(e.currentTarget.selectionStart ?? caret)}
              onClick={(e) => setCaret(e.currentTarget.selectionStart ?? caret)}
              onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? caret)}
              onKeyDown={handleKey}
              onPaste={handlePaste}
              placeholder="say something to the agent, or type / for a command…"
            />
          </div>

          <div className="composer-actions">
            <div className="left">
              <div className="plus-wrap" ref={plusWrapRef}>
                <input
                  ref={fileRef}
                  type="file"
                  accept="application/pdf,.pdf,image/*"
                  multiple
                  hidden
                  onChange={handleFilePick}
                />
                <button
                  type="button"
                  className="iconbtn ghost"
                  onClick={() => setPlusOpen(o => !o)}
                  disabled={disabled}
                  title={`Add files (${UPLOAD_SHORTCUT_LABEL})`}
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
                      onClick={() => { setPlusOpen(false); fileRef.current?.click() }}
                    >
                      <span className="mi-left">
                        <span className="ic"><PaperclipIcon /></span>
                        <span className="label">Add files or photos</span>
                      </span>
                      <span className="shortcut">{UPLOAD_SHORTCUT_LABEL}</span>
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
              ) : (() => {
                const hasInFlight = pending.some(p => p.status === 'staging' || p.status === 'uploading')
                return (
                  <button
                    type="button"
                    className="iconbtn send"
                    onClick={submit}
                    disabled={!text.trim() || hasInFlight}
                    title={hasInFlight
                      ? 'Waiting for uploads to finish…'
                      : `Send  ${IS_MAC ? '⌘' : 'Ctrl'}↵`}
                    aria-label="Send message"
                  >
                    <SendIcon />
                  </button>
                )
              })()}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
