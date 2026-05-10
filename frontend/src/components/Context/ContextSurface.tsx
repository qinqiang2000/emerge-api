// frontend/src/components/Context/ContextSurface.tsx
import { useEffect } from 'react'
import { X } from 'lucide-react'

import { useProjects } from '../../stores/projects'
import { useSchema } from '../../stores/schema'
import { useDocs } from '../../stores/docs'
import { useReview } from '../../stores/review'
import { docStatus } from '../../types/review'
import type { DocSummary } from '../../types/review'

// Map legacy docStatus values → pill class suffixes
function toPillClass(doc: DocSummary): string {
  const s = docStatus(doc)
  if (s === 'reviewed') return 'rev'
  if (s === 'draft') return 'pen'   // has prediction, not yet reviewed
  return 'new'                       // no prediction yet
}

// Pill label shown to user
function toPillLabel(doc: DocSummary): string {
  const s = docStatus(doc)
  if (s === 'reviewed') return 'reviewed'
  if (s === 'draft') return 'pending'
  return 'new'
}

// Placeholder metrics — real wiring deferred until useEval + /lab/projects/:id/evals land
const PLACEHOLDER_METRICS = [
  { k: 'precision', v: '0.94', tone: 'ok' },
  { k: 'recall',    v: '0.91', tone: 'ok' },
  { k: 'f1',        v: '0.92', tone: 'ok' },
  { k: 'coverage',  v: '100%', tone: 'ok' },
] as const

const MAX_VISIBLE_DOCS = 9
const MAX_VISIBLE_FIELDS = 7

interface Props {
  onClose?: () => void
}

export default function ContextSurface({ onClose }: Props) {
  const { selectedId, projects } = useProjects()
  const pid = selectedId ?? ''

  const fields = useSchema(s => s.byProject[pid] ?? [])
  const { load: loadSchema } = useSchema()

  const { byProject, refresh: refreshDocs } = useDocs()
  const docs = byProject[pid] ?? []
  const { open: openReview } = useReview()

  const project = projects.find(p => p.project_id === pid) ?? null

  useEffect(() => {
    if (!pid) return
    void loadSchema(pid)
    void refreshDocs(pid)
  }, [pid, loadSchema, refreshDocs])

  // Log placeholder metrics once — surfaces the deferred wiring
  useEffect(() => {
    if (!pid) return
    console.log('[ContextSurface] metrics section uses placeholder data — useEval not wired yet')
  }, [pid])

  // ── schema header hint ───────────────────────────────────────────
  const versionStr = project?.active_version_id
    ? `v${project.active_version_id} frozen`
    : 'v0 draft'
  const schemaHint = `${fields.length} fields · ${versionStr}`

  // ── docs display ─────────────────────────────────────────────────
  const visibleDocs = docs.slice(0, MAX_VISIBLE_DOCS)
  const docsHint = `${visibleDocs.length} of ${docs.length} shown`

  // ── no project selected ──────────────────────────────────────────
  if (!selectedId) {
    return (
      <div className="ctx">
        <button className="ctx-close" onClick={onClose} title="Close context">
          <X size={13} strokeWidth={1.8} />
        </button>
        <div className="ctx-section">
          <p className="micro" style={{ paddingTop: 24, textAlign: 'center' }}>
            select a project to see context
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="ctx">
      {/* ── close button ─────────────────────────────────────────── */}
      <button className="ctx-close" onClick={onClose} title="Close context">
        <X size={13} strokeWidth={1.8} />
      </button>

      {/* ── section 1: schema.json ───────────────────────────────── */}
      <div className="ctx-section">
        <div className="ctx-h">
          <span>schema.json</span>
          <span className="small">{schemaHint}</span>
        </div>
        <div className="ctx-card">
          {fields.length === 0 ? (
            <div className="schemaRow" style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}>
              no schema yet — type /init in the chat
            </div>
          ) : (
            <>
              {fields.slice(0, MAX_VISIBLE_FIELDS).map(f => (
                <div key={f.name} className="schemaRow">
                  <span>{f.name}</span>
                  <span className="typ">{f.type}</span>
                </div>
              ))}
              {fields.length > MAX_VISIBLE_FIELDS && (
                <div className="schemaRow" style={{ color: 'var(--ink-5)', fontStyle: 'italic' }}>
                  + {fields.length - MAX_VISIBLE_FIELDS} more
                </div>
              )}
            </>
          )}
        </div>
        <p className="micro" style={{ marginTop: 8 }}>
          The schema becomes the agent's prompt at publish time. Edit through conversation.
        </p>
      </div>

      {/* ── section 2: docs/ ─────────────────────────────────────── */}
      <div className="ctx-section">
        <div className="ctx-h">
          <span>docs/</span>
          <span className="small">{docsHint}</span>
        </div>
        <div className="ctx-card" style={{ padding: '4px 0', gap: 0 }}>
          {docs.length === 0 ? (
            <div className="doc" style={{ color: 'var(--ink-4)', fontStyle: 'italic', cursor: 'default' }}>
              no docs yet — drop PDFs into the chat
            </div>
          ) : (
            visibleDocs.map(d => (
              <div
                key={d.doc_id}
                className="doc"
                onClick={() => openReview(pid, d.doc_id)}
                role="button"
                tabIndex={0}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') openReview(pid, d.doc_id) }}
              >
                <span className="nm">{d.filename}</span>
                <span className={`stat ${toPillClass(d)}`}>{toPillLabel(d)}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── section 3: metrics/ ──────────────────────────────────── */}
      <div className="ctx-section">
        <div className="ctx-h">
          <span>metrics/</span>
          <span className="small">latest eval</span>
        </div>
        <div className="ctx-card">
          {PLACEHOLDER_METRICS.map(m => (
            <div key={m.k} className="metric">
              <span className="k">{m.k}</span>
              <span className={`v ${m.tone}`}>{m.v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
