// frontend/src/components/Spine/FSSpine.tsx
import { useEffect, useMemo, useState } from 'react'
import './spine.css'

import { useProjects } from '../../stores/projects'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'
import { useQuickLook } from '../../stores/quicklook'
import { usePrompts } from '../../stores/prompts'
import { useModels } from '../../stores/models'

// ── Tree node shapes ───────────────────────────────────────────────────────
type FileNode  = { kind: 'file';  name: string; stamp: string; active?: boolean; onClick?: () => void }
type GhostNode = { kind: 'ghost'; name: string }
type LeafNode  = FileNode | GhostNode
type DirGroup  = { name: string; count: number; items: LeafNode[] }
interface BuiltTree { groups: DirGroup[]; rootFiles: FileNode[] }

const STATUS_DOT: Record<string, string> = {
  live: 'var(--moss)',
  draft: 'var(--ochre)',
  empty: 'var(--ink-5)',
}

function buildTree(
  docs: import('../../types/review').DocSummary[],
  activeVersionId: string | null,
  promptItems: LeafNode[],
  modelItems: LeafNode[],
): BuiltTree {
  // ── docs/ ──────────────────────────────────────────────────────────────
  const docsItems: LeafNode[] = []
  const first5 = docs.slice(0, 5)
  for (const doc of first5) {
    let stamp: string
    if (doc.has_reviewed) stamp = 'reviewed'
    else if (doc.has_prediction) stamp = 'pending'
    else stamp = 'new'
    docsItems.push({ kind: 'file', name: doc.filename, stamp })
  }
  const remaining = docs.length - first5.length
  if (remaining > 0) docsItems.push({ kind: 'ghost', name: `… ${remaining} more` })

  // ── reviewed/ ──────────────────────────────────────────────────────────
  const reviewedDocs = docs.filter(d => d.has_reviewed)
  const reviewedItems: LeafNode[] = []
  const first5Reviewed = reviewedDocs.slice(0, 5)
  for (const doc of first5Reviewed) reviewedItems.push({ kind: 'file', name: doc.filename, stamp: '' })
  const remainingReviewed = reviewedDocs.length - first5Reviewed.length
  if (remainingReviewed > 0) reviewedItems.push({ kind: 'ghost', name: `… ${remainingReviewed} more` })
  else if (reviewedDocs.length === 0) reviewedItems.push({ kind: 'ghost', name: '(none yet)' })

  // ── versions/ ──────────────────────────────────────────────────────────
  const versionItems: LeafNode[] = activeVersionId
    ? [{ kind: 'file', name: activeVersionId, stamp: 'frozen' }]
    : [{ kind: 'ghost', name: '(no versions yet)' }]

  // ── trailing root files ────────────────────────────────────────────────
  const rootFiles: FileNode[] = [
    { kind: 'file', name: 'README.md', stamp: '' },
  ]

  return {
    groups: [
      { name: 'docs/', count: docs.length, items: docsItems },
      { name: 'reviewed/', count: reviewedDocs.length, items: reviewedItems },
      { name: 'prompts/', count: promptItems.filter(n => n.kind === 'file').length, items: promptItems },
      { name: 'models/', count: modelItems.filter(n => n.kind === 'file').length, items: modelItems },
      { name: 'versions/', count: activeVersionId ? 1 : 0, items: versionItems },
    ],
    rootFiles,
  }
}

