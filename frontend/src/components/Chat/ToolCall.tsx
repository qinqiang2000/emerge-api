import { useState, type ReactNode } from 'react'

export type ToolStatus = 'done' | 'run' | 'err' | 'cand'

interface Props {
  name: string
  args?: string
  status: ToolStatus
  durationMs?: number
  defaultOpen?: boolean
  footer?: ReactNode
  children?: ReactNode
}

function formatDuration(ms: number): string {
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.floor((ms % 60_000) / 1000)
  return `${m}m ${s}s`
}

const STATUS_LABEL: Record<ToolStatus, string> = {
  done: 'done',
  run: 'run',
  err: 'err',
  cand: 'cand',
}

export default function ToolCall({
  name,
  args,
  status,
  durationMs,
  defaultOpen = false,
  footer,
  children,
}: Props) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className={`tool${open ? ' open' : ''}`} data-status={status}>
      <div
        className="t-head"
        role="button"
        tabIndex={0}
        onClick={() => setOpen(o => !o)}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setOpen(o => !o) }}
      >
        <span className="t-arrow">{open ? '▾' : '▸'}</span>
        <span className="t-name">{name}</span>
        {args && <span className="t-args">({args})</span>}
        {status === 'run' && (
          <span className="t-status run" role="status" aria-label="running">
            <span className="inline-block animate-spin mr-1" style={{ display: 'inline-block' }}>↻</span>
            run
          </span>
        )}
        {status !== 'run' && (
          <span className={`t-status ${status}`}>{STATUS_LABEL[status]}</span>
        )}
        {durationMs !== undefined && (
          <span className="t-dur">{formatDuration(durationMs)}</span>
        )}
      </div>

      {status === 'run' && (
        <div className="t-bar indet"><i /></div>
      )}

      {open && (
        <>
          {children && <div className="t-body">{children}</div>}
          {footer && <div className="t-foot">{footer}</div>}
        </>
      )}
    </div>
  )
}
