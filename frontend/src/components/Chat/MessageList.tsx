import { KeyRound } from 'lucide-react'

import type { ChatEvent } from '../../types/chat'
import { groupChatEvents } from '../../lib/groupChatEvents'
import { toolShortHint } from '../../lib/toolHint'
import PublishStage, { adaptReadiness, sampleCurl } from '../Publish/PublishStage'
import { useApiKey } from '../../stores/apiKey'
import { useChat } from '../../stores/chat'
import { useProjects } from '../../stores/projects'

import AgentMessage from './AgentMessage'
import { EvalCardAdapter } from './EvalCard'
import JobProgressCard from './JobProgressCard'
import ToolCall, { type ToolStatus } from './ToolCall'
import ToolRow from './ToolRow'
import Turn from './Turn'

interface Props { events: ChatEvent[]; busy?: boolean }

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

function useProjectName(projectId: string): string {
  const projects = useProjects(s => s.projects)
  return projects.find(p => p.project_id === projectId)?.name ?? projectId
}

function toolStatus(e: ToolCallEvent): ToolStatus {
  if (e.ok === false) return 'err'
  if (e.tool_result === undefined || e.tool_result === null) return 'run'
  return 'done'
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

// ─── Publish adapters ─────────────────────────────────────────────────────────

function PublishStageCheckAdapter({ event }: { event: ToolCallEvent }) {
  const checklist = adaptReadiness(event.tool_result) ?? []
  const projectId = typeof (event.tool_input as Record<string, unknown>)?.project_id === 'string'
    ? (event.tool_input as Record<string, unknown>).project_id as string
    : 'project'
  const projectName = useProjectName(projectId)

  const send = useChat(s => s.send)
  const selectedId = useProjects(s => s.selectedId)

  const handleAdvance = () => {
    const pid = selectedId ?? projectId
    void send(pid, 'yes, mint the key now')
  }

  const handleClose = () => {
    // No-op for inline card: chat history keeps the readiness record.
    // (Overlay would unmount; inline we just leave it in the thread.)
  }

  // If tool_result not yet set, show running state
  if (event.tool_result === undefined || event.tool_result === null) {
    return (
      <div className="border-l-2 border-ochre bg-paper px-3 py-1.5 font-mono text-sm flex items-center gap-2">
        <span className="text-ink-4">running readiness check...</span>
      </div>
    )
  }

  return (
    <PublishStage
      stage="check"
      projectName={projectName}
      checklist={checklist}
      onAdvance={handleAdvance}
      onClose={handleClose}
    />
  )
}

function PublishStageKeyAdapter({ event }: { event: ToolCallEvent }) {
  const { current, clear } = useApiKey()

  const projectId = typeof (event.tool_input as Record<string, unknown>)?.project_id === 'string'
    ? (event.tool_input as Record<string, unknown>).project_id as string
    : 'project'
  const projectName = useProjectName(projectId)

  // One-time reveal available — show full key stage
  if (current && current.project_id === projectId) {
    return (
      <PublishStage
        stage="key"
        projectName={projectName}
        versionLabel={current.version_id ?? 'v1'}
        keyPlaintext={current.key_plaintext}
        keyHash={current.key_hash}
        keyPrefix={current.key_prefix}
        createdAt={current.created_at}
        sampleSnippet={sampleCurl(current.project_id)}
        onClose={clear}
      />
    )
  }

  // Reveal already closed — render redacted trail from tool_result
  const result = event.tool_result as
    | { redacted: true; key_prefix: string; key_hash_short: string; created_at: string }
    | { redacted: true; error: string }
    | undefined

  if (!result || !('redacted' in result)) {
    // Still running
    return (
      <div className="border-l-2 border-ochre bg-paper px-3 py-1.5 font-mono text-sm flex items-center gap-2">
        <KeyRound size={14} className="text-ochre-2" />
        <span className="text-ink-4">issuing api key...</span>
      </div>
    )
  }
  if ('error' in result) {
    return (
      <div className="border-l-2 border-rose bg-paper px-3 py-1.5 font-mono text-sm flex items-center gap-2">
        <KeyRound size={14} className="text-rose" />
        <span className="text-rose">key issue failed:</span>
        <span className="text-ink-3">{result.error}</span>
      </div>
    )
  }
  return (
    <div className="border-l-2 border-ochre bg-paper px-3 py-1.5 font-mono text-sm flex items-center gap-2">
      <KeyRound size={14} className="text-ochre-2" />
      <span className="text-ink">key issued</span>
      <span className="text-ink-4">·</span>
      <span className="text-ink">{result.key_prefix}</span>
      <span className="text-ink-4">...hash {result.key_hash_short}</span>
      <span className="ml-auto text-ink-4 text-xs">{result.created_at}</span>
    </div>
  )
}

// ─── ToolCallCard ─────────────────────────────────────────────────────────────

function ToolCallCard({ call }: { call: ToolCallEvent }) {
  // Special routing: start_job → JobProgressCard
  if (
    call.tool_name === 'mcp__emerge_tools__start_job' &&
    typeof call.tool_result === 'string' &&
    call.tool_result.startsWith('j_')
  ) {
    return <JobProgressCard jobId={call.tool_result} />
  }
  // Special routing: readiness_check → PublishStage check view
  if (call.tool_name === 'mcp__emerge_tools__readiness_check') {
    return <PublishStageCheckAdapter event={call} />
  }
  // Special routing: issue_api_key → PublishStage key view (or redacted trail)
  if (call.tool_name === 'mcp__emerge_tools__issue_api_key') {
    return <PublishStageKeyAdapter event={call} />
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
