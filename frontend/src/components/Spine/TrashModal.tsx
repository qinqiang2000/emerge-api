// frontend/src/components/Spine/TrashModal.tsx
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  X, Undo2, Folder, FileText, ScrollText, Cpu, FlaskConical, Package, Gift,
  NotebookPen,
  type LucideIcon,
} from 'lucide-react'

import { useT } from '../../i18n'
import { ApiError } from '../../lib/api'
import { useTrash } from '../../stores/trash'
import { useProjects } from '../../stores/projects'
import { useDocs } from '../../stores/docs'
import { usePrompts } from '../../stores/prompts'
import { useModels } from '../../stores/models'
import { useExperiments } from '../../stores/experiments'
import { toast } from '../../stores/toast'
import './trash.css'

const KIND_ICON: Record<string, LucideIcon> = {
  project: Folder,
  doc: FileText,
  prompt: ScrollText,
  model: Cpu,
  experiment: FlaskConical,
  // Agent-built `_export/` deliverable, aged out by retention rather than
  // deleted by the user.
  deliverable: Gift,
  // A retired `_memory/` note — the agent superseded a fact it had written
  // down. Restoring one also needs its MEMORY.md line put back.
  memory: NotebookPen,
  item: Package,
}

/** Days left before the retention purge takes it for real. Rounded UP: the
 *  window is 14 days, and something deleted ten seconds ago has 13.99 left —
 *  flooring that would greet every fresh delete with "13d left" and make the
 *  panel's own "kept for 14 days" line read as a lie. */
function daysLeft(expiresAt: string): number {
  const ms = new Date(expiresAt).getTime() - Date.now()
  return Math.max(0, Math.ceil(ms / 86_400_000))
}

/**
 * The recycle bin. Every delete path in emerge moves data to `_trash/` and
 * tells the user it's recoverable for 14 days — this is where they act on
 * that. Deliberately a flat list with one verb (restore): the bin is a safety
 * net you visit rarely and want to leave quickly, not a file manager.
 *
 * Permanent deletion is NOT offered. Retention purge on startup is the only
 * path that physically destroys user data (see `workspace/trash.py`), and
 * putting a "delete forever" button next to an undo button in a panel people
 * open *because they made a mistake* invites the second mistake.
 */
export default function TrashModal() {
  const t = useT()
  const open = useTrash(s => s.open)
  const hide = useTrash(s => s.hide)
  const rows = useTrash(s => s.rows)
  const loading = useTrash(s => s.loading)
  const restore = useTrash(s => s.restore)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') hide() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, hide])

  if (!open) return null

  async function onRestore(entry: string, name: string) {
    setBusy(entry)
    try {
      await restore(entry)
      // Everything the restored thing could belong to — cheaper to refresh the
      // few small lists than to reason about which one it landed in.
      await useProjects.getState().refresh()
      const slug = useProjects.getState().selectedSlug
      if (slug) {
        void useDocs.getState().refresh(slug)
        usePrompts.getState().invalidate(slug); void usePrompts.getState().load(slug)
        useModels.getState().invalidate(slug); void useModels.getState().load(slug)
        useExperiments.getState().invalidate(slug); void useExperiments.getState().load(slug)
      }
      toast.ok(t('trash.restored', { name }))
    } catch (e) {
      const msg = e instanceof ApiError && e.message ? e.message : t('trash.restore.failed')
      toast.err(msg)
      void useTrash.getState().refresh()
    } finally {
      setBusy(null)
    }
  }

  return createPortal(
    <div className="trash-scrim" onMouseDown={hide}>
      <div className="trash-sheet" onMouseDown={e => e.stopPropagation()}>
        <header className="trash-head">
          <div>
            <div className="trash-title">{t('trash.title')}</div>
            <div className="trash-sub">{t('trash.retention')}</div>
          </div>
          <button type="button" className="trash-close" aria-label={t('trash.close')} onClick={hide}>
            <X size={16} strokeWidth={2} />
          </button>
        </header>

        <div className="trash-body">
          {loading && rows.length === 0 && <div className="trash-empty">{t('trash.loading')}</div>}
          {!loading && rows.length === 0 && <div className="trash-empty">{t('trash.empty')}</div>}
          {rows.map(r => {
            const Icon = KIND_ICON[r.kind] ?? Package
            const left = daysLeft(r.expires_at)
            return (
              <div key={r.entry} className={'trash-row' + (r.restorable ? '' : ' blocked')}>
                <Icon size={15} strokeWidth={1.75} className="trash-row-icon" />
                <div className="trash-row-main">
                  <div className="trash-row-name" title={r.name}>{r.name}</div>
                  <div className="trash-row-meta">
                    {t(`trash.kind.${r.kind}`)}
                    {r.project && ` · ${r.project}`}
                    {` · ${t('trash.expires', { n: left })}`}
                    {r.member_count > 1 && ` · ${t('trash.members', { n: r.member_count })}`}
                  </div>
                  {!r.restorable && (
                    <div className="trash-row-blocked">
                      {r.blocked_reason?.startsWith('origin_occupied:')
                        ? t('trash.blocked.occupied', { path: r.blocked_reason.slice('origin_occupied:'.length) })
                        : t('trash.blocked.legacy', { entry: r.entry })}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  className="trash-restore"
                  disabled={!r.restorable || busy === r.entry}
                  onClick={() => void onRestore(r.entry, r.name)}
                >
                  <Undo2 size={13} strokeWidth={2} />
                  {busy === r.entry ? t('trash.restoring') : t('trash.restore')}
                </button>
              </div>
            )
          })}
        </div>
      </div>
    </div>,
    document.body,
  )
}
