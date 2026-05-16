// frontend/src/components/Spine/FSSpine.tsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './spine.css'

import { useProjects } from '../../stores/projects'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'
import { useQuickLook } from '../../stores/quicklook'
import { useReview } from '../../stores/review'
import { usePrompts } from '../../stores/prompts'
import { useModels } from '../../stores/models'
import { useExperiments } from '../../stores/experiments'
import PanelToggle from '../Shell/PanelToggle'

// ── Tree node shapes ───────────────────────────────────────────────────────
type FileNode  = { kind: 'file';  name: string; stamp: string; active?: boolean; onClick?: () => void }
type GhostNode = { kind: 'ghost'; name: string }
type MoreNode  = { kind: 'more'; remaining: number; onClick: () => void }
type LeafNode  = FileNode | GhostNode | MoreNode
type DirGroup  = { name: string; count: number; items: LeafNode[] }
interface BuiltTree { groups: DirGroup[]; rootFiles: FileNode[] }

const DOCS_INITIAL = 5
const DOCS_PAGE = 20

const STATUS_DOT: Record<string, string> = {
  live: 'var(--moss)',
  draft: 'var(--ochre)',
  empty: 'var(--ink-5)',
}

function buildTree(
  slug: string,
  docs: import('../../types/review').DocSummary[],
  activeVersionId: string | null,
  promptItems: LeafNode[],
  modelItems: LeafNode[],
  experimentItems: LeafNode[],
  openDoc: (slug: string, filename: string) => void,
  docsVisible: number,
  onLoadMoreDocs: () => void,
): BuiltTree {
  // ── docs/ ──────────────────────────────────────────────────────────────
  // reviewed/ has been retired — the reviewed state is already shown as
  // a stamp on each docs/ row, so a separate group is pure duplication.
  const docsItems: LeafNode[] = []
  const visible = docs.slice(0, docsVisible)
  for (const doc of visible) {
    let stamp: string
    if (doc.has_reviewed) stamp = 'reviewed'
    else if (doc.has_prediction) stamp = 'pending'
    else stamp = 'new'
    docsItems.push({
      kind: 'file',
      name: doc.filename,
      stamp,
      onClick: () => openDoc(slug, doc.filename),
    })
  }
  const remaining = docs.length - visible.length
  if (remaining > 0) docsItems.push({ kind: 'more', remaining, onClick: onLoadMoreDocs })

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
      { name: 'prompts/', count: promptItems.filter(n => n.kind === 'file').length, items: promptItems },
      { name: 'models/', count: modelItems.filter(n => n.kind === 'file').length, items: modelItems },
      { name: 'experiments/', count: experimentItems.filter(n => n.kind === 'file').length, items: experimentItems },
      { name: 'versions/', count: activeVersionId ? 1 : 0, items: versionItems },
    ],
    rootFiles,
  }
}

type FSSpineProps = {
  onToggleLeft?: () => void
}

