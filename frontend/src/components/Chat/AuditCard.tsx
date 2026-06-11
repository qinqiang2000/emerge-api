// frontend/src/components/Chat/AuditCard.tsx
//
// A3 — audit report + audit score cards (adapter pattern, mirrors EvalCard).
// `run_audit` results render as a per-rule ✓/✗/? checklist with a tri-state
// overall badge (pass=moss / warn=ochre / fail=rose, soft fills); `score_audit`
// results render a one-line metric strip + the wrongly-judged rules only.
// Adapters are strict: JSON they don't positively recognize returns null so the
// generic ToolCall rendering is never hijacked.
import type { ChatEvent } from '../../types/chat'
import ToolCall from './ToolCall'
import ToolRow from './ToolRow'
import { toolShortHint } from '../../lib/toolHint'

// ── Types ──────────────────────────────────────────────────────────────────

export type AuditOverall = 'pass' | 'warn' | 'fail'
export type AuditCheckStatus = 'pass' | 'fail' | 'unclear'

export interface AuditEvidenceRow {
  doc: string
  page: number | null
  quote: string
}

export interface AuditCheckRow {
  rule: string
  status: AuditCheckStatus
  reason: string
  level: 'critical' | 'warning'
  decidedBy: 'l1' | 'judge'
  evidence: AuditEvidenceRow[]
}

export interface AuditReportData {
  overall: AuditOverall
  checks: AuditCheckRow[]
  createdAt: string | null
}

export interface AuditScoreData {
  reviewed: number
  accuracy: number
  precision: number
  recall: number
  unclear: number
  wrong: Array<{ rule: string; truth: string; predicted: string }>
  unreviewedRules: string[]
}

// ── Tone mapping (semantic tokens only) ────────────────────────────────────

export function overallToneClasses(overall: AuditOverall): string {
  switch (overall) {
    case 'pass':
      return 'text-moss bg-moss-soft'
    case 'warn':
      return 'text-ochre-2 bg-ochre-soft'
    case 'fail':
      return 'text-rose bg-rose-soft'
  }
}

const OVERALL_LABEL: Record<AuditOverall, string> = {
  pass: 'pass',
  warn: 'warn',
  fail: 'fail',
}

// ── Adapters ───────────────────────────────────────────────────────────────

function asObject(raw: unknown): Record<string, unknown> | null {
  let obj: unknown = raw
  if (typeof raw === 'string') {
    try { obj = JSON.parse(raw) } catch { return null }
  }
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return null
  return obj as Record<string, unknown>
}

const CHECK_STATUSES = new Set(['pass', 'fail', 'unclear'])

/** Tolerant evidence pass-through: missing/non-array → []; entries without a
 * string doc+quote are dropped (mirrors the backend's drop-don't-fail parse). */
function adaptEvidence(raw: unknown): AuditEvidenceRow[] {
  if (!Array.isArray(raw)) return []
  const out: AuditEvidenceRow[] = []
  for (const e of raw) {
    if (!e || typeof e !== 'object') continue
    const ev = e as Record<string, unknown>
    if (typeof ev.doc !== 'string' || typeof ev.quote !== 'string') continue
    out.push({
      doc: ev.doc,
      page: typeof ev.page === 'number' ? ev.page : null,
      quote: ev.quote,
    })
  }
  return out
}

