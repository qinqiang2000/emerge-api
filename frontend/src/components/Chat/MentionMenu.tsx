// frontend/src/components/Chat/MentionMenu.tsx
//
// Mention dropdown for the chat composer. Two-tier:
//
//   1. **Projects** (top section, only at the token root — i.e. when the user
//      hasn't typed `/` yet). Source: in-memory project list. Selecting one
//      inserts `@<slug>` so the agent gets a verbatim folder-name handle.
//   2. **Tree entries** (always). Source: `/lab/projects/{slug}/tree?dir=…`
//      filtered by the trailing query segment. Files insert as
//      `@<full/path> `, dirs insert as `@<dir>/` (re-opens menu to keep
//      drilling).
//
// The active index runs over the **flattened** list (projects first, then
// tree entries) so arrow keys and Enter from the Composer act on a single
// 0-indexed cursor regardless of which section it lands in.
import { Folder, FileText, Box } from 'lucide-react'

import type { TreeEntry } from '../../lib/api'

/** Project pick item — just slug + display name. Restricted shape so we don't
 *  pull the whole `Project` type into the menu (which carries pid + status). */
export interface ProjectPick {
  slug: string
  name: string
}

export type MentionItem =
  | { kind: 'project'; project: ProjectPick }
  | { kind: 'entry'; entry: TreeEntry }

interface Props {
  /** Project matches; render in a top section. Empty array → section hidden. */
  projects: ProjectPick[]
  /** Tree entries for the active dir, already filtered by the query segment. */
  entries: TreeEntry[]
  /** 0-indexed cursor over the flattened list (projects first, then entries). */
  activeIdx: number
  dir: string
  loading: boolean
  /** When false (empty-hero state, no project selected), the tree-side
   *  affordances — breadcrumb + dir empty hint — are hidden; only the
   *  projects section is shown. */
  hasProject?: boolean
  emptyHint?: string
  /** Item-shaped pick. Lets the caller branch on project vs entry without
   *  re-doing the section split. */
  onPick: (item: MentionItem) => void
  onHover: (idx: number) => void
}

export default function MentionMenu({
  projects,
  entries,
  activeIdx,
  dir,
  loading,
  hasProject = true,
  emptyHint,
  onPick,
  onHover,
}: Props) {
  const crumb = dir ? `${dir}/` : '<root>'
  // The flat index lets us keep the visual sections (with optional labels)
  // while still computing one global active index.
  const items: MentionItem[] = [
    ...projects.map<MentionItem>(p => ({ kind: 'project', project: p })),
    ...entries.map<MentionItem>(e => ({ kind: 'entry', entry: e })),
  ]
  const totalCount = items.length
  return (
    <div className="mentionmenu">
      <div className="inner">
        {hasProject && <div className="crumb">{crumb}</div>}
        {loading ? (
          <div className="empty">loading…</div>
        ) : totalCount === 0 ? (
          <div className="empty">{emptyHint ?? 'empty'}</div>
        ) : (
          <>
            {projects.length > 0 && (
              <div className="section-label" aria-hidden>projects</div>
            )}
            {projects.map((p, i) => (
              <div
                key={`p:${p.slug}`}
                className={'item ' + (i === activeIdx ? 'active' : '')}
                onMouseEnter={() => onHover(i)}
                onMouseDown={(ev) => {
                  ev.preventDefault()
                  onPick({ kind: 'project', project: p })
                }}
              >
                <span className="ic">
                  <Box size={13} />
                </span>
                <span className="name">{p.name}</span>
                <span className="slug-hint" aria-hidden>{p.slug}</span>
                <span className="hint">{i === activeIdx ? '↵' : ''}</span>
              </div>
            ))}
            {projects.length > 0 && entries.length > 0 && (
              <div className="section-label" aria-hidden>{crumb}</div>
            )}
            {entries.map((e, i) => {
              const flatIdx = projects.length + i
              return (
                <div
                  key={`e:${e.path}`}
                  className={'item ' + (flatIdx === activeIdx ? 'active' : '')}
                  onMouseEnter={() => onHover(flatIdx)}
                  onMouseDown={(ev) => {
                    ev.preventDefault()
                    onPick({ kind: 'entry', entry: e })
                  }}
                >
                  <span className="ic">
                    {e.kind === 'dir' ? <Folder size={13} /> : <FileText size={13} />}
                  </span>
                  <span className="name">
                    {e.name}
                    {e.kind === 'dir' ? '/' : ''}
                  </span>
                  <span className="hint">{flatIdx === activeIdx ? '↵' : ''}</span>
                </div>
              )
            })}
          </>
        )}
      </div>
    </div>
  )
}
