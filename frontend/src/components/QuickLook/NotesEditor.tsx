import { useEffect, useRef, useState } from 'react'
import { useSchema, type SchemaField, type SaveError } from '../../stores/schema'
import { usePrompts } from '../../stores/prompts'

interface Props {
  slug: string
  value: string
  schema: SchemaField[]
  readOnly?: boolean
}

const PLACEHOLDER = '给模型的整体说明 — 角色、输入约束、任务描述、注意事项…'

export default function NotesEditor({ slug, value, schema, readOnly }: Props) {
  const [local, setLocal] = useState(value)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<SaveError | null>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  // Sync from prop when the store-side value changes externally (e.g.
  // a write_prompt tool result reloaded usePrompts). Skip while the
  // textarea has focus so we don't clobber the user's mid-edit value.
  useEffect(() => {
    if (taRef.current && document.activeElement === taRef.current) return
    setLocal(value)
  }, [value])

  if (readOnly) {
    return (
      <div className="ql-notes">
        <div className="ql-notes-lab">notes</div>
        {local.length > 0
          ? <pre className="ql-notes-ro">{local}</pre>
          : <div className="ql-notes-ro ql-notes-ro--empty">{'(no notes)'}</div>}
      </div>
    )
  }

  const commit = async () => {
    if (local === value) return
    setPending(true)
    setError(null)
    const err = await useSchema.getState().saveActive(slug, schema, local)
    setPending(false)
    if (err) {
      setError(err)
      setLocal(value)
      console.error('NotesEditor save failed', err)
    } else {
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
    }
  }

  return (
    <div className="ql-notes">
      <div className="ql-notes-lab">
        notes
        {pending && <span className="ql-notes-pending">saving…</span>}
      </div>
      <textarea
        ref={taRef}
        className="ql-notes-ta"
        value={local}
        placeholder={PLACEHOLDER}
        spellCheck={false}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={() => { void commit() }}
      />
      {error && (
        <div className="ql-edit-err" role="alert">
          <span className="ql-edit-err-code">{error.error_code}</span>
          {error.error_message_en && <span className="ql-edit-err-msg">{error.error_message_en}</span>}
        </div>
      )}
    </div>
  )
}
