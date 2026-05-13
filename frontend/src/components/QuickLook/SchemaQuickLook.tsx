import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuickLook } from '../../stores/quicklook'
import { useProjects } from '../../stores/projects'
import { usePrompts } from '../../stores/prompts'
import QuickLookHeader from './QuickLookHeader'
import FieldsTab from './FieldsTab'
import RawJsonTab from './RawJsonTab'
import './styles.css'

type Tab = 'fields' | 'raw'

export default function SchemaQuickLook() {
  const target = useQuickLook(s => s.target)
  const close = useQuickLook(s => s.close)
  const projects = useProjects(s => s.projects)
  const [tab, setTab] = useState<Tab>('fields')

  // Reset tab when a new target opens.
  useEffect(() => { setTab('fields') }, [target])

  // Esc to close.
  useEffect(() => {
    if (!target) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [target, close])

  // Auto-close on project switch via Zustand subscription (fires synchronously on setState).
  // useEffect would be async, but subscribers run synchronously — needed for both test fidelity
  // and correct UX (the sheet must close the instant the project changes, not one render later).
  useEffect(() => {
    const unsub = useProjects.subscribe(s => {
      const t = useQuickLook.getState().target
      if (t && t.pid !== s.selectedId) {
        useQuickLook.getState().close()
      }
    })
    return unsub
  }, [])

  const activePrompt = usePrompts(s => target ? s.activeByProject[target.pid] : undefined)
  const promptList = usePrompts(s => target ? s.list[target.pid] : undefined)
  const loadPrompts = usePrompts(s => s.load)
  useEffect(() => {
    if (target && (target.kind === 'schema' || target.kind === 'prompt')) void loadPrompts(target.pid)
  }, [target, loadPrompts])

  if (!target) return null

  const activeVersionId = projects.find(p => p.project_id === target.pid)?.active_version_id ?? null
  let derivedFrom: string | null = null
  if (target.kind === 'schema') {
    derivedFrom = activePrompt?.derived_from ?? null
  } else if (target.kind === 'prompt') {
    derivedFrom = promptList?.find(p => p.prompt_id === target.promptId)?.derived_from ?? null
  }

  return createPortal(
    <div
      className="ql-scrim"
      data-testid="ql-scrim"
      onClick={e => { if (e.target === e.currentTarget) close() }}
    >
      <div className="ql-sheet" role="dialog" aria-modal="true">
        <QuickLookHeader target={target} activeVersionId={activeVersionId} derivedFrom={derivedFrom} onClose={close} />

        <div className="ql-tabs">
          <button
            type="button"
            className={`ql-tab${tab === 'fields' ? ' ql-tab--active' : ''}`}
            onClick={() => setTab('fields')}
          >
            fields
          </button>
          <button
            type="button"
            className={`ql-tab${tab === 'raw' ? ' ql-tab--active' : ''}`}
            onClick={() => setTab('raw')}
          >
            raw json
          </button>
        </div>

        <div className="ql-body">
          {tab === 'fields' ? <FieldsTab target={target} /> : <RawJsonTab />}
        </div>

        <div className="ql-footer">
          description goes into the prompt at publish time. review notes (per-doc) feed
          AutoResearch only — they propose description tweaks but never become prompt.
        </div>
      </div>
    </div>,
    document.body,
  )
}
