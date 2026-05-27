// frontend/src/components/Chat/MentionMenu.tsx
//
// Mention dropdown for the chat composer. The composer feeds it a single
// already-ordered, already-filtered `items` list so the menu and the keyboard
// handler share one flat index. Items carry their own kind; the menu draws a
// `section-label` at each group boundary:
//
//   - **projects** (root only) — in-memory project list; inserts `@<slug> `.
//   - **resources** (models, …) — pid-scoped registry sources (see
//     `mentionSources.ts`); insert `@<scope>/<id> `.
//   - **tree entries** — `/lab/projects/{slug}/tree?dir=…`; files insert
//     `@<path> `, dirs insert `@<path>/` (re-opens to keep drilling).
//
// Adding a new resource kind needs no change here — it just appears as more
// `resource` items with a new group label.
import { Fragment } from 'react'
import { Folder, FileText, Box } from 'lucide-react'

import type { TreeEntry } from '../../lib/api'
import type { MentionCandidate, ResourceSource } from './mentionSources'

/** Project pick item — just slug + display name. Restricted shape so we don't
 *  pull the whole `Project` type into the menu (which carries pid + status). */
export interface ProjectPick {
  slug: string
  name: string
}

export type MentionItem =
  | { kind: 'project'; project: ProjectPick }
  | { kind: 'entry'; entry: TreeEntry }
  | { kind: 'resource'; source: ResourceSource; cand: MentionCandidate }

interface Props {
  /** Ordered, filtered items. Projects first, then resource groups, then tree
   *  entries — the same order the composer's keyboard handler indexes into. */
  items: MentionItem[]
  /** 0-indexed cursor over `items`. */
  activeIdx: number
  dir: string
  loading: boolean
  /** When false (empty-hero state, no project selected), the tree-side
   *  affordances — breadcrumb + dir empty hint — are hidden. */
  hasProject?: boolean
  /** When true, render entries by their full `path` instead of just `name`
   *  (used when the root recursive picker surfaces nested matches). */
  flat?: boolean
  emptyHint?: string
  onPick: (item: MentionItem) => void
  onHover: (idx: number) => void
}

/** Stable React key for an item. */
function itemKey(it: MentionItem): string {
  switch (it.kind) {
    case 'project': return `p:${it.project.slug}`
    case 'resource': return `r:${it.source.kind}:${it.cand.key}`
    case 'entry': return `e:${it.entry.path}`
  }
}

/** Group header an item belongs under. Entries use the breadcrumb so the
 *  header reflects the current dir; projects/resources use a fixed label. */
function groupLabel(it: MentionItem, crumb: string): string {
  switch (it.kind) {
    case 'project': return 'projects'
    case 'resource': return it.source.label
    case 'entry': return crumb
  }
}

export default function MentionMenu({
  items,
  activeIdx,
  dir,
  loading,
  hasProject = true,
  flat = false,
  emptyHint,
  onPick,
  onHover,
}: Props) {
  const crumb = dir ? `${dir}/` : '<root>'
  return (
    <div className="mentionmenu">
      <div className="inner">
        {hasProject && <div className="crumb">{crumb}</div>}
        {loading ? (
          <div className="empty">loading…</div>
        ) : items.length === 0 ? (
          <div className="empty">{emptyHint ?? 'empty'}</div>
        ) : (
          items.map((it, i) => {
            const grp = groupLabel(it, crumb)
            const prevGrp = i > 0 ? groupLabel(items[i - 1], crumb) : null
            // Show a section label at each group boundary, except for a leading
            // file group — the top crumb already serves as its header, so a
            // `<root>`/`dir/` label there would just duplicate it.
            const showLabel = grp !== prevGrp && !(i === 0 && it.kind === 'entry')
            return (
              <Fragment key={itemKey(it)}>
                {showLabel && <div className="section-label" aria-hidden>{grp}</div>}
                <div
                  className={'item ' + (i === activeIdx ? 'active' : '')}
                  onMouseEnter={() => onHover(i)}
                  onMouseDown={(ev) => {
                    ev.preventDefault()
                    onPick(it)
                  }}
                >
                  <Row item={it} flat={flat} />
                  <span className="hint">{i === activeIdx ? '↵' : ''}</span>
                </div>
              </Fragment>
            )
          })
        )}
      </div>
    </div>
  )
}

/** Icon + label cell for one item, branched by kind. */
function Row({ item, flat }: { item: MentionItem; flat: boolean }) {
  if (item.kind === 'project') {
    return (
      <>
        <span className="ic"><Box size={13} /></span>
        <span className="name">{item.project.name}</span>
        <span className="slug-hint" aria-hidden>{item.project.slug}</span>
      </>
    )
  }
  if (item.kind === 'resource') {
    const Icon = item.source.icon
    return (
      <>
        <span className="ic"><Icon size={13} /></span>
        <span className="name">{item.cand.display}</span>
        {item.cand.sublabel && (
          <span className="slug-hint" aria-hidden>{item.cand.sublabel}</span>
        )}
      </>
    )
  }
  const e = item.entry
  return (
    <>
      <span className="ic">
        {e.kind === 'dir' ? <Folder size={13} /> : <FileText size={13} />}
      </span>
      <span className="name">
        {flat ? e.path : e.name}
        {e.kind === 'dir' ? '/' : ''}
      </span>
    </>
  )
}
