// frontend/src/components/Context/ContextSurface.tsx
//
// Right rail — metrics surface.
//
// Layout (claude.ai wiggle-panel pattern):
//   <aside class="ctx">                  ← Shell-provided; rail-gray gutter
//     ├─ .ctx-actions (top toolbar — toggle lives here, OUTSIDE the panel)
//     └─ .ctx-panel  (one rounded white card filling the rest; flex:1 → reaches
//                     the bottom of the viewport even when content is short)
//         └─ sections of metric rows
//
// IMPORTANT: this component returns a Fragment, NOT a wrapper <div>. The
// Shell already renders the `<aside class="ctx">`; if we add another .ctx
// wrapper here it nests inside, breaks `flex:1`, and the panel collapses
// to content-height instead of stretching to the rail bottom.
import { useEffect } from 'react'

import { useProjects } from '../../stores/projects'
import { useEval } from '../../stores/eval'
import type { EvalSnapshot } from '../../lib/api'
import PanelToggle from '../Shell/PanelToggle'

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

type ContextSurfaceProps = {
  onToggleRight?: () => void
}

export default function ContextSurface({ onToggleRight }: ContextSurfaceProps = {}) {
  const selectedSlug = useProjects(s => s.selectedSlug)
  const slug = selectedSlug ?? ''

  const evalSnap = useEval(s => (slug ? s.byProject[slug] : undefined))
  const loadEval = useEval(s => s.load)

  useEffect(() => {
    if (!slug) return
    void loadEval(slug)
  }, [slug, loadEval])

  const actions = onToggleRight ? (
    <div className="ctx-actions">
      <PanelToggle
        side="right"
        hidden={false}
        onClick={onToggleRight}
        className="ctx-toggle"
      />
    </div>
  ) : null

  if (!selectedSlug) {
    return (
      <>
        {actions}
        <div className="ctx-panel">
          <p className="micro" style={{ paddingTop: 16, textAlign: 'center' }}>
            select a project to see metrics
          </p>
        </div>
      </>
    )
  }

  const metrics = evalSnap ? deriveMetrics(evalSnap) : null
  const metricsHint = metrics?.hint ?? 'latest eval'

  return (
    <>
      {actions}
      <div className="ctx-panel">
        <div className="ctx-h">
          <span>metrics/</span>
          <span className="small">{metricsHint}</span>
        </div>
        {metrics === null ? (
          <p className="micro" style={{ paddingTop: 4 }}>
            no eval yet — type /eval in the chat
          </p>
        ) : (
          <div className="ctx-rows">
            {metrics.rows.map(m => (
              <div key={m.k} className="metric">
                <span className="k">{m.k}</span>
                <span className={`v ${m.tone}`}>{m.v}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
