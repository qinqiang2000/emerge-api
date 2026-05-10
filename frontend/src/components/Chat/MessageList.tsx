import type { ChatEvent } from '../../types/chat'
import { groupChatEvents } from '../../lib/groupChatEvents'
import { toolShortHint } from '../../lib/toolHint'
import KeyTrailCard from '../Publish/KeyTrailCard'

import AgentMessage from './AgentMessage'
import { EvalCardAdapter } from './EvalCard'
import JobProgressCard from './JobProgressCard'
import ProposalDiff from './ProposalDiff'
import ToolCall, { type ToolStatus } from './ToolCall'
import ToolRow from './ToolRow'
import Turn from './Turn'

interface Props { events: ChatEvent[]; busy?: boolean }

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

function toolStatus(e: ToolCallEvent): ToolStatus {
  if (e.ok === false) return 'err'
  if (e.tool_result === undefined || e.tool_result === null) return 'run'
  if (isProposalCandidate(e)) return 'cand'
  return 'done'
}

function isProposalCandidate(e: ToolCallEvent): boolean {
  if (!e.tool_name.endsWith('propose_description')) return false
  if (!e.ok || e.tool_result === null || e.tool_result === undefined) return false
  const r = parseResult(e.tool_result)
  return r !== null && typeof r.field === 'string' && typeof r.new_description === 'string'
}

function parseResult(result: unknown): Record<string, unknown> | null {
  if (typeof result === 'object' && result !== null) return result as Record<string, unknown>
  if (typeof result === 'string') {
    try {
      const p = JSON.parse(result)
      return typeof p === 'object' && p !== null ? p as Record<string, unknown> : null
    } catch {
      return null
    }
  }
  return null
}

function extractErrorCode(result: unknown): string | null {
  const r = parseResult(result)
  return typeof r?.error_code === 'string' ? r.error_code : null
}

function resultText(result: unknown): string {
  return typeof result === 'string' ? result : JSON.stringify(result, null, 2)
}

function ToolCallCard({ call }: { call: ToolCallEvent }) {
  // Special routing: start_job → JobProgressCard
  if (
    call.tool_name === 'mcp__emerge_tools__start_job' &&
    typeof call.tool_result === 'string' &&
    call.tool_result.startsWith('j_')
  ) {
    return <JobProgressCard jobId={call.tool_result} />
  }
  // Special routing: issue_api_key → KeyTrailCard
  if (call.tool_name === 'mcp__emerge_tools__issue_api_key') {
    return <KeyTrailCard event={call} />
  }
  // Special routing: score → EvalCardAdapter
  if (call.tool_name === 'mcp__emerge_tools__score') {
    return <EvalCardAdapter call={call} />
  }

  const status = toolStatus(call)
  const displayName = call.tool_name.replace(/^mcp__emerge_tools__/, '')
  const hint = status !== 'run' ? toolShortHint(call.tool_name, call.tool_result) : null
  const errorCode = status === 'err' ? extractErrorCode(call.tool_result) : null
  const argsStr = hint ?? (errorCode ? errorCode : undefined)

  // Candidate proposal: render ProposalDiff inside body
  if (status === 'cand') {
    const r = parseResult(call.tool_result)!
    return (
      <ToolCall name={displayName} args={argsStr} status="cand" defaultOpen>
        <ProposalDiff
          field={r.field as string}
          oldDesc={(r.old_description as string) ?? ''}
          newDesc={r.new_description as string}
        />
      </ToolCall>
    )
  }

  return (
    <ToolCall name={displayName} args={argsStr} status={status}>
      <ToolRow glyph="·" label="input" value={JSON.stringify(call.tool_input)} />
      {call.tool_result !== undefined && call.tool_result !== null && (
        <ToolRow glyph="↳" label="result" value={resultText(call.tool_result)} />
      )}
    </ToolCall>
  )
}

export default function MessageList({ events, busy }: Props) {
  const items = groupChatEvents(events)
  return (
    <div data-testid="message-list">
      {items.map((item, i) => {
        if (item.kind === 'user') {
          return (
            <Turn key={i} who="you" ts="just now">
              <div className="msg user">{item.text}</div>
            </Turn>
          )
        }
        if (item.kind === 'agent') {
          return (
            <Turn key={i} who="agent" ts="just now">
              <AgentMessage text={item.text} />
            </Turn>
          )
        }
        if (item.kind === 'tools') {
          return (
            <div key={i} className="pl-2 flex flex-col gap-2">
              {item.calls.map((call, j) => (
                <ToolCallCard key={j} call={call} />
              ))}
            </div>
          )
        }
        return (
          <div
            key={i}
            className="border-l-2 border-rose px-3 py-2 bg-paper-2 text-sm font-mono"
          >
            <span className="text-rose">{item.error_code}</span>
            <span className="text-ink-3">: {item.error_message_en}</span>
          </div>
        )
      })}
      {busy && (() => {
        const latest = [...events].reverse().find(e => e.type === 'tool_call') as
          | ToolCallEvent | undefined
        const running = latest
          && (latest.tool_result === undefined || latest.tool_result === null)
          && latest.ok !== false
        const name = running ? latest.tool_name.replace(/^mcp__emerge_tools__/, '') : null
        return (
          <div className="text-ink-4 italic flex items-center gap-2 px-1 mt-4" aria-live="polite">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-ink-4 animate-pulse"></span>
            {name ? `calling ${name}...` : 'agent is thinking...'}
          </div>
        )
      })()}
    </div>
  )
}
