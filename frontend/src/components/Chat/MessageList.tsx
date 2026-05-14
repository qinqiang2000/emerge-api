import { KeyRound } from 'lucide-react'

import type { ChatEvent } from '../../types/chat'
import { groupChatEvents } from '../../lib/groupChatEvents'
import { toolShortHint } from '../../lib/toolHint'
import PublishStage, { adaptReadiness } from '../Publish/PublishStage'
import { sampleCurl } from '../../lib/api'
import { useApiKey } from '../../stores/apiKey'
import { useChat } from '../../stores/chat'
import { useProjects } from '../../stores/projects'

import AgentMessage from './AgentMessage'
import { EvalCardAdapter } from './EvalCard'
import JobProgressCard from './JobProgressCard'
import ToolCall, { type ToolStatus } from './ToolCall'
import ToolRow from './ToolRow'
import ToolStack from './ToolStack'
import Turn from './Turn'
import UserMessage from './UserMessage'

interface Props { events: ChatEvent[]; busy?: boolean }

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

// Tool-input `project_id` field now carries a slug (slug-transparency rename).
// Match by either slug or the immutable internal pid as a fallback for older
// hydrated events that still reference `p_xxx` directly.
function useProjectName(slugOrPid: string): string {
  const projects = useProjects(s => s.projects)
  const byHandle = projects.find(p => p.slug === slugOrPid || p.project_id === slugOrPid)
  return byHandle?.name ?? slugOrPid
}

function useLatestPublishedId(slugOrPid: string): string | null {
  const projects = useProjects(s => s.projects)
  const byHandle = projects.find(p => p.slug === slugOrPid || p.project_id === slugOrPid)
  const ids = byHandle?.published_ids
  return ids && ids.length > 0 ? ids[ids.length - 1] : null
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
  const selectedSlug = useProjects(s => s.selectedSlug)

  const handleAdvance = () => {
    const slug = selectedSlug ?? projectId
    // Prefix /publish so ChatService._select_system_prompt re-loads the publish
    // skill on this turn — without it, the agent may refuse `issue_api_key`
    // because the default extractor skill is loaded (M7.2-era multi-turn
    // skill-loading workaround; see docs/design-decisions.md 2026-05-11).
    void send(slug, '/publish yes, mint the key now')
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

  // `issue_api_key` is now user-scoped — its tool_input may omit `project_id`
  // entirely. Fall back to the current selection / reveal payload so the card
  // still has a project name + published_id to surface in the curl example.
  const inputPid = typeof (event.tool_input as Record<string, unknown>)?.project_id === 'string'
    ? (event.tool_input as Record<string, unknown>).project_id as string
    : null
  const selectedSlug = useProjects(s => s.selectedSlug)
  const projectId = inputPid ?? current?.project_id ?? selectedSlug ?? 'project'
  const projectName = useProjectName(projectId)
  const latestPub = useLatestPublishedId(projectId)
  const pubForCurl = latestPub ?? 'pub_xxx'

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
        sampleSnippet={sampleCurl(pubForCurl)}
        publishedId={latestPub}
        onClose={clear}
      />
    )
  }

  // Reveal already closed — render redacted trail from tool_result
  const result = event.tool_result as
    | { redacted: true; key_prefix: string; key_hash_short: string; created_at: string }
    | { redacted: true; error: string }
    | undefined

  // `'redacted' in result` requires result to be a non-null object. A
  // string-shaped tool_result (e.g. an older hydrate path or unexpected
  // backend payload) would throw `Cannot use 'in' operator…` and crash the
  // whole conv tree — fall through to the "running / unknown" pill instead.
  if (!result || typeof result !== 'object' || !('redacted' in result)) {
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

// ─── HoistedToolCard ──────────────────────────────────────────────────────────
// Rich-card tools (score / readiness_check / issue_api_key / start_job) render
// outside the ToolStack collapse — their primary artifact (score numbers,
// readiness checklist, one-time key reveal, job progress) is the user's main
// focus and must stay immediately visible. Hoist routing happens at the
// grouping layer (lib/groupChatEvents.ts); this is the render-time dispatch.

function HoistedToolCard({ call }: { call: ToolCallEvent }) {
  if (
    call.tool_name === 'mcp__emerge_tools__start_job' &&
    typeof call.tool_result === 'string' &&
    call.tool_result.startsWith('j_')
  ) {
    return <JobProgressCard jobId={call.tool_result} />
  }
  if (call.tool_name === 'mcp__emerge_tools__readiness_check') {
    return <PublishStageCheckAdapter event={call} />
  }
  if (call.tool_name === 'mcp__emerge_tools__issue_api_key') {
    return <PublishStageKeyAdapter event={call} />
  }
  if (call.tool_name === 'mcp__emerge_tools__score') {
    return <EvalCardAdapter call={call} />
  }
  // Fallback (shouldn't trigger — HOISTED_TOOL_NAMES in groupChatEvents owns the list):
  return <PlumbingToolCard call={call} />
}

// ─── PlumbingToolCard ─────────────────────────────────────────────────────────
// Generic ToolCall renderer for non-hoisted tools. Wrapped in a ToolStack
// (collapsed `Ran N tools ›`) by MessageList.

function PlumbingToolCard({ call }: { call: ToolCallEvent }) {
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
  // Pre-pass: map each user-item position → its 0-indexed ordinal among user
  // items. UserMessage passes this back to rewindAndSend so retry/edit can
  // target any user bubble, not just the latest.
  const userOrdinals = new Map<number, number>()
  let userCount = 0
  for (let i = 0; i < items.length; i++) {
    if (items[i].kind === 'user') {
      userOrdinals.set(i, userCount)
      userCount++
    }
  }
  return (
    <div data-testid="message-list">
      {items.map((item, i) => {
        if (item.kind === 'user') {
          return (
            <Turn key={i} who="you" ts="just now">
              <UserMessage
                text={item.text}
                userIndex={userOrdinals.get(i) ?? 0}
                attachments={item.attachments}
              />
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
            <div key={i} className="pl-2">
              <ToolStack>
                {item.calls.map((call, j) => (
                  <PlumbingToolCard key={j} call={call} />
                ))}
              </ToolStack>
            </div>
          )
        }
        if (item.kind === 'hoisted_tool') {
          return (
            <div key={i} className="pl-2">
              <HoistedToolCard call={item.call} />
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