/** run_audit report → card data; null when the JSON isn't an audit report. */
export function adaptAuditReport(raw: unknown): AuditReportData | null {
  const o = asObject(raw)
  if (!o) return null
  const overall = o.overall
  if (overall !== 'pass' && overall !== 'warn' && overall !== 'fail') return null
  if (!Array.isArray(o.checks)) return null
  const checks: AuditCheckRow[] = []
  for (const c of o.checks) {
    if (!c || typeof c !== 'object') return null
    const r = c as Record<string, unknown>
    if (typeof r.rule !== 'string' || !CHECK_STATUSES.has(r.status as string)) {
      return null
    }
    checks.push({
      rule: r.rule,
      status: r.status as AuditCheckStatus,
      reason: typeof r.reason === 'string' ? r.reason : '',
      level: r.level === 'warning' ? 'warning' : 'critical',
      decidedBy: r.decided_by === 'l1' ? 'l1' : 'judge',
      evidence: adaptEvidence(r.evidence),
    })
  }
  return {
    overall,
    checks,
    createdAt: typeof o.created_at === 'string' ? o.created_at : null,
  }
}

/** score_audit result → card data; null when the JSON isn't an audit score. */
export function adaptAuditScore(raw: unknown): AuditScoreData | null {
  const o = asObject(raw)
  if (!o) return null
  // Positive identification: the audit-score envelope always carries per_rule
  // (array), reviewed + accuracy (numbers) and the unclear counter. The
  // extract-eval score result (`per_field`) never has per_rule.
  if (!Array.isArray(o.per_rule)) return null
  if (typeof o.reviewed !== 'number' || typeof o.accuracy !== 'number') return null
  if (typeof o.unclear !== 'number') return null
  const wrong: AuditScoreData['wrong'] = []
  for (const c of o.per_rule) {
    if (!c || typeof c !== 'object') return null
    const r = c as Record<string, unknown>
    if (typeof r.rule !== 'string') return null
    if (r.correct === false) {
      wrong.push({
        rule: r.rule,
        truth: typeof r.truth === 'string' ? r.truth : '?',
        predicted: typeof r.predicted === 'string' ? r.predicted : '?',
      })
    }
  }
  return {
    reviewed: o.reviewed,
    accuracy: o.accuracy,
    precision: typeof o.precision === 'number' ? o.precision : 0,
    recall: typeof o.recall === 'number' ? o.recall : 0,
    unclear: o.unclear,
    wrong,
    unreviewedRules: Array.isArray(o.unreviewed_rules)
      ? o.unreviewed_rules.filter((x): x is string => typeof x === 'string')
      : [],
  }
}

// ── Cards ──────────────────────────────────────────────────────────────────

const STATUS_GLYPH: Record<AuditCheckStatus, { glyph: string; cls: string }> = {
  pass: { glyph: '✓', cls: 'text-moss' },
  fail: { glyph: '✗', cls: 'text-rose' },
  unclear: { glyph: '?', cls: 'text-ink-4' },
}

