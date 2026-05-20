// frontend/src/components/Chat/EvalCard.tsx
//
// M12.x — accuracy-first eval card. Headline shows field accuracy + doc
// accuracy (non-engineer-comprehensible). Per-field table drops P/R columns;
// each row shows accuracy + the `absent both sides` hint when applicable.
// `not_applicable` rows render as em-dash (—) instead of red `0%`.
import { Fragment, useState } from 'react'
import type { ChatEvent } from '../../types/chat'
import ToolCall from './ToolCall'
import ToolRow from './ToolRow'
import { toolShortHint } from '../../lib/toolHint'
import { pathForEvalMatrix } from '../../lib/slugUrl'

// ── Types ──────────────────────────────────────────────────────────────────

export type EvalTone = 'ok' | 'mid' | 'bad'

export interface EvalRow {
  f: string                // field name
  accuracy: number | null  // M12.x — null when not_applicable
  correct: number          // M12.x — `accuracy = correct / total` denominator
  total: number
  nAbsentBoth: number      // M12.x — UI hint for sparsely-present fields
  notApplicable: boolean   // M12.x — render `—`, never red 0%
  tone: EvalTone
  err?: string             // error explanation when expanded
}

export interface EvalCardProps {
  rows: EvalRow[]
  scoredAt: string         // "just now" or ISO timestamp
  overall: number          // field_accuracy_macro
  /** M12 — when the score result carries `doc_accuracy`, display it
   *  prominently alongside field accuracy. Optional for back-compat with
   *  legacy results that pre-date M12. M12.x.c: smooth semantics on new
   *  writes (mean of per-doc accuracy). */
  docAccuracy?: number | null
  /** M12 — when known, render an "open full matrix" link to the dir-form
   *  matrix view. Requires both slug and ts; either missing → omit link. */
  slug?: string | null
  ts?: string | null
}

// ── Tone helper ────────────────────────────────────────────────────────────

// M12.x thresholds — accuracy is a stricter measure than F1, so the
// "ok" cutoff matches the publish-soft threshold (0.90).
function toTone(accuracy: number): EvalTone {
  if (accuracy >= 0.90) return 'ok'
  if (accuracy >= 0.75) return 'mid'
  return 'bad'
}

// ── Adapter ────────────────────────────────────────────────────────────────

interface ScoreResult {
  field_accuracy_macro?: number | null
  macro_f1?: number | null  // legacy
  doc_accuracy?: number | null
  // M12.x.c — sibling strict metric, optional on read.
  doc_accuracy_strict?: number | null
  per_field?: Array<{
    field: string
    accuracy?: number | null
    correct?: number
    total?: number
    n_absent_both?: number
    not_applicable?: boolean
    // legacy fields tolerated on read
    precision?: number
    recall?: number
    f1?: number
    support?: number
    error_explanation?: string
  }>
  scored_at?: string
  ts?: string
}

function parseScoreResult(raw: unknown): ScoreResult | null {
  // If string, try JSON.parse first
  let obj: unknown = raw
  if (typeof raw === 'string') {
    try { obj = JSON.parse(raw) } catch { return null }
  }
  if (!obj || typeof obj !== 'object') return null
  const o = obj as Record<string, unknown>
  // M12.x — accept either the new headline or the legacy one, or any
  // per-field accuracy we can synthesize from. Old summaries on disk only
  // carry `macro_f1`; new writes carry `field_accuracy_macro`; both may be
  // explicitly null when the per_field row is the truth source.
  const headlineCandidate =
    typeof o.field_accuracy_macro === 'number' ||
    typeof o.macro_f1 === 'number'
  const hasPerFieldAccuracy =
    Array.isArray(o.per_field) &&
    o.per_field.some((f) => {
      const r = f as Record<string, unknown>
      return typeof r?.accuracy === 'number' || typeof r?.f1 === 'number'
    })
  if (!headlineCandidate && !hasPerFieldAccuracy) return null
  return o as unknown as ScoreResult
}

