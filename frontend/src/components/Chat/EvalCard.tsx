// frontend/src/components/Chat/EvalCard.tsx
import { Fragment, useState } from 'react'
import type { ChatEvent } from '../../types/chat'
import ToolCall from './ToolCall'
import ToolRow from './ToolRow'
import { toolShortHint } from '../../lib/toolHint'

// ── Types ──────────────────────────────────────────────────────────────────

export type EvalTone = 'ok' | 'mid' | 'bad'

export interface EvalRow {
  f: string       // field name
  p: number       // precision
  r: number       // recall
  f1: number
  n: number       // support count
  tone: EvalTone
  err?: string    // error explanation when expanded
}

export interface EvalCardProps {
  rows: EvalRow[]
  scoredAt: string    // "just now" or ISO timestamp
  overall: number     // e.g. 0.914
}

// ── Tone helper ────────────────────────────────────────────────────────────

function toTone(f1: number): EvalTone {
  if (f1 >= 0.85) return 'ok'
  if (f1 >= 0.65) return 'mid'
  return 'bad'
}

// ── Adapter ────────────────────────────────────────────────────────────────

interface ScoreResult {
  macro_f1: number
  per_field?: Array<{
    field: string
    precision: number
    recall: number
    f1: number
    support: number
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
  if (typeof o.macro_f1 !== 'number') return null
  return o as unknown as ScoreResult
}

export function adaptScoreResult(
  result: unknown,
): { rows: EvalRow[]; overall: number; scoredAt: string } | null {
  const sr = parseScoreResult(result)
  if (!sr) return null

  const overall = sr.macro_f1
  const perField = Array.isArray(sr.per_field) ? sr.per_field : []
  const rows: EvalRow[] = perField.map((f: Record<string, unknown>) => {
    const f1 = typeof f.f1 === 'number' ? f.f1 : 0
    return {
      f: typeof f.field === 'string' ? f.field : '?',
      p: typeof f.precision === 'number' ? f.precision : 0,
      r: typeof f.recall === 'number' ? f.recall : 0,
      f1,
      n: typeof f.support === 'number' ? f.support : 0,
      tone: toTone(f1),
      err: typeof f.error_explanation === 'string' ? f.error_explanation : undefined,
    }
  })
  const scoredAt =
    (typeof sr.scored_at === 'string' && sr.scored_at) ||
    (typeof sr.ts === 'string' && sr.ts) ||
    'just now'
  return { rows, overall, scoredAt }
}

// ── EvalCard ───────────────────────────────────────────────────────────────

export default function EvalCard({ rows, scoredAt, overall }: EvalCardProps) {
  const [open, setOpen] = useState<string | null>(null)

  return (
    <div className="eval-card" data-testid="eval-card">
      {/* header */}
      <div className="eh">
        <span className="nm">eval result</span>
        <span className="stamp">{scoredAt}</span>
        <span className="agg">
          <span className="lbl">F1</span>
          {overall.toFixed(3)}
        </span>
      </div>

      {/* column header row */}
      <div className="eval-row head">
        <span className="f">field</span>
        <span className="num">P</span>
        <span className="num">R</span>
        <span className="num">F1</span>
        <span></span>
      </div>

      {rows.length === 0 && (
        <div className="eval-row" style={{ gridTemplateColumns: '1fr' }}>
          <span className="f" style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}>
            per-field breakdown not available
          </span>
        </div>
      )}

      {rows.map(r => (
        <Fragment key={r.f}>
          <div
            className="eval-row"
            onClick={() => r.err && setOpen(o => (o === r.f ? null : r.f))}
            style={{ cursor: r.err ? 'pointer' : 'default' }}
          >
            <span className="f">
              {r.f}
              {r.err && (
                <span style={{ color: 'var(--ochre-2)', marginLeft: 6, fontSize: 10 }}>
                  ▾ explain
                </span>
              )}
            </span>
            <span className="num">{r.p.toFixed(2)}</span>
            <span className="num">{r.r.toFixed(2)}</span>
            <span className={`num f1 ${r.tone}`}>{r.f1.toFixed(2)}</span>
            <div className="bar">
              <i className={r.tone} style={{ width: `${r.f1 * 100}%` }} />
            </div>
          </div>
          {open === r.f && r.err && (
            <div className="eval-row expand">
              <span>
                <b>
                  {r.f} · {r.f1.toFixed(2)}
                </b>{' '}
                — {r.err}
              </span>
            </div>
          )}
        </Fragment>
      ))}
    </div>
  )
}

// ── EvalCardAdapter ────────────────────────────────────────────────────────
// Wraps a score tool_call event: renders ToolCall + EvalCard when per_field
// data is present, or falls back to ToolCall-only.

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

export function EvalCardAdapter({ call }: { call: ToolCallEvent }) {
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
          <ToolRow glyph="↳" label="result" value={`macro_f1=${adapted.overall.toFixed(3)}`} />
        </ToolCall>
        <EvalCard rows={adapted.rows} scoredAt={adapted.scoredAt} overall={adapted.overall} />
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