export function AuditReportCard({ data }: { data: AuditReportData }) {
  const correct = data.checks.filter(c => c.status === 'pass').length
  return (
    <div
      className="border border-rule-soft bg-paper rounded-sm font-mono text-sm"
      data-testid="audit-card"
    >
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-rule-soft">
        <span className="text-ink font-semibold">audit report</span>
        <span
          className={`px-1.5 py-0.5 rounded-sm text-xs font-semibold uppercase ${overallToneClasses(data.overall)}`}
          data-testid="audit-overall"
        >
          {OVERALL_LABEL[data.overall]}
        </span>
        <span className="ml-auto text-ink-4 text-xs">
          {correct}/{data.checks.length}
          {data.createdAt ? ` · ${data.createdAt.slice(0, 19).replace('T', ' ')}` : ''}
        </span>
      </div>
      <div>
        {data.checks.map((c, i) => (
          <div key={i} className="px-3 py-1.5 border-b border-rule-soft last:border-b-0">
            <div className="flex items-start gap-2">
              <span className={`${STATUS_GLYPH[c.status].cls} shrink-0`}>
                {STATUS_GLYPH[c.status].glyph}
              </span>
              <span className="text-ink min-w-0 break-words">{c.rule}</span>
              {c.level === 'warning' && (
                <span className="shrink-0 px-1 rounded-sm text-[10px] text-ochre-2 bg-ochre-soft">
                  警告
                </span>
              )}
              {c.decidedBy === 'l1' && (
                <span
                  className="shrink-0 px-1 rounded-sm text-[10px] text-ink-3 bg-paper-3"
                  title="确定性规则判定，未经 LLM"
                >
                  规则
                </span>
              )}
            </div>
            {c.reason && (
              <div className="pl-5 text-xs text-ink-3 break-words">{c.reason}</div>
            )}
            {/* Evidence: verbatim text quotes only — the card never draws
                boxes/coordinates (spatial expression belongs to the board). */}
            {c.evidence.map((e, j) => (
              <div key={j} className="pl-5 text-xs text-ink-4 break-words">
                「{e.quote}」 — {e.doc}
                {e.page != null ? ` · p${e.page}` : ''}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

export function AuditScoreCard({ data }: { data: AuditScoreData }) {
  const correct = Math.round(data.accuracy * data.reviewed)
  return (
    <div
      className="border border-rule-soft bg-paper rounded-sm font-mono text-sm"
      data-testid="audit-score-card"
    >
      <div className="flex items-center gap-3 px-3 py-1.5">
        <span className="text-ink font-semibold">audit score</span>
        <span className="text-ink-2">
          accuracy {correct}/{data.reviewed}
        </span>
        <span className="text-ink-3 text-xs">P {(data.precision * 100).toFixed(0)}%</span>
        <span className="text-ink-3 text-xs">R {(data.recall * 100).toFixed(0)}%</span>
        {data.unclear > 0 && (
          <span className="text-ink-4 text-xs">unclear {data.unclear}</span>
        )}
      </div>
      {data.wrong.length > 0 && (
        <div className="border-t border-rule-soft">
          {data.wrong.map((w, i) => (
            <div key={i} className="px-3 py-1.5 flex items-start gap-2 border-b border-rule-soft last:border-b-0">
              <span className="text-rose shrink-0">✗</span>
              <span className="text-ink min-w-0 break-words">{w.rule}</span>
              <span className="ml-auto shrink-0 text-xs text-ink-3">
                judged {w.predicted} · truth {w.truth}
              </span>
            </div>
          ))}
        </div>
      )}
      {data.unreviewedRules.length > 0 && (
        <div className="px-3 py-1.5 border-t border-rule-soft text-xs text-ink-4">
          {data.unreviewedRules.length} rule(s) without confirmed truth
        </div>
      )}
    </div>
  )
}

// ── Adapter component (ToolCall wiring) ────────────────────────────────────

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

export function AuditCardAdapter({ call }: { call: ToolCallEvent }) {
  const status = call.ok === false ? 'err' : call.tool_result == null ? 'run' : 'done'
  const displayName = call.tool_name.replace(/^mcp__emerge_tools__/, '')
  const hint = status !== 'run' ? toolShortHint(call.tool_name, call.tool_result) : null

  if (status === 'done') {
    const report = adaptAuditReport(call.tool_result)
    if (report) {
      return (
        <>
          <ToolCall name={displayName} args={hint ?? undefined} status={status}>
            <ToolRow glyph="·" label="input" value={JSON.stringify(call.tool_input)} />
            <ToolRow glyph="↳" label="result" value={`overall=${report.overall}`} />
          </ToolCall>
          <AuditReportCard data={report} />
        </>
      )
    }
    const score = adaptAuditScore(call.tool_result)
    if (score) {
      return (
        <>
          <ToolCall name={displayName} args={hint ?? undefined} status={status}>
            <ToolRow glyph="·" label="input" value={JSON.stringify(call.tool_input)} />
            <ToolRow glyph="↳" label="result" value={`accuracy=${score.accuracy.toFixed(3)}`} />
          </ToolCall>
          {score.reviewed > 0 && <AuditScoreCard data={score} />}
        </>
      )
    }
  }

  // Fallback: regular ToolCall (running / error envelope / unrecognized JSON)
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
