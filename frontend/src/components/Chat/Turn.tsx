import type { ReactNode } from 'react'

type Props = { who: 'you' | 'agent'; ts: string; children: ReactNode }

export default function Turn({ who, ts, children }: Props) {
  const isAgent = who === 'agent'
  return (
    <div className={`turn ${isAgent ? 'turn-agent' : 'turn-you'}`}>
      {/* a11y + 现有单元测试依赖该文本节点 */}
      <span className="sr-only">{isAgent ? 'agent' : 'you'} · {ts}</span>
      <span className={`who ${isAgent ? 'agent' : ''} sr-only`}>{isAgent ? 'agent' : 'you'}</span>
      {children}
    </div>
  )
}
