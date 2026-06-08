// frontend/src/components/Spine/FSSpine.tsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './spine.css'
import kdfpyIcon from '../../assets/kdfpy-icon.png'

import { useI18n, useT } from '../../i18n'
import { navigateToReview, pathForBench } from '../../lib/slugUrl'
import { useProjects } from '../../stores/projects'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'
import { useQuickLook } from '../../stores/quicklook'
import { useReview } from '../../stores/review'
import { usePrompts } from '../../stores/prompts'
import { useModels } from '../../stores/models'
import { useExperiments } from '../../stores/experiments'
import { useEval } from '../../stores/eval'
import { pathForEvalMatrix } from '../../lib/slugUrl'
import PanelToggle from '../Shell/PanelToggle'
import UserMenu from '../Shell/UserMenu'
import {
  Folder, FolderOpen, FolderPlus, FileText, ScrollText, Cpu,
  FlaskConical, Gauge, Tag, Star, ChevronRight, ChevronDown, MoreHorizontal,
  Search, X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

// ── Tree node shapes ───────────────────────────────────────────────────────
type FileNode  = { kind: 'file';  name: string; stamp: string; active?: boolean; selected?: boolean; onClick?: () => void }
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

// Per-group leaf icon — the tree row's type at a glance, claude.ai-style.
// Active rows override this with a filled Star (see leaf render below).
const GROUP_ICON: Record<string, LucideIcon> = {
  'docs/': FileText,
  'prompts/': ScrollText,
  'models/': Cpu,
  'experiments/': FlaskConical,
  'metrics/': Gauge,
  'versions/': Tag,
}

type StampLabels = {
  new: string
  pending: string
  reviewed: string
  frozen: string
}

function buildTree(
  slug: string,
  docs: import('../../types/review').DocSummary[],
  activeVersionId: string | null,
  promptItems: LeafNode[],
  modelItems: LeafNode[],
  experimentItems: LeafNode[],
  metricsItems: LeafNode[],
  openDoc: (slug: string, filename: string) => void,
  docsVisible: number,
  onLoadMoreDocs: () => void,
  selectedDocFilename: string | null,
  versionsEmptyLabel: string,
  stampLabels: StampLabels,
): BuiltTree {
  // ── docs/ ──────────────────────────────────────────────────────────────
  // reviewed/ has been retired — the reviewed state is already shown as
  // a stamp on each docs/ row, so a separate group is pure duplication.
  const docsItems: LeafNode[] = []
  const visible = docs.slice(0, docsVisible)
  for (const doc of visible) {
    let stamp: string
    if (doc.has_reviewed) stamp = stampLabels.reviewed
    else if (doc.has_prediction) stamp = stampLabels.pending
    else stamp = stampLabels.new
    docsItems.push({
      kind: 'file',
      name: doc.filename,
      stamp,
      selected: doc.filename === selectedDocFilename,
      onClick: () => openDoc(slug, doc.filename),
    })
  }
  const remaining = docs.length - visible.length
  if (remaining > 0) docsItems.push({ kind: 'more', remaining, onClick: onLoadMoreDocs })

  // ── versions/ ──────────────────────────────────────────────────────────
  const versionItems: LeafNode[] = activeVersionId
    ? [{ kind: 'file', name: activeVersionId, stamp: stampLabels.frozen }]
    : [{ kind: 'ghost', name: versionsEmptyLabel }]

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
      { name: 'metrics/', count: metricsItems.filter(n => n.kind === 'file').length, items: metricsItems },
      { name: 'versions/', count: activeVersionId ? 1 : 0, items: versionItems },
    ],
    rootFiles,
  }
}

type FSSpineProps = {
  onToggleLeft?: () => void
}

