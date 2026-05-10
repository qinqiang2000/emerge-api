// frontend/src/components/Spine/FSSpine.tsx
import { useEffect } from 'react'
import './spine.css'

import { useProjects } from '../../stores/projects'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'

// ── Tree node shape (mirrors data.jsx TREE array) ──────────────────────────
type TreeNode =
  | { kind: 'dir';   name: string; count: number }
  | { kind: 'file';  name: string; stamp: string }
  | { kind: 'ghost'; name: string }

function buildTree(
  _pid: string,
  docs: import('../../types/review').DocSummary[],
  activeVersionId: string | null,
  schemaFieldCount: number,
): TreeNode[] {
  const nodes: TreeNode[] = []

  // ── docs/ ──────────────────────────────────────────────────────────────
  const docsCount = docs.length
  nodes.push({ kind: 'dir', name: 'docs/', count: docsCount })
  const first5 = docs.slice(0, 5)
  for (const doc of first5) {
    let stamp: string
    if (doc.has_reviewed) {
      stamp = 'reviewed'
    } else if (doc.has_prediction) {
      stamp = 'pending'
    } else {
      stamp = 'new'
    }
    nodes.push({ kind: 'file', name: doc.filename, stamp })
  }
  const remaining = docsCount - first5.length
  if (remaining > 0) {
    nodes.push({ kind: 'ghost', name: `… ${remaining} more` })
  }

  // ── reviewed/ ──────────────────────────────────────────────────────────
  const reviewedDocs = docs.filter(d => d.has_reviewed)
  nodes.push({ kind: 'dir', name: 'reviewed/', count: reviewedDocs.length })
  const first5Reviewed = reviewedDocs.slice(0, 5)
  for (const doc of first5Reviewed) {
    nodes.push({ kind: 'file', name: doc.filename, stamp: '' })
  }
  const remainingReviewed = reviewedDocs.length - first5Reviewed.length
  if (remainingReviewed > 0) {
    nodes.push({ kind: 'ghost', name: `… ${remainingReviewed} more` })
  } else if (reviewedDocs.length === 0) {
    nodes.push({ kind: 'ghost', name: '(none yet)' })
  }

  // ── versions/ ──────────────────────────────────────────────────────────
  const versionsCount = activeVersionId ? 1 : 0
  nodes.push({ kind: 'dir', name: 'versions/', count: versionsCount })
  if (activeVersionId) {
    nodes.push({ kind: 'file', name: activeVersionId, stamp: 'frozen' })
  } else {
    nodes.push({ kind: 'ghost', name: '(no versions yet)' })
  }

  // ── schema.json ────────────────────────────────────────────────────────
  const fieldStamp = schemaFieldCount > 0 ? `${schemaFieldCount} fields` : ''
  nodes.push({ kind: 'file', name: 'schema.json', stamp: fieldStamp })

  // ── README.md ──────────────────────────────────────────────────────────
  nodes.push({ kind: 'file', name: 'README.md', stamp: '' })

  return nodes
}

export default function FSSpine() {
  const projects = useProjects(s => s.projects)
  const selectedId = useProjects(s => s.selectedId)

  const docsByProject = useDocs(s => s.byProject)
  const schemaByProject = useSchema(s => s.byProject)

  // On mount: refresh project list
  useEffect(() => {
    void useProjects.getState().refresh()
  }, [])

  // When active project changes: load docs + schema
  useEffect(() => {
    if (!selectedId) return
    void useDocs.getState().refresh(selectedId)
    void useSchema.getState().load(selectedId)
  }, [selectedId])

  const activeDocs = selectedId ? (docsByProject[selectedId] ?? []) : []
  const activeSchemaFields = selectedId ? (schemaByProject[selectedId] ?? []) : []
  const activeProject = projects.find(p => p.project_id === selectedId) ?? null

  const tree: TreeNode[] = activeProject
    ? buildTree(selectedId!, activeDocs, activeProject.active_version_id ?? null, activeSchemaFields.length)
    : []

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
        const docCount = docsByProject[p.project_id]?.length
        const meta = docCount !== undefined ? String(docCount) : '—'
        return (
          <div
            key={p.project_id}
            className={'proj' + (isActive ? ' active' : '')}
            onClick={() => useProjects.getState().select(p.project_id)}
          >
            <span className="glyph">{isActive ? '▸' : '·'}</span>
            <span>{p.name}/</span>
            <span className="meta">{meta}</span>
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
      {activeProject && (
        <>
          <hr />
          <div className="fs-head">
            {activeProject.name}/ <span className="small">ls</span>
          </div>
          <div className="tree">
            {tree.map((node, i) => {
              if (node.kind === 'dir') {
                return (
                  <div key={i} className="branch dir">
                    <span className="arrow">▾</span>
                    <span>{node.name}</span>
                    <span className="stamp">{node.count}</span>
                  </div>
                )
              }
              if (node.kind === 'ghost') {
                return (
                  <div key={i} className="ghost">{node.name}</div>
                )
              }
              // file
              return (
                <div key={i} className="branch file">
                  <span style={{ color: 'var(--ink-5)' }}>·</span>
                  <span>{node.name}</span>
                  {node.stamp && <span className="stamp">{node.stamp}</span>}
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