export default function FSSpine() {
  const projects = useProjects(s => s.projects)
  const selectedId = useProjects(s => s.selectedId)

  const docsByProject = useDocs(s => s.byProject)
  const schemaByProject = useSchema(s => s.byProject)

  const promptListByProject = usePrompts(s => s.list)
  const modelListByProject = useModels(s => s.list)

  const openSchema = useQuickLook(s => s.openSchema)
  const openVersion = useQuickLook(s => s.openVersion)

  // Only docs/ open by default; prompts/ and models/ closed by default.
  const [openDirs, setOpenDirs] = useState<Record<string, boolean>>({ 'docs/': true })
  const toggleDir = (name: string) => setOpenDirs(s => ({ ...s, [name]: !s[name] }))

  // On mount: refresh project list
  useEffect(() => { void useProjects.getState().refresh() }, [])

  // When active project changes: load docs + schema + prompts + models
  useEffect(() => {
    if (!selectedId) return
    void useDocs.getState().refresh(selectedId)
    void useSchema.getState().load(selectedId)
    void usePrompts.getState().load(selectedId)
    void useModels.getState().load(selectedId)
  }, [selectedId])

  const activeDocs = selectedId ? (docsByProject[selectedId] ?? []) : []
  const activeSchemaFields = selectedId ? (schemaByProject[selectedId] ?? []) : []
  const activeProject = projects.find(p => p.project_id === selectedId) ?? null

  // Build prompts leaf nodes
  const promptItems: LeafNode[] = useMemo(() => {
    if (!selectedId) return [{ kind: 'ghost', name: '(none yet)' }]
    const rows = promptListByProject[selectedId]
    if (!rows || rows.length === 0) return [{ kind: 'ghost', name: '(none yet)' }]
    return rows.map(row => ({
      kind: 'file' as const,
      name: row.label,
      stamp: '',
      active: row.is_active,
      onClick: row.is_active ? () => openSchema(selectedId) : undefined,
    }))
  }, [selectedId, promptListByProject, openSchema])

  // Build models leaf nodes
  const modelItems: LeafNode[] = useMemo(() => {
    if (!selectedId) return [{ kind: 'ghost', name: '(none yet)' }]
    const rows = modelListByProject[selectedId]
    if (!rows || rows.length === 0) return [{ kind: 'ghost', name: '(none yet)' }]
    return rows.map(row => ({
      kind: 'file' as const,
      name: row.label,
      stamp: row.provider_model_id,
      active: row.is_active,
      onClick: undefined,
    }))
  }, [selectedId, modelListByProject])

  const tree = useMemo<BuiltTree | null>(
    () => activeProject
      ? buildTree(activeDocs, activeProject.active_version_id ?? null, promptItems, modelItems)
      : null,
    [activeProject, activeDocs, activeSchemaFields.length, promptItems, modelItems],
  )

  return (
    <div className="fs">
      {/* ── ~/projects header ─────────────────────────────────────────── */}
      <div className="fs-head">
        ~/projects <span className="small">{projects.length}</span>
      </div>

      {/* ── project rows ──────────────────────────────────────────────── */}
      {projects.length === 0 && (
        <div className="ghost" style={{ padding: '4px 16px' }}>no projects yet</div>
      )}
      {projects.map(p => {
        const isActive = p.project_id === selectedId
        return (
          <div
            key={p.project_id}
            className={'proj' + (isActive ? ' active' : '')}
            onClick={() => useProjects.getState().select(p.project_id)}
          >
            <span className="glyph">{isActive ? '▸' : '·'}</span>
            <span>{p.name}/</span>
            {isActive && (
              <span
                className="status-dot"
                title={p.status ?? 'empty'}
                style={{ background: STATUS_DOT[p.status ?? 'empty'] ?? 'var(--ink-5)' }}
              />
            )}
          </div>
        )
      })}

      {/* ── new project row ───────────────────────────────────────────── */}
      <div
        className="proj"
        onClick={() => useProjects.getState().select(null)}
        style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}
      >
        <span className="glyph">+</span>
        <span>new project…</span>
      </div>

      {/* ── active project tree ───────────────────────────────────────── */}
      {activeProject && tree && (
        <>
          <hr />
          <div className="fs-head">
            {activeProject.name}/ <span className="small">ls</span>
          </div>
          <div className="tree">
            {tree.groups.map(g => {
              const open = !!openDirs[g.name]
              return (
                <div key={g.name}>
                  <div className="branch dir" onClick={() => toggleDir(g.name)}>
                    <span className="arrow">{open ? '▾' : '▸'}</span>
                    <span>{g.name}</span>
                    <span className="stamp">{g.count}</span>
                  </div>
                  {open && g.items.map((n, j) => {
                    if (n.kind === 'ghost') return <div key={j} className="ghost">{n.name}</div>
                    const isVersion = g.name === 'versions/' && selectedId
                    const clickHandler = isVersion
                      ? () => openVersion(selectedId!, n.name)
                      : n.onClick
                    return (
                      <div
                        key={j}
                        className="branch file"
                        onClick={clickHandler}
                        role={clickHandler ? 'button' : undefined}
                        tabIndex={clickHandler ? 0 : undefined}
                        onKeyDown={clickHandler ? e => { if (e.key === 'Enter' || e.key === ' ') clickHandler() } : undefined}
                        style={clickHandler ? { cursor: 'pointer' } : undefined}
                      >
                        <span style={{ color: 'var(--ink-5)' }}>{n.active ? '⭐' : '·'}</span>
                        <span>{n.name}</span>
                        {n.stamp && <span className="stamp">{n.stamp}</span>}
                      </div>
                    )
                  })}
                </div>
              )
            })}
            {tree.rootFiles.map((n, k) => (
              <div
                key={'r' + k}
                className="branch file"
                style={{ paddingLeft: 18 }}
              >
                <span style={{ color: 'var(--ink-5)' }}>·</span>
                <span>{n.name}</span>
                {n.stamp && <span className="stamp">{n.stamp}</span>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
