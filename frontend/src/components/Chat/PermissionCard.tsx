import { Check, ShieldAlert, X } from 'lucide-react'

import { useChat } from '../../stores/chat'
import { useT } from '../../i18n'
import type { PermissionRequestEvent } from '../../types/chat'

interface Props {
  event: PermissionRequestEvent
}

/** Structured shape we render for AskUserQuestion. Mirrors the Claude Code
 *  AskUserQuestion contract: 1-4 questions, each with header (≤12 char chip),
 *  question text, 2-4 options of {label, description}. */
interface AskUserQuestion {
  question: string
  header?: string
  multiSelect?: boolean
  options: { label: string; description?: string }[]
}

/** Try to parse AskUserQuestion input. Returns null if shape doesn't match,
 *  so the caller can fall back to the generic JSON dump. */
function parseAskUserQuestion(input: unknown): AskUserQuestion[] | null {
  if (!input || typeof input !== 'object') return null
  const qs = (input as Record<string, unknown>).questions
  if (!Array.isArray(qs) || qs.length === 0) return null
  const out: AskUserQuestion[] = []
  for (const q of qs) {
    if (!q || typeof q !== 'object') return null
    const r = q as Record<string, unknown>
    const question = typeof r.question === 'string' ? r.question : null
    const options = Array.isArray(r.options) ? r.options : null
    if (!question || !options) return null
    const opts: AskUserQuestion['options'] = []
    for (const o of options) {
      if (!o || typeof o !== 'object') return null
      const label = typeof (o as Record<string, unknown>).label === 'string'
        ? (o as Record<string, string>).label : null
      if (!label) return null
      const desc = typeof (o as Record<string, unknown>).description === 'string'
        ? (o as Record<string, string>).description : undefined
      opts.push({ label, description: desc })
    }
    out.push({
      question,
      header: typeof r.header === 'string' ? r.header : undefined,
      multiSelect: typeof r.multiSelect === 'boolean' ? r.multiSelect : undefined,
      options: opts,
    })
  }
  return out
}

/** Pull out the one or two input fields that meaningfully identify *what* the
 *  agent is about to do, so the user sees `Bash · curl https://…` rather than
 *  a JSON blob. We surface a single key per tool family; for unknown tools we
 *  fall through to a JSON.stringify trimmed to ~140 chars.
 *
 *  Returns `null` for AskUserQuestion — that one gets a dedicated structured
 *  renderer below, since a flat string can't show options + descriptions. */
function summarizeInput(toolName: string, input: unknown): string | null {
  if (!input || typeof input !== 'object') return null
  if (toolName === 'AskUserQuestion') return null
  const o = input as Record<string, unknown>
  // Bash family — the command is the whole point.
  if (toolName === 'Bash' || toolName === 'BashOutput' || toolName === 'KillBash') {
    const cmd = typeof o.command === 'string' ? o.command : null
    return cmd
  }
  // Filesystem tools — the path is the point.
  if (
    toolName === 'Read' || toolName === 'Write' || toolName === 'Edit' ||
    toolName === 'MultiEdit' || toolName === 'NotebookEdit'
  ) {
    const p = (typeof o.file_path === 'string' && o.file_path) ||
              (typeof o.path === 'string' && o.path) ||
              (typeof o.notebook_path === 'string' && o.notebook_path) ||
              null
    return p
  }
  if (toolName === 'Glob' || toolName === 'Grep') {
    const pattern = typeof o.pattern === 'string' ? o.pattern : null
    const path = typeof o.path === 'string' ? o.path : null
    if (pattern && path) return `${pattern}  @  ${path}`
    return pattern ?? path
  }
  if (toolName === 'WebFetch' || toolName === 'WebSearch') {
    return (typeof o.url === 'string' && o.url) ||
           (typeof o.query === 'string' && o.query) ||
           null
  }
  // Unknown tool — best-effort JSON dump, capped.
  try {
    const s = JSON.stringify(input)
    return s.length > 140 ? s.slice(0, 137) + '…' : s
  } catch {
    return null
  }
}

