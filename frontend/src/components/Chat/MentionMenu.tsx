// frontend/src/components/Chat/MentionMenu.tsx
import { Folder, FileText } from 'lucide-react'

import type { TreeEntry } from '../../lib/api'

interface Props {
  entries: TreeEntry[]
  activeIdx: number
  dir: string
  loading: boolean
  emptyHint?: string
  onPick: (entry: TreeEntry) => void
  onHover: (idx: number) => void
}

export default function MentionMenu({
  entries,
  activeIdx,
  dir,
  loading,
  emptyHint,
  onPick,
  onHover,
}: Props) {
  const crumb = dir ? `${dir}/` : '<root>'
  return (
    <div className="mentionmenu">
      <div className="inner">
        <div className="crumb">{crumb}</div>
        {loading ? (
          <div className="empty">loading…</div>
        ) : entries.length === 0 ? (
          <div className="empty">{emptyHint ?? 'empty'}</div>
        ) : (
          entries.map((e, i) => (
            <div
              key={e.path}
              className={'item ' + (i === activeIdx ? 'active' : '')}
              onMouseEnter={() => onHover(i)}
              onMouseDown={(ev) => {
                ev.preventDefault()
                onPick(e)
              }}
            >
              <span className="ic">
                {e.kind === 'dir' ? <Folder size={13} /> : <FileText size={13} />}
              </span>
              <span className="name">
                {e.name}
                {e.kind === 'dir' ? '/' : ''}
              </span>
              <span className="hint">{i === activeIdx ? '↵' : ''}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