export function adaptScoreResult(
  result: unknown,
): {
  rows: EvalRow[]
  overall: number
  scoredAt: string
  docAccuracy?: number | null
  ts?: string | null
} | null {
  const sr = parseScoreResult(result)
  if (!sr) return null

  const perField = Array.isArray(sr.per_field) ? sr.per_field : []
  const rows: EvalRow[] = perField.map((f) => {
    const accuracy =
      typeof f.accuracy === 'number'
        ? f.accuracy
        : typeof f.f1 === 'number'  // legacy fallback so old runs still render something
          ? f.f1
          : null
    const correct = typeof f.correct === 'number' ? f.correct : 0
    const total =
      typeof f.total === 'number'
        ? f.total
        : typeof f.support === 'number' ? f.support : 0
    const nAbsentBoth =
      typeof f.n_absent_both === 'number' ? f.n_absent_both : 0
    const notApplicable =
      f.not_applicable === true || (typeof f.total === 'number' && f.total === 0)
    return {
      f: typeof f.field === 'string' ? f.field : '?',
      accuracy: notApplicable ? null : (accuracy ?? 0),
      correct,
      total,
      nAbsentBoth,
      notApplicable,
      tone: notApplicable ? 'mid' : toTone(accuracy ?? 0),
      err: typeof f.error_explanation === 'string' ? f.error_explanation : undefined,
    }
  })

  // M12.x — synthesize the headline if the backend didn't write it (legacy
  // summary): mean of per-field accuracy over applicable fields. Falls back
  // to legacy macro_f1 only when no per-field accuracy is present at all.
  let overall: number
  if (typeof sr.field_accuracy_macro === 'number') {
    overall = sr.field_accuracy_macro
  } else {
    const applicable = rows.filter((r) => !r.notApplicable && r.accuracy != null)
    if (applicable.length > 0) {
      overall =
        applicable.reduce((a, r) => a + (r.accuracy ?? 0), 0) / applicable.length
    } else if (typeof sr.macro_f1 === 'number') {
      overall = sr.macro_f1
    } else {
      overall = 0
    }
  }

  const scoredAt =
    (typeof sr.scored_at === 'string' && sr.scored_at) ||
    (typeof sr.ts === 'string' && sr.ts) ||
    'just now'
  return {
    rows,
    overall,
    scoredAt,
    docAccuracy: typeof sr.doc_accuracy === 'number' ? sr.doc_accuracy : null,
    ts: typeof sr.ts === 'string' ? sr.ts : null,
  }
}

// ── EvalCard ───────────────────────────────────────────────────────────────