export default function FSSpine({ onToggleLeft }: FSSpineProps = {}) {
  const t = useT()
  const locale = useI18n(s => s.locale)
  const projects = useProjects(s => s.projects)
  const selectedSlug = useProjects(s => s.selectedSlug)

  const docsByProject = useDocs(s => s.byProject)
  const schemaByProject = useSchema(s => s.byProject)

  const promptListByProject = usePrompts(s => s.list)
  const modelListByProject = useModels(s => s.list)
  const experimentListByProject = useExperiments(s => s.list)

  const openVersion = useQuickLook(s => s.openVersion)
  const openPrompt = useQuickLook(s => s.openPrompt)
  // Spine doc clicks navigate via the URL — App.tsx then drives
  // `useReview.open()` from the URL change. Keeps a single source of truth
  // for "am I in review" so browser back / "← back" both work uniformly.
  // Selection marker for the docs/ list: only when review mode is open on
  // this project. The doc id is the on-disk filename — same handle the
  // ReviewBar prev/next arrows drive — so → / ← in review keep the spine
  // row in sync.
  const reviewActiveFilename = useReview(s => s.activeFilename)
  const reviewActiveProjectId = useReview(s => s.activeProjectId)
  const selectedDocFilename =
    reviewActiveProjectId && reviewActiveProjectId === selectedSlug
      ? reviewActiveFilename
      : null

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

  // Project filter — only surfaces once the list is long enough to need it.
  // Pure client-side name match; never touches selection.
  const [filter, setFilter] = useState('')
  const [filterFocused, setFilterFocused] = useState(false)
  const filterInputRef = useRef<HTMLInputElement | null>(null)
  const selectedProjRef = useRef<HTMLDivElement | null>(null)

  // Per-project tree expansion. Default collapsed: nothing here until the user
  // explicitly opens a project, so landing via URL shows a tidy list, not a
  // 369-doc tree shoving everything down. Selecting an unopened project opens
  // it; clicking the already-open active project collapses it again.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

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
    void useEval.getState().loadList(selectedSlug)
  }, [selectedSlug])

  const evalListByProject = useEval(s => s.list)

  const activeDocs = selectedSlug ? (docsByProject[selectedSlug] ?? []) : []
  const activeSchemaFields = selectedSlug ? (schemaByProject[selectedSlug] ?? []) : []
  // Selection key is slug (folder name on disk); display label is `name`
  // (may contain spaces / unicode that the slug stripped or transcoded).
  const activeProject = projects.find(p => p.slug === selectedSlug) ?? null

  // Filter is opt-in: show the input only when the list is long enough to
  // warrant it. Match on the human `name`; the selected project always stays
  // visible so its inline tree never vanishes mid-interaction.
  const FILTER_THRESHOLD = 8
  const showFilter = projects.length > FILTER_THRESHOLD || filterFocused

  const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
  const filterPlaceholder = t('spine.filter.placeholder').replace('⌘K', isMac ? '⌘K' : 'Ctrl+K')

  // Cmd+K (Mac) / Ctrl+K (Win/Linux) focuses the project filter
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setFilterFocused(true)
        // defer so the input is rendered before focusing
        setTimeout(() => filterInputRef.current?.focus(), 0)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])
  const filteredProjects = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return projects
    return projects.filter(p => p.slug === selectedSlug || p.name.toLowerCase().includes(q))
  }, [projects, filter, selectedSlug])

  // Build prompts leaf nodes
  const promptItems: LeafNode[] = useMemo(() => {
    if (!selectedSlug) return [{ kind: 'ghost', name: t('spine.none.yet') }]
    const rows = promptListByProject[selectedSlug]
    if (!rows || rows.length === 0) return [{ kind: 'ghost', name: t('spine.none.yet') }]
    return rows.map(row => ({
      kind: 'file' as const,
      name: row.label,
      stamp: '',
      active: row.is_active,
      onClick: row.is_active
        ? () => openPrompt(selectedSlug)
        : () => openPrompt(selectedSlug, row.prompt_id),
    }))
  }, [selectedSlug, promptListByProject, openPrompt, locale, t])

  // Build models leaf nodes
  const modelItems: LeafNode[] = useMemo(() => {
    if (!selectedSlug) return [{ kind: 'ghost', name: t('spine.none.yet') }]
    const rows = modelListByProject[selectedSlug]
    if (!rows || rows.length === 0) return [{ kind: 'ghost', name: t('spine.none.yet') }]
    return rows.map(row => ({
      kind: 'file' as const,
      name: row.provider_model_id,
      stamp: '',
      active: row.is_active,
      onClick: undefined,
    }))
  }, [selectedSlug, modelListByProject, locale, t])

  // Build metrics/ leaf nodes from the eval list. Each entry routes to the
  // matrix page for that ts; the most recent ts gets the active marker.
  const metricsItems: LeafNode[] = useMemo(() => {
    if (!selectedSlug) return [{ kind: 'ghost', name: t('spine.none.yet') }]
    const rows = evalListByProject[selectedSlug]
    if (!rows || rows.length === 0) return [{ kind: 'ghost', name: t('spine.none.yet') }]
    return rows.map((row, i) => {
      // M12.x — spine stamp prefers field_accuracy_macro, then doc_accuracy,
      // then the legacy macro_f1 (which on M12.x writes is null but on older
      // disk JSON still carries an F1 number).
      const fieldAcc = row.field_accuracy_macro
      let stamp = ''
      if (typeof fieldAcc === 'number') {
        stamp = `${(fieldAcc * 100).toFixed(1)}%`
      } else if (row.doc_accuracy != null) {
        stamp = `${(row.doc_accuracy * 100).toFixed(1)}%`
      } else if (typeof row.macro_f1 === 'number') {
        stamp = row.macro_f1.toFixed(2)
      }
      return {
        kind: 'file' as const,
        name: `eval_${row.ts}`,
        stamp,
        active: i === 0,
        onClick: () => {
          window.history.pushState(null, '', pathForEvalMatrix(selectedSlug, row.ts))
          window.dispatchEvent(new PopStateEvent('popstate'))
        },
      }
    })
  }, [selectedSlug, evalListByProject, locale, t])

  // Build experiments leaf nodes
  const experimentItems: LeafNode[] = useMemo(() => {
    if (!selectedSlug) return [{ kind: 'ghost', name: t('spine.none.yet') }]
    const rows = experimentListByProject[selectedSlug]
    if (!rows || rows.length === 0) return [{ kind: 'ghost', name: t('spine.none.yet') }]
    return rows.map(row => ({
      kind: 'file' as const,
      name: row.label,
      stamp: row.score != null
        ? `${row.status} · ${row.score.toFixed(2)}`
        : row.status,
      active: false,
      onClick: undefined,
    }))
  }, [selectedSlug, experimentListByProject, locale, t])

  const tree = useMemo<BuiltTree | null>(
    () => activeProject
      ? buildTree(
          activeProject.slug,
          activeDocs,
          activeProject.active_version_id ?? null,
          promptItems,
          modelItems,
          experimentItems,
          metricsItems,
          (slug, filename) => navigateToReview(slug, filename),
          docsVisible,
          loadMoreDocs,
          selectedDocFilename,
          t('spine.versions.empty'),
          {
            new: t('spine.stamp.new'),
            pending: t('spine.stamp.pending'),
            reviewed: t('spine.stamp.reviewed'),
            frozen: t('spine.stamp.frozen'),
          },
        )
      : null,
    [activeProject, activeDocs, activeSchemaFields.length, promptItems, modelItems, experimentItems, metricsItems, docsVisible, loadMoreDocs, selectedDocFilename, locale, t],
  )

  // When review ← / → steps past the visible page boundary, bump
  // docsVisible so the row that should look "selected" is actually rendered.
  // Without this the highlight silently goes nowhere when the active doc is
  // past the initial DOCS_INITIAL slice.
  useEffect(() => {
    if (!selectedDocFilename) return
    const idx = activeDocs.findIndex(d => d.filename === selectedDocFilename)
    if (idx >= 0 && idx >= docsVisible) {
      setDocsVisible(idx + 1)
    }
  }, [selectedDocFilename, activeDocs, docsVisible])

  // Scroll the selected doc row into view when it changes (e.g. ← / → in
  // review). Lives inside the spine's scroll container so other scroll
  // positions aren't disturbed.
  const selectedRowRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!selectedDocFilename) return
    // Drop the browser focus ring from whichever row the user last clicked.
    // Without this, click-focus outlines stick on the previously-active row
    // while .selected has already moved on via ← / → navigation.
    const focused = document.activeElement as HTMLElement | null
    if (
      focused
      && focused !== selectedRowRef.current
      && focused.classList.contains('branch')
      && focused.classList.contains('file')
    ) {
      focused.blur()
    }
    const el = selectedRowRef.current
    if (!el) return
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selectedDocFilename])

  // Ensure docs/ is expanded when a doc gets selected via review nav.
  useEffect(() => {
    if (selectedDocFilename) setOpenDirs(s => (s['docs/'] ? s : { ...s, 'docs/': true }))
  }, [selectedDocFilename])

  // When the active project changes, bring its row (and the inline tree that
  // now renders directly beneath it) into view. Fixes the "I clicked a
  // mid-list project but nothing seemed to happen" confusion — the tree was
  // previously rendered far below the whole flat list, off-screen.
  useEffect(() => {
    if (!selectedSlug) return
    const el = selectedProjRef.current
    if (!el) return
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selectedSlug])

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

  // The active project's file tree — rendered inline, directly beneath its
  // own row in the project list (accordion). Previously this lived at the
  // bottom of the whole flat list, so with many projects it sat off-screen.
  const treeNode = activeProject && tree ? (
    <div className="tree nested">
      {tree.groups.map(g => {
        const open = !!openDirs[g.name]
        return (
          <div key={g.name}>
            <div className="branch dir" onClick={() => toggleDir(g.name)}>
              {open
                ? <ChevronDown size={13} className="arrow" strokeWidth={2} />
                : <ChevronRight size={13} className="arrow" strokeWidth={2} />}
              <span className="dir-name">{g.name}</span>
              <span className="stamp">{g.count}</span>
              {/* ── experiments/ → open Bench leaderboard ─────────
                  Secondary affordance: a small ↗ icon button that
                  deep-links to `?bench=1`. stopPropagation so the
                  click never bubbles up to toggleDir (which would
                  also fire from the parent .branch.dir handler).
                  Disabled when there's no active project. */}
              {g.name === 'experiments/' && (
                <button
                  type="button"
                  className="bench-open"
                  aria-label={t('spine.experiments.open_bench')}
                  title={t('spine.experiments.open_bench')}
                  disabled={!selectedSlug}
                  onClick={e => {
                    e.stopPropagation()
                    if (!selectedSlug) return
                    window.history.pushState(null, '', pathForBench(selectedSlug))
                    window.dispatchEvent(new PopStateEvent('popstate'))
                  }}
                >↗</button>
              )}
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
                    <MoreHorizontal size={14} className="leaf-icon" strokeWidth={1.75} />
                    <span className="leaf-name">{t('spine.more', { n: n.remaining })}</span>
                  </div>
                )
              }
              const isVersion = g.name === 'versions/' && selectedSlug
              const clickHandler = isVersion
                ? () => openVersion(selectedSlug!, n.name)
                : n.onClick
              const isSelected = !!n.selected
              const LeafIcon = n.active ? Star : (GROUP_ICON[g.name] ?? FileText)
              return (
                <div
                  key={j}
                  ref={isSelected ? selectedRowRef : undefined}
                  className={'branch file' + (isSelected ? ' selected' : '')}
                  onClick={clickHandler}
                  role={clickHandler ? 'button' : undefined}
                  tabIndex={clickHandler ? 0 : undefined}
                  onKeyDown={clickHandler ? e => { if (e.key === 'Enter' || e.key === ' ') clickHandler() } : undefined}
                  style={clickHandler ? { cursor: 'pointer' } : undefined}
                  aria-current={isSelected ? 'true' : undefined}
                >
                  <LeafIcon
                    size={14}
                    strokeWidth={1.75}
                    className={'leaf-icon' + (n.active ? ' active' : '')}
                    {...(n.active ? { fill: 'currentColor' } : {})}
                  />
                  <span className="leaf-name">{n.name}</span>
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
          className="branch file root"
        >
          <FileText size={14} strokeWidth={1.75} className="leaf-icon" />
          <span className="leaf-name">{n.name}</span>
          {n.stamp && <span className="stamp">{n.stamp}</span>}
        </div>
      ))}
    </div>
  ) : null

  return (
    <div className="fs">
      {/* ── brand + collapse toggle ───────────────────────────────────── */}
      <div className="fs-brand-row">
        <div className="fs-brand">
          <img src={kdfpyIcon} alt="" className="brand-icon" />Piaozone
          <span className="fs-badge">{t('auth.preview')}</span>
        </div>
        {onToggleLeft && (
          <PanelToggle
            side="left"
            hidden={false}
            onClick={onToggleLeft}
            className="fs-toggle"
          />
        )}
      </div>

      {/* ── new project ──────────────────────────────────────────────── */}
      <div className="fs-new-proj">
        <div
          className="proj new"
          onClick={() => useProjects.getState().startNew()}
        >
          <FolderPlus size={15} className="proj-icon" strokeWidth={1.75} />
          <span className="proj-name">{t('spine.project.new')}</span>
        </div>
      </div>

      {/* ── scrollable middle (project list + tree) ─────────────────── */}
      <div className="fs-scroll">

      {/* ── ~/projects header ─────────────────────────────────────────── */}
      <div className="fs-head">
        ~/projects <span className="small">{projects.length}</span>
      </div>

      {/* ── project filter (surfaces only when the list is long) ───────── */}
      {showFilter && (
        <div className="fs-filter">
          <Search size={13} className="fs-filter-icon" strokeWidth={1.75} />
          <input
            ref={filterInputRef}
            className="fs-filter-input"
            type="text"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            onBlur={() => { if (projects.length <= FILTER_THRESHOLD && !filter) setFilterFocused(false) }}
            onKeyDown={e => { if (e.key === 'Escape') { setFilter(''); filterInputRef.current?.blur() } }}
            placeholder={filterPlaceholder}
            spellCheck={false}
            autoComplete="off"
          />
          {filter && (
            <button
              type="button"
              className="fs-filter-clear"
              aria-label={t('spine.filter.clear')}
              title={t('spine.filter.clear')}
              onClick={() => setFilter('')}
            >
              <X size={13} strokeWidth={2} />
            </button>
          )}
        </div>
      )}

      {/* ── project rows (each can expand its file tree inline) ────────── */}
      {projects.length === 0 && (
        <div className="ghost" style={{ padding: '4px 16px' }}>{t('spine.projects.empty')}</div>
      )}
      {projects.length > 0 && filteredProjects.length === 0 && (
        <div className="ghost" style={{ padding: '4px 16px' }}>{t('spine.filter.empty')}</div>
      )}
      {filteredProjects.map(p => {
        // React `key` and selection state are keyed on slug (the disk-truth
        // identifier). The visible label is the user-given `name`, which can
        // diverge from slug after rename / when name has chars slug stripped.
        const isActive = p.slug === selectedSlug
        const isOpen = isActive && !!expanded[p.slug]
        // Row click: open an unopened project (selecting it); re-clicking the
        // already-open active project collapses it. The chevron mirrors state.
        const onRowClick = () => {
          if (isActive) {
            setExpanded(s => ({ ...s, [p.slug]: !s[p.slug] }))
          } else {
            useProjects.getState().select(p.slug)
            setExpanded(s => ({ ...s, [p.slug]: true }))
          }
        }
        return (
          <div key={p.slug}>
            <div
              ref={isActive ? selectedProjRef : undefined}
              className={'proj' + (isActive ? ' active' : '')}
              onClick={onRowClick}
            >
              {/* folder + chevron share one slot — the twisty replaces the
                  folder on hover/active so the column never gains a reserved
                  chevron indent (see .proj-disc in spine.css) */}
              <span className="proj-disc">
                {isActive
                  ? <FolderOpen size={15} className="proj-icon" strokeWidth={1.75} />
                  : <Folder size={15} className="proj-icon" strokeWidth={1.75} />}
                {isOpen
                  ? <ChevronDown size={13} className="proj-arrow" strokeWidth={2} />
                  : <ChevronRight size={13} className="proj-arrow" strokeWidth={2} />}
              </span>
              <span className="proj-name">{p.name}</span>
              {isActive && (
                <span
                  className="status-dot"
                  title={p.status ?? 'empty'}
                  style={{ background: STATUS_DOT[p.status ?? 'empty'] ?? 'var(--ink-5)' }}
                />
              )}
            </div>
            {/* active project's docs/ prompts/ … expand right here */}
            {isOpen && treeNode}
          </div>
        )
      })}

      </div>{/* /fs-scroll */}

      {/* ── pinned bottom: user identity + menu ──────────────────────── */}
      <div className="fs-foot">
        <UserMenu variant="expanded" />
      </div>
    </div>
  )
}
