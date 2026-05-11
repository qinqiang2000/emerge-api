import { Children, isValidElement, useState, type ReactElement, type ReactNode } from 'react'

import type { ToolStatus } from './ToolCall'

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
  const [open, setOpen] = useState(defaultOpen)
  const kids = Children.toArray(children).filter(isValidElement) as ReactElement<{ status?: ToolStatus }>[]
  const count = kids.length
  if (count === 0) return null

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
        <span>Ran</span>
        <span className="cnt">{count}</span>
        <span>{count === 1 ? 'tool' : 'tools'}</span>
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
