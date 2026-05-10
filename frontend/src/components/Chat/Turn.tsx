import type { ReactNode } from 'react'

type Props = { who: 'you' | 'agent'; ts: string; children: ReactNode }

export default function Turn({ who, ts, children }: Props) {
  const isAgent = who === 'agent'
  return (
    <div className="turn">
      <div className="turn-meta">
        <span className={`who ${isAgent ? 'agent' : ''}`}>{isAgent ? 'agent' : 'you'}</span>
        <span className="ts">{ts}</span>
        <span className="rule" />
      </div>
      {children}
    </div>
  )
}
