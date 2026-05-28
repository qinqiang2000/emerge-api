// BenchDiff — 2-row compare modal.
//
// Surface mounted on top of <BenchOverlay> when the user picks exactly two
// rows from the matrix and clicks "compare →" in the selection bar. It
// gives the per-field Δ breakdown + a literal prompt-text diff so the user
// can reason about whether a delta is "real" (prompt rewrite landed a
// genuine improvement) or just provider noise (same prompt, different model).
//
// Layout (top → bottom):
//   1. header        — COMPARE chip + title "{baseP} · {baseM} → {targP} · {targM}" + ✕
//   2. summary       — score Δ pill + "axes changed" pills (prompt | model | none)
//   3. per-field Δ   — one row per field: name · base.N/total → target.N/total ·
//                      width-encoded bar · ±N pill
//   4. prompt-text   — only when prompts differ; two-column pre with simple
//                      line-by-line set-membership diff (no diff-match-patch).
//                      target body: lines not in base get `.b-line-added`.
//                      base body:   lines not in target get `.b-line-removed`.
//                      Both bodies null → loading skeleton.
//   5. footer        — close · copy-as-text (placeholder, no onClick) · primary
//                      "promote {targetPromptLabel}" → onPromote(target.id)
//
// Close affordances:
//   - ✕ button             → onClose
//   - backdrop click       → onClose (modal click stopPropagation)
//   - window keydown 'Esc' → onClose
//
// Diff implementation note: this is intentionally NOT a token-aware diff.
// Per CLAUDE.md the goal is "visible signal that something moved", not a
// review-grade diff renderer. Lines are split on '\n' and the simplest
// set membership check is used. Empty / whitespace-only lines are skipped
// to avoid every blank line lighting up as "changed".
import { useEffect } from 'react'

import { useT } from '../../i18n'
import type { BenchRow } from '../../types/bench'
import './Bench.css'

interface Props {
  base: BenchRow
  target: BenchRow
  /** Prompt body text, formatted by the caller (overlay) from
   *  `{schema, global_notes}`. `null` while the fetch is in-flight. */
  basePromptBody: string | null
  /** Same as `basePromptBody` for the target row. */
  targetPromptBody: string | null
  /** Active prompt's schema field names (iteration order matches BenchMatrix). */
  fields: string[]
  /** `pr_xxx` → display label (taken from BenchResponse.prompts). */
  promptLabels: Record<string, string>
  /** `m_xxx` → display label (taken from BenchResponse.models). */
  modelLabels: Record<string, string>
  onClose: () => void
  onPromote: (rowId: string) => void
}

function fmtDelta(d: number | null | undefined): string | null {
  if (d == null) return null
  const sign = d > 0 ? '+' : ''
  // Drop trailing zeros but keep one digit so "+0.0" doesn't degrade to "+0."
  const body = d.toFixed(3).replace(/0+$/, '').replace(/\.$/, '.0')
  return sign + body
}

/** First "word" of a label — used to render a compact model short-name in
 *  the title (e.g. "gemini-2.5-flash" → "gemini"). */
function shortModel(label: string | undefined, fallback: string): string {
  if (!label) return fallback
  return label.split('-')[0] || label
}

interface FieldDelta {
  field: string
  base: number
  targ: number
  total: number
  delta: number
}

