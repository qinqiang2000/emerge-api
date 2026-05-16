import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuickLook } from '../../stores/quicklook'
import { useProjects } from '../../stores/projects'
import { usePrompts } from '../../stores/prompts'
import QuickLookHeader from './QuickLookHeader'
import PromptTab from './PromptTab'
import RawJsonTab from './RawJsonTab'
import './styles.css'

type Tab = 'prompt' | 'raw'

export default function PromptQuickLook() {
  const target = useQuickLook(s => s.target)
  const close = useQuickLook(s => s.close)
  const projects = useProjects(s => s.projects)
  const [tab, setTab] = useState<Tab>('prompt')

  // Reset tab when a new target opens.
  useEffect(() => { setTab('prompt') }, [target])

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
      if (t && t.pid !== s.selectedSlug) {
        useQuickLook.getState().close()
      }
    })
    return unsub
  }, [])

  const activePrompt = usePrompts(s => target ? s.activeByProject[target.pid] : undefined)
  const promptList = usePrompts(s => target ? s.list[target.pid] : undefined)
  const loadPrompts = usePrompts(s => s.load)
  useEffect(() => {
    if (target && target.kind === 'prompt') void loadPrompts(target.pid)
  }, [target, loadPrompts])

  if (!target) return null

  // QuickLook `target.pid` holds a slug (post-transparency rename). Match by slug.
  const activeVersionId = projects.find(p => p.slug === target.pid)?.active_version_id ?? null
  let derivedFrom: string | null = null
  if (target.kind === 'prompt') {
    if (target.promptId) {
      derivedFrom = promptList?.find(p => p.prompt_id === target.promptId)?.derived_from ?? null
    } else {
      derivedFrom = activePrompt?.derived_from ?? null
    }
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
            className={`ql-tab${tab === 'prompt' ? ' ql-tab--active' : ''}`}
            onClick={() => setTab('prompt')}
          >
            prompt
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
          {tab === 'prompt' ? <PromptTab target={target} /> : <RawJsonTab />}
        </div>

        <div className="ql-footer">
          notes + field descriptions go into the prompt at publish time. review notes (per-doc)
          feed AutoResearch only — they propose tweaks but never become prompt.
        </div>
      </div>
    </div>,
    document.body,
  )
}
