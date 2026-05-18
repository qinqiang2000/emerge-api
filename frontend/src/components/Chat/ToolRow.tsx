import type { ReactNode } from 'react'

interface Props {
  glyph?: string
  label: ReactNode
  value?: ReactNode
  mini?: ReactNode
  nest?: 0 | 1 | 2
  wrap?: boolean
}

export default function ToolRow({ glyph = '·', label, value, mini, nest = 0, wrap = false }: Props) {
  const nestClass = nest === 1 ? ' nest' : nest === 2 ? ' nest2' : ''
  const wrapClass = wrap ? ' wrap' : ''
  return (
    <div className={`t-row${nestClass}${wrapClass}`}>
      <span className="glyph">{glyph}</span>
      <span className="label">{label}</span>
      {value !== undefined && <span className="v">{value}</span>}
      {mini !== undefined && <span className="mini">{mini}</span>}
    </div>
  )
}
