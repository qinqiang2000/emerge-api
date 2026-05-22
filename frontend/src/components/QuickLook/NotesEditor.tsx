import { useEffect, useRef, useState } from 'react'
import { useSchema, type SchemaField, type SaveError } from '../../stores/schema'
import { usePrompts } from '../../stores/prompts'
import { Reminder } from '../Reminder'
import { useT } from '../../i18n'

interface Props {
  slug: string
  value: string
  schema: SchemaField[]
  readOnly?: boolean
}

// Long enough that the human eye can register the confirmation, short enough
// that it doesn't linger past the next interaction. Matches PublishStage's
// copy-confirm cadence.
const SAVED_HOLD_MS = 1500

type Status = 'idle' | 'saving' | 'saved' | 'error'

export default function NotesEditor({ slug, value, schema, readOnly }: Props) {
  const t = useT()
  const [local, setLocal] = useState(value)
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<SaveError | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const savedTimerRef = useRef<number | null>(null)

  // Sync from prop when the store-side value changes externally (e.g.
  // a write_prompt tool result reloaded usePrompts). Skip while the
  // textarea has focus so we don't clobber the user's mid-edit value.
  useEffect(() => {
    if (taRef.current && document.activeElement === taRef.current) return
    setLocal(value)
  }, [value])

  // Clean up the hold-timer on unmount; otherwise a quick close-then-reopen
  // could fire setStatus into an unmounted tree.
  useEffect(() => () => {
    if (savedTimerRef.current !== null) window.clearTimeout(savedTimerRef.current)
  }, [])

  // Auto-grow to fit content up to ~35vh, then scroll internally. The cap is
  // intentionally lower than the textarea could fill — the fields list lives
  // directly below, and we want at least half the panel reserved for it so
  // long notes never push the fields entirely below the fold.
  useEffect(() => {
    const el = taRef.current
    if (!el || readOnly || collapsed) return
    const recalc = () => {
      el.style.height = 'auto'
      const max = Math.floor(window.innerHeight * 0.35)
      el.style.height = Math.min(el.scrollHeight, max) + 'px'
      el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
    }
    recalc()
    const ro = new ResizeObserver(recalc)
    if (el.parentElement) ro.observe(el.parentElement)
    return () => ro.disconnect()
  }, [local, collapsed, readOnly])

  const lineCount = local.length === 0 ? 0 : local.split('\n').length
  const summary = local.length === 0
    ? t('ql.notes.empty')
    : (lineCount === 1 ? t('ql.notes.line.one') : t('ql.notes.line.many', { n: lineCount }))

  if (readOnly) {
    return (
      <div className="ql-notes">
        <div className="ql-notes-lab">
          <button
            type="button"
            className="ql-notes-toggle"
            onClick={() => setCollapsed(v => !v)}
            aria-expanded={!collapsed}
            title={collapsed ? t('ql.notes.expand') : t('ql.notes.collapse')}
          >
            {collapsed ? '▸' : '▾'} notes
          </button>
          {collapsed && <span className="ql-notes-count">· {summary}</span>}
        </div>
        {!collapsed && (
          local.length > 0
            ? <pre className="ql-notes-ro">{local}</pre>
            : <div className="ql-notes-ro ql-notes-ro--empty">{t('ql.notes.none')}</div>
        )}
      </div>
    )
  }

  const commit = async () => {
    if (local === value) return
    if (savedTimerRef.current !== null) {
      window.clearTimeout(savedTimerRef.current)
      savedTimerRef.current = null
    }
    setStatus('saving')
    setError(null)
    const err = await useSchema.getState().saveActive(slug, schema, local)
    if (err) {
      setError(err)
      setStatus('error')
      setLocal(value)
      console.error('NotesEditor save failed', err)
      return
    }
    // Patch the cached active prompt in place. invalidate() would also work
    // but it nukes list[slug] (→ spine flashes "(none yet)") and
    // activeByProject[slug] (→ this textarea momentarily reads undefined and
    // resets to '') with nothing scheduled to refill them until the next
    // page mount.
    usePrompts.setState((s) => {
      const cur = s.activeByProject[slug]
      if (!cur) return s
      return {
        activeByProject: { ...s.activeByProject, [slug]: { ...cur, global_notes: local } },
      }
    })
    setStatus('saved')
    savedTimerRef.current = window.setTimeout(() => {
      savedTimerRef.current = null
      setStatus('idle')
    }, SAVED_HOLD_MS)
  }

  return (
    <div className="ql-notes">
      <div className="ql-notes-lab">
        <button
          type="button"
          className="ql-notes-toggle"
          onClick={() => setCollapsed(v => !v)}
          aria-expanded={!collapsed}
          title={collapsed ? 'expand' : 'collapse'}
        >
          {collapsed ? '▸' : '▾'} notes
        </button>
        {collapsed && <span className="ql-notes-count">· {summary}</span>}
        {status === 'saving' && (
          <Reminder form="inline" intent="note">{t('ql.notes.saving')}</Reminder>
        )}
        {status === 'saved' && (
          <Reminder form="inline" intent="tip">{t('ql.notes.saved')}</Reminder>
        )}
      </div>
      {!collapsed && (
        <textarea
          ref={taRef}
          className="ql-notes-ta"
          value={local}
          placeholder={t('ql.notes.placeholder')}
          spellCheck={false}
          onChange={(e) => setLocal(e.target.value)}
          onBlur={() => { void commit() }}
        />
      )}
      {status === 'error' && error && (
        <div className="ql-edit-err" role="alert">
          <span className="ql-edit-err-code">{error.error_code}</span>
          {error.error_message_en && <span className="ql-edit-err-msg">{error.error_message_en}</span>}
        </div>
      )}
    </div>
  )
}
