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

// M12.x — accuracy is stricter than F1, so the cutoffs match the publish
// soft/hard threshold (0.90 ok, 0.75 mid).
function toneFor(v: number): MetricTone {
  if (v >= 0.90) return 'ok'
  if (v >= 0.75) return 'mid'
  return 'bad'
}

interface MetricRow {
  k: string
  v: string
  tone: MetricTone
}

// M12.x — back-compat: synthesize `field_accuracy_macro` from per_field
// accuracy when a legacy summary is loaded (the field will be null on
// pre-M12.x summaries).
function fieldAccuracyMacro(snap: EvalSnapshot): number {
  if (snap.field_accuracy_macro != null) return snap.field_accuracy_macro
  const applicable = snap.per_field.filter(
    (p) => !p.not_applicable && typeof p.accuracy === 'number',
  )
  if (applicable.length === 0) {
    // Legacy fallback: if all we have is the old `macro_f1`, surface it.
    // Better than showing 0 and worse than the future-state real number.
    return snap.macro_f1 ?? 0
  }
  return applicable.reduce((a, p) => a + (p.accuracy ?? 0), 0) / applicable.length
}

export function deriveMetrics(snap: EvalSnapshot): { rows: MetricRow[]; hint: string } {
  const fieldAcc = fieldAccuracyMacro(snap)
  const docAcc = snap.doc_accuracy ?? null
  const docAccNoArray = snap.doc_accuracy_without_array ?? null
  const coverage = snap.n_docs === 0 ? 0 : snap.n_reviewed / snap.n_docs

  // M12.x.c — when the scalar-only sibling is materially different (Δ ≥ 0.05),
  // expand into two rows so the items-heavy noise vs. clean-signal split is
  // visible at a glance.
  const showWithoutArray =
    docAcc != null && docAccNoArray != null
      ? Math.abs(docAccNoArray - docAcc) >= 0.05
      : false

  const rows: MetricRow[] = [
    { k: 'field accuracy', v: `${(fieldAcc * 100).toFixed(1)}%`, tone: toneFor(fieldAcc) },
  ]
  if (showWithoutArray) {
    rows.push(
      {
        k: 'doc accuracy',
        v: docAcc == null ? '—' : `${(docAcc * 100).toFixed(1)}%`,
        tone: toneFor(docAcc ?? 0),
      },
      {
        k: 'doc accuracy (去除 items)',
        v: docAccNoArray == null
          ? '—'
          : `${(docAccNoArray * 100).toFixed(1)}%`,
        tone: toneFor(docAccNoArray ?? 0),
      },
    )
  } else {
    rows.push({
      k: 'doc accuracy',
      v: docAcc == null ? '—' : `${(docAcc * 100).toFixed(1)}%`,
      tone: toneFor(docAcc ?? 0),
    })
  }
  rows.push({ k: 'coverage', v: `${Math.round(coverage * 100)}%`, tone: toneFor(coverage) })

  const hint = `${(fieldAcc * 100).toFixed(1)}% · ${snap.n_reviewed} reviewed`
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
