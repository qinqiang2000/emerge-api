import type { ChatEvent } from '../../types/chat'
import KeyTrailCard from '../Publish/KeyTrailCard'

import JobProgressCard from './JobProgressCard'
import ToolCallPill from './ToolCallPill'

interface Props { calls: Extract<ChatEvent, { type: 'tool_call' }>[] }

function renderOne(call: Extract<ChatEvent, { type: 'tool_call' }>, key: number) {
  if (
    call.tool_name === 'mcp__emerge_tools__start_job' &&
    typeof call.tool_result === 'string' &&
    call.tool_result.startsWith('j_')
  ) {
    return <JobProgressCard key={key} jobId={call.tool_result} />
  }
  if (call.tool_name === 'mcp__emerge_tools__issue_api_key') {
    return <KeyTrailCard key={key} event={call} />
  }
  return <ToolCallPill key={key} event={call} />
}

export default function ToolCallGroup({ calls }: Props) {
  return (
    <div className="bg-canvas border border-subtle rounded p-1.5 space-y-1">
      {calls.map((c, i) => renderOne(c, i))}
    </div>
  )
}
