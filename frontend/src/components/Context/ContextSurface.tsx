// frontend/src/components/Context/ContextSurface.tsx
import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { useProjects } from '../../stores/projects'
import { useSchema } from '../../stores/schema'
import { useDocs } from '../../stores/docs'
import { useEval } from '../../stores/eval'
import { useReview } from '../../stores/review'
import { docStatus } from '../../types/review'
import type { DocSummary } from '../../types/review'
import type { EvalSnapshot } from '../../lib/api'

function toPillClass(doc: DocSummary): string {
  const s = docStatus(doc)
  if (s === 'reviewed') return 'rev'
  if (s === 'draft') return 'pen'
  return 'new'
}

function toPillLabel(doc: DocSummary): string {
  const s = docStatus(doc)
  if (s === 'reviewed') return 'reviewed'
  if (s === 'draft') return 'pending'
  return 'new'
}

type MetricTone = 'ok' | 'mid' | 'bad'

function toneFor(v: number): MetricTone {
  if (v >= 0.85) return 'ok'
  if (v >= 0.65) return 'mid'
  return 'bad'
}

interface MetricRow {
  k: string
  v: string
  tone: MetricTone
}

// Visible-for-test export — keeps the derivation pure for unit tests if we
// want to grow them later. (See ContextSurface.test.tsx for the rendered shape.)
export function deriveMetrics(snap: EvalSnapshot): { rows: MetricRow[]; hint: string } {
  const n = snap.per_field.length
  const macroP = n === 0 ? 0 : snap.per_field.reduce((a, f) => a + f.precision, 0) / n
  const macroR = n === 0 ? 0 : snap.per_field.reduce((a, f) => a + f.recall, 0) / n
  const macroF = snap.macro_f1
  const coverage = snap.n_docs === 0 ? 0 : snap.n_reviewed / snap.n_docs
  const rows: MetricRow[] = [
    { k: 'precision', v: macroP.toFixed(2), tone: toneFor(macroP) },
    { k: 'recall',    v: macroR.toFixed(2), tone: toneFor(macroR) },
    { k: 'f1',        v: macroF.toFixed(2), tone: toneFor(macroF) },
    { k: 'coverage',  v: `${Math.round(coverage * 100)}%`, tone: toneFor(coverage) },
  ]
  const hint = `macro ${macroF.toFixed(2)} · ${snap.n_reviewed} reviewed`
  return { rows, hint }
}

const MAX_VISIBLE_DOCS = 9
const MAX_VISIBLE_FIELDS = 7

export default function ContextSurface() {
  const { selectedId, projects } = useProjects()
  const pid = selectedId ?? ''

  const fields = useSchema(useShallow(s => s.byProject[pid] ?? []))
  const loadSchema = useSchema(s => s.load)

  const docs = useDocs(useShallow(s => s.byProject[pid] ?? []))
  const refreshDocs = useDocs(s => s.refresh)

  const evalSnap = useEval(s => (pid ? s.byProject[pid] : undefined))
  const loadEval = useEval(s => s.load)

  const { open: openReview } = useReview()
  const project = projects.find(p => p.project_id === pid) ?? null

  useEffect(() => {
    if (!pid) return
    void loadSchema(pid)
    void refreshDocs(pid)
    void loadEval(pid)
  }, [pid, loadSchema, refreshDocs, loadEval])

  const versionStr = project?.active_version_id
    ? `${project.active_version_id} frozen`
    : 'v0 draft'
  const schemaHint = `${fields.length} fields · ${versionStr}`

  const visibleDocs = docs.slice(0, MAX_VISIBLE_DOCS)
  const docsHint = `${visibleDocs.length} of ${docs.length} shown`

  if (!selectedId) {
    return (
      <div className="ctx">
        <div className="ctx-section">
          <p className="micro" style={{ paddingTop: 24, textAlign: 'center' }}>
            select a project to see context
          </p>
        </div>
      </div>
    )
  }

  // ── metrics derivation ───────────────────────────────────────────
  const metrics = evalSnap ? deriveMetrics(evalSnap) : null
  const metricsHint = metrics?.hint ?? 'latest eval'

  return (
    <div className="ctx">
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
          <span className="small">{metricsHint}</span>
        </div>
        <div className="ctx-card">
          {metrics === null ? (
            <div className="metric" style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}>
              <span className="k">no eval yet — type /eval in the chat</span>
            </div>
          ) : (
            metrics.rows.map(m => (
              <div key={m.k} className="metric">
                <span className="k">{m.k}</span>
                <span className={`v ${m.tone}`}>{m.v}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