export default function EvalCard({
  rows,
  scoredAt,
  overall,
  docAccuracy,
  slug,
  ts,
}: EvalCardProps) {
  const [open, setOpen] = useState<string | null>(null)

  return (
    <div className="eval-card" data-testid="eval-card">
      {/* header */}
      <div className="eh">
        <span className="nm">eval result</span>
        <span className="stamp">{scoredAt}</span>
        {docAccuracy != null && (
          <span className="agg">
            <span className="lbl">doc acc</span>
            {(docAccuracy * 100).toFixed(1)}%
          </span>
        )}
        <span className="agg">
          <span className="lbl">field acc</span>
          {(overall * 100).toFixed(1)}%
        </span>
      </div>

      {/* column header row */}
      <div className="eval-row head">
        <span className="f">field</span>
        <span className="num">accuracy</span>
        <span></span>
      </div>

      {rows.length === 0 && (
        <div className="eval-row" style={{ gridTemplateColumns: '1fr' }}>
          <span className="f" style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}>
            per-field breakdown not available
          </span>
        </div>
      )}

      {slug && ts && (
        <div className="eval-row" style={{ gridTemplateColumns: '1fr' }}>
          <a
            href={pathForEvalMatrix(slug, ts)}
            className="f"
            style={{ color: 'var(--ochre-2)', textDecoration: 'underline' }}
          >
            ↗ open full matrix
          </a>
        </div>
      )}

      {rows.map(r => {
        // M12.x — accuracy hint: e.g. "21/21 correct · 18 absent both sides".
        // `not_applicable` rows show no count (total=0).
        const hint = r.notApplicable
          ? 'not exercised by reviewed set'
          : r.nAbsentBoth > 0
            ? `${r.correct}/${r.total} correct · ${r.nAbsentBoth} absent both sides`
            : `${r.correct}/${r.total} correct`
        const accDisplay = r.notApplicable
          ? '—'
          : `${((r.accuracy ?? 0) * 100).toFixed(1)}%`
        return (
          <Fragment key={r.f}>
            <div
              className="eval-row"
              onClick={() => r.err && setOpen(o => (o === r.f ? null : r.f))}
              style={{ cursor: r.err ? 'pointer' : 'default' }}
              title={hint}
            >
              <span className="f">
                {r.f}
                {r.err && (
                  <span style={{ color: 'var(--ochre-2)', marginLeft: 6, fontSize: 10 }}>
                    ▾ explain
                  </span>
                )}
              </span>
              <span
                className={r.notApplicable
                  ? 'num'
                  : `num acc ${r.tone}`}
                style={r.notApplicable
                  ? { color: 'var(--ink-4)' }
                  : undefined}
              >
                {accDisplay}
              </span>
              <div className="bar">
                {!r.notApplicable && (
                  <i className={r.tone} style={{ width: `${(r.accuracy ?? 0) * 100}%` }} />
                )}
              </div>
            </div>
            {open === r.f && r.err && (
              <div className="eval-row expand">
                <span>
                  <b>
                    {r.f} · {accDisplay}
                  </b>{' '}
                  — {r.err}
                </span>
              </div>
            )}
          </Fragment>
        )
      })}
    </div>
  )
}

// ── EvalCardAdapter ────────────────────────────────────────────────────────
// Wraps a score tool_call event: renders ToolCall + EvalCard when per_field
// data is present, or falls back to ToolCall-only.

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

export function EvalCardAdapter({ call, slug }: { call: ToolCallEvent; slug?: string | null }) {
  const status = call.ok === false ? 'err' : call.tool_result == null ? 'run' : 'done'
  const displayName = call.tool_name.replace(/^mcp__emerge_tools__/, '')
  const hint = status !== 'run' ? toolShortHint(call.tool_name, call.tool_result) : null

  const adapted =
    status === 'done' ? adaptScoreResult(call.tool_result) : null

  if (adapted && adapted.rows.length > 0) {
    // Full table: ToolCall (collapsed) + sibling EvalCard
    return (
      <>
        <ToolCall name={displayName} args={hint ?? undefined} status={status}>
          <ToolRow glyph="·" label="input" value={JSON.stringify(call.tool_input)} />
          <ToolRow glyph="↳" label="result" value={`field_accuracy=${adapted.overall.toFixed(3)}`} />
        </ToolCall>
        <EvalCard
          rows={adapted.rows}
          scoredAt={adapted.scoredAt}
          overall={adapted.overall}
          docAccuracy={adapted.docAccuracy}
          slug={slug ?? null}
          ts={adapted.ts ?? null}
        />
      </>
    )
  }

  // Fallback: show ToolCall normally (no per_field or parse failed)
  return (
    <ToolCall name={displayName} args={hint ?? undefined} status={status}>
      <ToolRow glyph="·" label="input" value={JSON.stringify(call.tool_input)} />
      {call.tool_result != null && (
        <ToolRow
          glyph="↳"
          label="result"
          value={typeof call.tool_result === 'string' ? call.tool_result : JSON.stringify(call.tool_result, null, 2)}
        />
      )}
    </ToolCall>
  )
}