export default function FSSpine({ onToggleLeft }: FSSpineProps = {}) {
  const projects = useProjects(s => s.projects)
  const selectedSlug = useProjects(s => s.selectedSlug)

  const docsByProject = useDocs(s => s.byProject)
  const schemaByProject = useSchema(s => s.byProject)

  const promptListByProject = usePrompts(s => s.list)
  const modelListByProject = useModels(s => s.list)
  const experimentListByProject = useExperiments(s => s.list)

  const openSchema = useQuickLook(s => s.openSchema)
  const openVersion = useQuickLook(s => s.openVersion)
  const openPrompt = useQuickLook(s => s.openPrompt)
  const openReview = useReview(s => s.open)

  // Only docs/ open by default; prompts/ and models/ closed by default.
  const [openDirs, setOpenDirs] = useState<Record<string, boolean>>({ 'docs/': true })
  const toggleDir = (name: string) => setOpenDirs(s => ({ ...s, [name]: !s[name] }))

  // docs/ pagination: first DOCS_INITIAL shown; user clicks "… N more" to
  // load DOCS_PAGE more. Once the user has clicked at least once, an
  // IntersectionObserver on the same button auto-loads the next page when
  // it scrolls into view (lazy infinite scroll, gated on explicit intent).
  const [docsVisible, setDocsVisible] = useState(DOCS_INITIAL)
  const [docsAutoload, setDocsAutoload] = useState(false)
  const moreBtnRef = useRef<HTMLDivElement | null>(null)

  // Reset pagination when switching project
  useEffect(() => {
    setDocsVisible(DOCS_INITIAL)
    setDocsAutoload(false)
  }, [selectedSlug])

  const loadMoreDocs = useCallback(() => {
    setDocsVisible(v => v + DOCS_PAGE)
    setDocsAutoload(true)
  }, [])

  // On mount: refresh project list
  useEffect(() => { void useProjects.getState().refresh() }, [])

  // When active project changes: load docs + schema + prompts + models
  useEffect(() => {
    if (!selectedSlug) return
    void useDocs.getState().refresh(selectedSlug)
    void useSchema.getState().load(selectedSlug)
    void usePrompts.getState().load(selectedSlug)
    void useModels.getState().load(selectedSlug)
    void useExperiments.getState().load(selectedSlug)
  }, [selectedSlug])

  const activeDocs = selectedSlug ? (docsByProject[selectedSlug] ?? []) : []
  const activeSchemaFields = selectedSlug ? (schemaByProject[selectedSlug] ?? []) : []
  // Selection key is slug (folder name on disk); display label is `name`
  // (may contain spaces / unicode that the slug stripped or transcoded).
  const activeProject = projects.find(p => p.slug === selectedSlug) ?? null

  // Build prompts leaf nodes
  const promptItems: LeafNode[] = useMemo(() => {
    if (!selectedSlug) return [{ kind: 'ghost', name: '(none yet)' }]
    const rows = promptListByProject[selectedSlug]
    if (!rows || rows.length === 0) return [{ kind: 'ghost', name: '(none yet)' }]
    return rows.map(row => ({
      kind: 'file' as const,
      name: row.label,
      stamp: '',
      active: row.is_active,
      onClick: row.is_active
        ? () => openSchema(selectedSlug)
        : () => openPrompt(selectedSlug, row.prompt_id),
    }))
  }, [selectedSlug, promptListByProject, openSchema, openPrompt])

  // Build models leaf nodes
  const modelItems: LeafNode[] = useMemo(() => {
    if (!selectedSlug) return [{ kind: 'ghost', name: '(none yet)' }]
    const rows = modelListByProject[selectedSlug]
    if (!rows || rows.length === 0) return [{ kind: 'ghost', name: '(none yet)' }]
    return rows.map(row => ({
      kind: 'file' as const,
      name: row.provider_model_id,
      stamp: '',
      active: row.is_active,
      onClick: undefined,
    }))
  }, [selectedSlug, modelListByProject])

  // Build experiments leaf nodes
  const experimentItems: LeafNode[] = useMemo(() => {
    if (!selectedSlug) return [{ kind: 'ghost', name: '(none yet)' }]
    const rows = experimentListByProject[selectedSlug]
    if (!rows || rows.length === 0) return [{ kind: 'ghost', name: '(none yet)' }]
    return rows.map(row => ({
      kind: 'file' as const,
      name: row.label,
      stamp: row.score != null
        ? `${row.status} · ${row.score.toFixed(2)}`
        : row.status,
      active: false,
      onClick: undefined,
    }))
  }, [selectedSlug, experimentListByProject])

  const tree = useMemo<BuiltTree | null>(
    () => activeProject
      ? buildTree(
          activeProject.slug,
          activeDocs,
          activeProject.active_version_id ?? null,
          promptItems,
          modelItems,
          experimentItems,
          (slug, filename) => { void openReview(slug, filename) },
          docsVisible,
          loadMoreDocs,
        )
      : null,
    [activeProject, activeDocs, activeSchemaFields.length, promptItems, modelItems, experimentItems, openReview, docsVisible, loadMoreDocs],
  )

  // Auto-load more docs once user has clicked "more" at least once and
  // the button is scrolled into view. Re-arms whenever the button remounts
  // (after each page load) by keying observer on docsVisible.
  useEffect(() => {
    if (!docsAutoload) return
    const el = moreBtnRef.current
    if (!el) return
    const obs = new IntersectionObserver(entries => {
      for (const e of entries) {
        if (e.isIntersecting) {
          loadMoreDocs()
          break
        }
      }
    }, { root: null, threshold: 0.1 })
    obs.observe(el)
    return () => obs.disconnect()
  }, [docsAutoload, docsVisible, loadMoreDocs])

  return (
    <div className="fs">
      {/* ── brand + collapse toggle ───────────────────────────────────── */}
      <div className="fs-brand-row">
        <div className="fs-brand"><span className="dot"></span>emerge</div>
        {onToggleLeft && (
          <PanelToggle
            side="left"
            hidden={false}
            onClick={onToggleLeft}
            className="fs-toggle"
          />
        )}
      </div>

      {/* ── ~/projects header ─────────────────────────────────────────── */}
      <div className="fs-head">
        ~/projects <span className="small">{projects.length}</span>
      </div>

      {/* ── project rows ──────────────────────────────────────────────── */}
      {projects.length === 0 && (
        <div className="ghost" style={{ padding: '4px 16px' }}>no projects yet</div>
      )}
      {projects.map(p => {
        // React `key` and selection state are keyed on slug (the disk-truth
        // identifier). The visible label is the user-given `name`, which can
        // diverge from slug after rename / when name has chars slug stripped.
        const isActive = p.slug === selectedSlug
        return (
          <div
            key={p.slug}
            className={'proj' + (isActive ? ' active' : '')}
            onClick={() => useProjects.getState().select(p.slug)}
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
                    if (n.kind === 'more') {
                      return (
                        <div
                          key={j}
                          ref={g.name === 'docs/' ? moreBtnRef : undefined}
                          className="branch more"
                          onClick={n.onClick}
                          role="button"
                          tabIndex={0}
                          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); n.onClick() } }}
                        >
                          <span style={{ color: 'var(--ink-5)' }}>…</span>
                          <span>{n.remaining} more</span>
                        </div>
                      )
                    }
                    const isVersion = g.name === 'versions/' && selectedSlug
                    const clickHandler = isVersion
                      ? () => openVersion(selectedSlug!, n.name)
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