export default function BenchDiff({
  base,
  target,
  basePromptBody,
  targetPromptBody,
  fields,
  promptLabels,
  modelLabels,
  onClose,
  onPromote,
}: Props) {
  const t = useT()

  // Close on Esc — single window-level handler keeps the keyboard contract
  // consistent with EvalMatrixModal etc. We deliberately don't read
  // `e.target` because chord-style modals always want Esc to win.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const samePrompt = base.prompt_id === target.prompt_id
  const sameModel = base.model_id === target.model_id

  const basePromptLabel = promptLabels[base.prompt_id] ?? base.prompt_id
  const targetPromptLabel = promptLabels[target.prompt_id] ?? target.prompt_id
  const baseModelShort = shortModel(modelLabels[base.model_id], base.model_id)
  const targetModelShort = shortModel(modelLabels[target.model_id], target.model_id)

  // Per-field deltas (skip when either side has no cell for the field —
  // can't form a meaningful delta).
  const fieldDeltas: FieldDelta[] = []
  for (const f of fields) {
    const b = base.cells[f]
    const tg = target.cells[f]
    if (!b || !tg) continue
    fieldDeltas.push({
      field: f,
      base: b.correct,
      targ: tg.correct,
      total: b.total,
      delta: tg.correct - b.correct,
    })
  }

  const scoreDelta =
    base.score != null && target.score != null
      ? target.score - base.score
      : null

  // Line-diff: skip pure-whitespace lines so the visual signal sticks to
  // meaningful content edits. Split-by-'\n' is sufficient — we explicitly
  // do not engage diff-match-patch (CLAUDE.md / plan red line).
  const baseLines = (basePromptBody ?? '').split('\n')
  const targLines = (targetPromptBody ?? '').split('\n')
  const baseSet = new Set(baseLines.map(l => l.trim()))
  const targSet = new Set(targLines.map(l => l.trim()))

  const showPromptDiff = !samePrompt

  return (
    <div
      className="b-diff-back"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="bench-diff"
    >
      <div className="b-diff-modal" onClick={(e) => e.stopPropagation()}>
        <header className="b-diff-hd">
          <div className="b-diff-hd-l">
            <span className="b-diff-kind">{t('bench.diff.kind')}</span>
            <h2 className="b-diff-title">
              {basePromptLabel} · {baseModelShort}
              <span className="arr">→</span>
              {targetPromptLabel} · {targetModelShort}
            </h2>
          </div>
          <button
            type="button"
            className="b-diff-x"
            onClick={onClose}
            aria-label={t('bench.diff.close')}
          >
            ✕
          </button>
        </header>

        <div className="b-diff-summary">
          <div className="b-diff-summary-cell">
            <span className="lbl">{t('bench.diff.score.headline')}</span>
            <span className="val">
              {base.score != null ? `${(base.score * 100).toFixed(1)}%` : '—'}
              <span className="arr">→</span>
              {target.score != null ? `${(target.score * 100).toFixed(1)}%` : '—'}
              {scoreDelta != null && (
                <span className={'pill ' + (scoreDelta > 0 ? 'up' : scoreDelta < 0 ? 'down' : 'flat')}>
                  {fmtDelta(scoreDelta)}
                </span>
              )}
            </span>
          </div>
          <div className="b-diff-summary-cell">
            <span className="lbl">{t('bench.diff.axes_changed')}</span>
            <span className="val">
              {!samePrompt && <span className="pill">{t('bench.diff.axes.prompt')}</span>}
              {!sameModel && <span className="pill">{t('bench.diff.axes.model')}</span>}
              {samePrompt && sameModel && (
                <span className="muted">{t('bench.diff.axes.none')}</span>
              )}
            </span>
          </div>
        </div>

        <div className="b-diff-fields">
          <div className="b-diff-fields-h">{t('bench.diff.per_field_h')}</div>
          {fieldDeltas.length === 0 ? (
            <div className="b-diff-fields-empty">{t('bench.diff.per_field_empty')}</div>
          ) : (
            fieldDeltas.map((fd) => {
              const pct = fd.total > 0 ? fd.delta / fd.total : 0
              const cls = fd.delta > 0 ? 'up' : fd.delta < 0 ? 'down' : 'flat'
              return (
                <div key={fd.field} className="b-diff-frow">
                  <span className="b-diff-fn">{fd.field}</span>
                  <span className="b-diff-base">{fd.base}/{fd.total}</span>
                  <span className="b-diff-arr">→</span>
                  <span className="b-diff-targ">{fd.targ}/{fd.total}</span>
                  <span className="b-diff-bar-wrap">
                    <span
                      className={'b-diff-bar ' + cls}
                      style={{ width: Math.min(Math.abs(pct) * 100, 100) + '%' }}
                    />
                  </span>
                  <span className={'b-diff-pill ' + cls}>
                    {fd.delta > 0 ? '+' : ''}{fd.delta}
                  </span>
                </div>
              )
            })
          )}
        </div>

        {showPromptDiff && (
          <div className="b-diff-prompt">
            <div className="b-diff-prompt-h">
              <span>{t('bench.diff.prompt_text_h')}</span>
              <span className="b-diff-prompt-tag">{t('bench.diff.prompt_text_tag')}</span>
            </div>
            {basePromptBody == null || targetPromptBody == null ? (
              <div className="b-diff-prompt-loading">{t('bench.diff.prompt.loading')}</div>
            ) : (
              <div className="b-diff-cols">
                <div className="b-diff-col">
                  <div className="b-diff-col-hd">{basePromptLabel}</div>
                  <pre className="b-diff-body base">
                    {baseLines.map((ln, i) => {
                      const trimmed = ln.trim()
                      const isRemoved = trimmed.length > 0 && !targSet.has(trimmed)
                      return (
                        <span key={i} className={isRemoved ? 'b-line-removed' : ''}>
                          {ln + '\n'}
                        </span>
                      )
                    })}
                  </pre>
                </div>
                <div className="b-diff-col">
                  <div className="b-diff-col-hd">{targetPromptLabel}</div>
                  <pre className="b-diff-body targ">
                    {targLines.map((ln, i) => {
                      const trimmed = ln.trim()
                      const isAdded = trimmed.length > 0 && !baseSet.has(trimmed)
                      return (
                        <span key={i} className={isAdded ? 'b-line-added' : ''}>
                          {ln + '\n'}
                        </span>
                      )
                    })}
                  </pre>
                </div>
              </div>
            )}
          </div>
        )}

        <footer className="b-diff-foot">
          <button type="button" className="b-diff-btn" onClick={onClose}>
            {t('bench.diff.close')}
          </button>
          <span className="b-diff-foot-spacer" />
          <button type="button" className="b-diff-btn">
            {t('bench.diff.copy')}
          </button>
          <button
            type="button"
            className="b-diff-btn primary"
            onClick={() => onPromote(target.id)}
          >
            {t('bench.diff.promote', { label: targetPromptLabel })}
          </button>
        </footer>
      </div>
    </div>
  )
}
