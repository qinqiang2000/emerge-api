import { useState } from 'react'
import { Check, ChevronDown, ChevronRight, Loader2, X } from 'lucide-react'

import { toolShortHint } from '../../lib/toolHint'
import type { ChatEvent } from '../../types/chat'

interface Props { event: Extract<ChatEvent, { type: 'tool_call' }> }

type PillState = 'running' | 'done' | 'error'

function pillState(e: Extract<ChatEvent, { type: 'tool_call' }>): PillState {
  if (e.ok === false) return 'error'
  if (e.tool_result === undefined || e.tool_result === null) return 'running'
  return 'done'
}

function extractErrorCode(result: unknown): string | null {
  if (typeof result === 'string') {
    try {
      const o = JSON.parse(result) as { error_code?: string }
      return o.error_code ?? null
    } catch {
      return null
    }
  }
  if (typeof result === 'object' && result !== null) {
    return (result as { error_code?: string }).error_code ?? null
  }
  return null
}

function resultText(result: unknown): string {
  return typeof result === 'string' ? result : JSON.stringify(result, null, 2)
}

export default function ToolCallPill({ event }: Props) {
  const [open, setOpen] = useState(false)
  const state = pillState(event)
  const displayName = event.tool_name.replace(/^mcp__emerge_tools__/, '')
  const hint = state === 'done' ? toolShortHint(event.tool_name, event.tool_result) : null
  const errorCode = state === 'error' ? extractErrorCode(event.tool_result) : null
  const Icon = state === 'running' ? Loader2 : state === 'error' ? X : Check
  const Caret = open ? ChevronDown : ChevronRight
  const iconClass =
    state === 'running' ? 'text-fg-muted animate-spin' :
    state === 'error' ? 'text-accent-danger' :
    'text-accent-success'

  return (
    <div
      data-state={state}
      className={
        'border-l-2 bg-surface text-sm transition-colors ' +
        (state === 'error' ? 'border-accent-danger' : 'border-accent-info')
      }
    >
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-1.5 font-mono text-left hover:bg-subtle"
      >
        <Caret size={12} className="text-fg-muted shrink-0" />
        <Icon size={14} className={`shrink-0 ${iconClass}`} />
        <span className="text-fg-primary">{displayName}</span>
        {hint && <span className="text-fg-muted">·</span>}
        {hint && <span className="text-fg-secondary">{hint}</span>}
        {errorCode && <span className="text-accent-danger">·</span>}
        {errorCode && <span className="text-accent-danger">{errorCode}</span>}
      </button>
      {open && (
        <div className="px-3 pb-2 pt-0.5 text-xs font-mono text-fg-secondary space-y-2">
          <div>
            <div className="text-fg-muted text-[10px] uppercase tracking-wide mb-0.5">input</div>
            <pre className="whitespace-pre-wrap">{JSON.stringify(event.tool_input, null, 2)}</pre>
          </div>
          {event.tool_result !== undefined && (
            <div>
              <div className="text-fg-muted text-[10px] uppercase tracking-wide mb-0.5">result</div>
              <pre className="whitespace-pre-wrap">{resultText(event.tool_result)}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
