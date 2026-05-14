import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useSchema } from '../../stores/schema'
import FieldCard from './FieldCard'
import type { QuickLookTarget } from '../../stores/quicklook'
import type { SchemaField } from '../../stores/schema'

interface Props {
  target: QuickLookTarget
}

export default function FieldsTab({ target }: Props) {
  if (target.kind === 'schema') return <SchemaFields pid={target.pid} />
  if (target.kind === 'prompt') return <PromptFields pid={target.pid} promptId={target.promptId} />
  return <VersionFields pid={target.pid} versionId={target.versionId} />
}

function PromptFields({ pid, promptId }: { pid: string; promptId: string }) {
  const [state, setState] = useState<{ fields: SchemaField[] | null; error: string | null }>({
    fields: null,
    error: null,
  })

  useEffect(() => {
    let cancelled = false
    // `pid` carries the project slug post-transparency rename.
    fetch(`/lab/projects/${encodeURIComponent(pid)}/prompts/${promptId}`)
      .then(async resp => {
        if (!resp.ok) {
          let code = `http_${resp.status}`
          try {
            const j = await resp.json()
            code = j?.detail?.error_code ?? code
          } catch { /* not json */ }
          if (!cancelled) setState({ fields: null, error: code })
          return
        }
        const blob = await resp.json()
        if (!cancelled) setState({ fields: blob.schema ?? [], error: null })
      })
      .catch(e => { if (!cancelled) setState({ fields: null, error: (e as Error).message }) })
    return () => { cancelled = true }
  }, [pid, promptId])

  if (state.error) return <div className="ql-raw-error">{state.error}</div>
  if (state.fields === null) return <div className="ql-field-desc ql-field-desc--empty">loading…</div>
  if (state.fields.length === 0) {
    return <div className="ql-field ql-field-desc ql-field-desc--empty">empty prompt</div>
  }
  return <FieldList fields={state.fields} />
}

function SchemaFields({ pid }: { pid: string }) {
  const fields = useSchema(useShallow(s => s.byProject[pid]))
  // Cache-first load: safety net for future deep-link / slash-command surfaces
  // that open Quick-look without going through the project-selection effect
  // that pre-warms useSchema.
  useEffect(() => { void useSchema.getState().load(pid) }, [pid])
  if (fields === undefined) {
    return <div className="ql-field-desc ql-field-desc--empty">loading…</div>
  }
  if (fields.length === 0) {
    return (
      <div className="ql-field ql-field-desc ql-field-desc--empty">
        no schema yet — type /init in the chat
      </div>
    )
  }
  return <FieldList fields={fields} />
}

function VersionFields({ pid, versionId }: { pid: string; versionId: string }) {
  const [state, setState] = useState<{ fields: SchemaField[] | null; error: string | null }>({
    fields: null,
    error: null,
  })

  useEffect(() => {
    let cancelled = false
    fetch(`/lab/projects/${encodeURIComponent(pid)}/versions/${versionId}/raw?shape=fields`)
      .then(async resp => {
        if (!resp.ok) {
          let code = `http_${resp.status}`
          try {
            const j = await resp.json()
            code = j?.detail?.error_code ?? code
          } catch { /* not json */ }
          if (!cancelled) setState({ fields: null, error: code })
          return
        }
        const blob = await resp.json()
        if (!cancelled) setState({ fields: blob.fields ?? [], error: null })
      })
      .catch(e => { if (!cancelled) setState({ fields: null, error: (e as Error).message }) })
    return () => { cancelled = true }
  }, [pid, versionId])

  if (state.error) return <div className="ql-raw-error">{state.error}</div>
  if (state.fields === null) return <div className="ql-field-desc ql-field-desc--empty">loading…</div>
  if (state.fields.length === 0) {
    return <div className="ql-field ql-field-desc ql-field-desc--empty">empty version</div>
  }
  return <FieldList fields={state.fields} />
}

function FieldList({ fields }: { fields: SchemaField[] }) {
  return (
    <>
      {fields.map(f => <FieldCard key={f.name} field={f} />)}
    </>
  )
}
