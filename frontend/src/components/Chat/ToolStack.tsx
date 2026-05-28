import { Children, isValidElement, useState, type ReactElement, type ReactNode } from 'react'

import type { ToolStatus } from './ToolCall'
import { useT } from '../../i18n'

interface Props {
  children: ReactNode
  defaultOpen?: boolean
}

const NODE_STATE: Record<ToolStatus, 'done' | 'run' | 'err'> = {
  done: 'done',
  run: 'run',
  err: 'err',
  cand: 'done',
}

export default function ToolStack({ children, defaultOpen = false }: Props) {
  const t = useT()
  const [open, setOpen] = useState(defaultOpen)
  const kids = Children.toArray(children).filter(isValidElement) as ReactElement<{ status?: ToolStatus }>[]
  const count = kids.length
  if (count === 0) return null

  // Derive per-stack progress so concurrent extract / label tool calls show
  // "X/N done" while in flight — no SSE plumbing needed, the running/done
  // split is already on each child's `status` prop. We only surface this
  // when there's at least one still running and the stack has >1 calls
  // (single-tool stacks already render their own status).
  const running = kids.filter(k => k.props.status === 'run').length
  const errored = kids.filter(k => k.props.status === 'err').length
  const done = count - running
  const showProgress = count > 1 && running > 0

  return (
    <div className={`tstack${open ? ' open' : ''}`} data-testid="tool-stack">
      <div
        className="ts-ran"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setOpen(o => !o) }}
      >
        <span>{t('tool.ran')}</span>
        <span className="cnt">{count}</span>
        <span>{count === 1 ? t('tool.tool') : t('tool.tools')}</span>
        {showProgress && (
          <span className="ts-progress" data-testid="ts-progress">
            · {done}/{count}
            {errored > 0 && <span className="ts-err"> · {errored} failed</span>}
          </span>
        )}
        <span className="chev">›</span>
      </div>
      <div className="ts-tree" aria-hidden={!open}>
        {kids.map((kid, i) => {
          const state = NODE_STATE[kid.props.status ?? 'done']
          return (
            <div key={i} className={`ts-node ${state}`}>
              <span className="ts-dot" aria-hidden="true">
                <svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="2.5,3.5 5,6 2.5,8.5" />
                  <line x1="6.5" y1="8.5" x2="9.5" y2="8.5" />
                </svg>
              </span>
              {kid}
            </div>
          )
        })}
      </div>
    </div>
  )
}
