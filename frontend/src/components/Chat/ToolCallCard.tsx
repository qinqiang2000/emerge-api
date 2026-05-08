import { useState } from 'react'
import { Check, X, ChevronDown, ChevronRight } from 'lucide-react'

import type { ChatEvent } from '../../types/chat'

interface Props { event: Extract<ChatEvent, { type: 'tool_call' }> }

export default function ToolCallCard({ event }: Props) {
  const [open, setOpen] = useState(false)
  const Icon = event.ok ? Check : X
  return (
    <button
      onClick={() => setOpen(o => !o)}
      data-ok={event.ok}
      className={
        'block w-full text-left border-l-2 px-3 py-2 bg-surface text-sm font-mono transition-colors ' +
        (event.ok ? 'border-accent-info' : 'border-accent-danger')
      }
    >
      <div className="flex items-center gap-2">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Icon size={14} className={event.ok ? 'text-accent-success' : 'text-accent-danger'} />
        <span>{event.tool_name}</span>
      </div>
      {open && (
        <pre className="mt-2 text-xs whitespace-pre-wrap text-fg-secondary">
{`input:
${JSON.stringify(event.tool_input, null, 2)}

result:
${JSON.stringify(event.tool_result, null, 2)}`}
        </pre>
      )}
    </button>
  )
}
