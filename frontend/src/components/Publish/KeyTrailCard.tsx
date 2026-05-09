import { KeyRound } from 'lucide-react'

import type { ChatEvent } from '../../types/chat'

interface Props { event: Extract<ChatEvent, { type: 'tool_call' }> }

export default function KeyTrailCard({ event }: Props) {
  const result = event.tool_result as
    | { redacted: true; key_prefix: string; key_hash_short: string; created_at: string }
    | { redacted: true; error: string }
    | undefined

  if (!result || !('redacted' in result)) {
    return (
      <div className="border-l-2 border-accent-primary bg-surface px-3 py-1.5 font-mono text-sm flex items-center gap-2">
        <KeyRound size={14} className="text-accent-primary" />
        <span className="text-fg-muted">issuing api key...</span>
      </div>
    )
  }
  if ('error' in result) {
    return (
      <div className="border-l-2 border-accent-danger bg-surface px-3 py-1.5 font-mono text-sm flex items-center gap-2">
        <KeyRound size={14} className="text-accent-danger" />
        <span className="text-accent-danger">key issue failed:</span>
        <span className="text-fg-secondary">{result.error}</span>
      </div>
    )
  }
  return (
    <div className="border-l-2 border-accent-primary bg-surface px-3 py-1.5 font-mono text-sm flex items-center gap-2">
      <KeyRound size={14} className="text-accent-primary" />
      <span className="text-fg-primary">key issued</span>
      <span className="text-fg-muted">·</span>
      <span className="text-fg-primary">{result.key_prefix}</span>
      <span className="text-fg-muted">...hash {result.key_hash_short}</span>
      <span className="ml-auto text-fg-muted text-xs">{result.created_at}</span>
    </div>
  )
}
