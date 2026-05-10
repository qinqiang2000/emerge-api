// frontend/src/components/Improve/ProposalCandidateCard.tsx
//
// 🟡 Design-decisions note: accept is turn-level, not field-level.
// See docs/design-decisions.md for the 2026-05-10 entry.

import { useState } from 'react'

import type { ChatEvent } from '../../types/chat'
import { useJob } from '../../stores/jobs'
import ProposalDiff from '../Chat/ProposalDiff'
import ToolCall from '../Chat/ToolCall'

type ToolCallEvent = Extract<ChatEvent, { type: 'tool_call' }>

function parseResult(result: unknown): Record<string, unknown> | null {
  if (typeof result === 'object' && result !== null) return result as Record<string, unknown>
  if (typeof result === 'string') {
    try {
      const p = JSON.parse(result)
      return typeof p === 'object' && p !== null ? (p as Record<string, unknown>) : null
    } catch {
      return null
    }
  }
  return null
}

interface Props {
  event: ToolCallEvent
}

export default function ProposalCandidateCard({ event }: Props) {
  const [accepted, setAccepted] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  // Find a running (or most-recently-running) improve job for the accept callback.
  const byId = useJob(s => s.byId)
  const accept = useJob(s => s.accept)

  // Pick the running job with the highest jobId (lexicographic; j_<timestamp> is monotone).
  const runningEntry = Object.entries(byId)
    .filter(([, slice]) => slice.status === 'running')
    .sort(([a], [b]) => (a > b ? -1 : a < b ? 1 : 0))[0] ?? null

  const activeJob = runningEntry ? runningEntry[1] : null
  const bestTurn = activeJob?.bestTurn ?? null

  const canAccept = !accepted && activeJob !== null && bestTurn !== null

  async function handleAccept() {
    if (!canAccept || !activeJob || bestTurn === null) return
    await accept(activeJob.jobId, bestTurn.turn)
    setAccepted(true)
  }

  const r = parseResult(event.tool_result)!
  const field = r.field as string
  const oldDesc = (r.old_description as string) ?? ''
  const newDesc = r.new_description as string
  const displayName = event.tool_name.replace(/^mcp__emerge_tools__/, '')

  if (dismissed) return null

  const footer = (
    <>
      <button
        className={`t-btn primary${accepted ? '' : ''}`}
        onClick={() => { void handleAccept() }}
        disabled={!canAccept}
        title={
          !activeJob
            ? 'No running improve job'
            : !bestTurn
              ? 'Wait for at least one scored turn'
              : undefined
        }
      >
        {accepted ? 'accepted ✓' : 'accept'}
      </button>
      <button className="t-btn" disabled>
        edit
      </button>
      <button
        className="t-btn danger"
        onClick={() => setDismissed(true)}
      >
        dismiss
      </button>
    </>
  )

  return (
    <div data-improve-card={activeJob?.jobId ?? 'none'}>
      <ToolCall
        name={displayName}
        args={`field=${field}`}
        status="cand"
        defaultOpen
        footer={footer}
      >
        <ProposalDiff field={field} oldDesc={oldDesc} newDesc={newDesc} />
      </ToolCall>
    </div>
  )
}