export default function PermissionCard({ event }: Props) {
  const t = useT()
  const resolvePermission = useChat(s => s.resolvePermission)
  const resolved = event.resolution
  const summary = summarizeInput(event.tool_name, event.tool_input)
  const askQuestions = event.tool_name === 'AskUserQuestion'
    ? parseAskUserQuestion(event.tool_input)
    : null

  const onApprove = () => { void resolvePermission(event.request_id, 'approve', 'once') }
  const onAlways  = () => { void resolvePermission(event.request_id, 'approve', 'always') }
  const onDeny    = () => { void resolvePermission(event.request_id, 'deny', 'once') }

  // Resolved trail — keep the card visible so chat history reads naturally,
  // but render the decision instead of the buttons.
  if (resolved) {
    const isApproved = resolved.decision === 'approve'
    const label = isApproved
      ? (resolved.scope === 'always' ? t('perm.resolved.approvedAlways') : t('perm.resolved.approved'))
      : t('perm.resolved.denied')
    const accent = isApproved ? 'text-moss' : 'text-rose'
    return (
      <div
        className="border-l-2 border-rule-soft bg-paper-2 px-3 py-2 font-mono text-sm flex items-center gap-2"
        data-testid="permission-card-resolved"
      >
        {isApproved
          ? <Check size={14} className="text-moss" />
          : <X size={14} className="text-rose" />}
        <span className="text-ink-3">{t('perm.resolved.label')}</span>
        <span className="text-ink-4">·</span>
        <span className="text-ink">{event.tool_name}</span>
        {summary && (
          <span className="text-ink-4 truncate min-w-0">— {summary}</span>
        )}
        <span className={`ml-auto ${accent}`}>{label}</span>
      </div>
    )
  }

  // Pending — modeled on Claude Code's permission prompt: tool name + key
  // input + reason + three actions. The whole card uses warm `ochre` accents
  // so it visually pops out of the surrounding plumbing-tool stack and the
  // user notices the agent is blocked on them.
  return (
    <div
      className="border border-ochre-edge bg-ochre-soft rounded-lg px-3 py-3 flex flex-col gap-2"
      role="dialog"
      aria-label={t('perm.aria')}
      data-testid="permission-card"
    >
      <div className="flex items-baseline gap-2">
        <ShieldAlert size={14} className="text-ochre-2 self-center" />
        <span className="font-mono text-xs uppercase tracking-wider text-ochre-2">
          {t('perm.needed')}
        </span>
        <span className="font-mono text-sm text-ink ml-2 truncate min-w-0">
          {event.tool_name}
        </span>
      </div>

      {askQuestions && (
        <div
          className="flex flex-col gap-3 bg-paper rounded px-3 py-2.5"
          data-testid="permission-card-ask-question"
        >
          {askQuestions.map((q, i) => (
            <div key={i} className="flex flex-col gap-2">
              <div className="flex items-baseline gap-2 flex-wrap">
                {q.header && (
                  <span className="font-mono text-[10.5px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-ochre-soft text-ochre-2 border border-ochre-edge">
                    {q.header}
                  </span>
                )}
                <span className="font-sans text-[13.5px] text-ink leading-snug">
                  {q.question}
                </span>
                {q.multiSelect && (
                  <span className="font-mono text-[10.5px] text-ink-4">{t('ask.multiSelectHint')}</span>
                )}
              </div>
              <ul className="flex flex-col gap-1.5 pl-1">
                {q.options.map((opt, j) => (
                  <li key={j} className="flex flex-col gap-0.5 border-l-2 border-rule-soft pl-2">
                    <span className="font-sans text-[13px] text-ink-2">
                      <span className="text-ink-4 mr-1.5">{j + 1}.</span>{opt.label}
                    </span>
                    {opt.description && (
                      <span className="font-sans text-[12px] text-ink-3 leading-snug">
                        {opt.description}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {summary && (
        <div
          className="font-mono text-[12.5px] text-ink-2 bg-paper rounded px-2 py-1.5 break-all"
          data-testid="permission-card-summary"
        >
          {summary}
        </div>
      )}

      {event.reason && (
        <div className="font-sans text-[13px] text-ink-3 italic">
          {event.reason}
        </div>
      )}

      <div className="flex gap-2 mt-1">
        <button
          type="button"
          onClick={onApprove}
          className="font-mono text-xs px-3 py-1.5 rounded border border-ochre bg-paper text-ochre-2 hover:bg-ochre-soft transition-colors"
        >
          {t('perm.approve')}
        </button>
        <button
          type="button"
          onClick={onAlways}
          className="font-mono text-xs px-3 py-1.5 rounded border border-rule bg-paper text-ink-2 hover:bg-paper-2 transition-colors"
          title={t('perm.alwaysHint')}
        >
          {t('perm.always')}
        </button>
        <button
          type="button"
          onClick={onDeny}
          className="font-mono text-xs px-3 py-1.5 rounded border border-rule bg-paper text-ink-3 hover:bg-paper-2 transition-colors ml-auto"
        >
          {t('perm.deny')}
        </button>
      </div>
    </div>
  )
}
