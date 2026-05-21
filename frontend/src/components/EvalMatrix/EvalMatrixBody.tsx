import { useCallback, useEffect, useMemo, useState } from 'react'

import { evalMatrixCsvUrl, getLatestEval } from '../../lib/api'
import { navigateToReview, pathForEvalCompare, pathForEvalMatrix } from '../../lib/slugUrl'
import { useEval } from '../../stores/eval'
import { useEvalSurface } from '../../stores/evalSurface'
import { useReview } from '../../stores/review'
import { useSchema } from '../../stores/schema'
import type { CellVerdict, ScoreResultSummary } from '../../types/eval'
import { synthesizeAccuracyMacro } from '../../types/eval'
import CellDrilldown from './CellDrilldown'
import MatrixGrid from './MatrixGrid'
import { type MatrixFilter, pct } from './filters'


function flattenFieldNames(fields: Array<{ name: string | null }>): string[] {
  return fields.map((f) => f.name ?? '').filter(Boolean)
}


interface Props {
  slug: string
  ts: string
  /** When true, body chrome is tailored for a modal host — header back-link
   *  becomes invisible (the modal header handles it). When false, the body
   *  renders its own back-link, matching the legacy standalone page. */
  inModal?: boolean
  /** Modal host hook — invoked after the chat-review handoff so the modal
   *  closes itself before navigating to the review surface. */
  onAfterOpenReview?: () => void
}


/** EvalMatrixBody — shared loader + matrix shell used by both the modal
 *  overlay (`EvalMatrixModal`) and the standalone `EvalMatrixPage`. Owns the
 *  `latest`-resolution, summary/cells/list loads, filter toggle, and drilldown
 *  state. The wrapping host decides chrome (modal card vs. min-h-screen). */
export default function EvalMatrixBody({ slug, ts, inModal = false, onAfterOpenReview }: Props) {
  // ts="latest" is a virtual alias — resolve to the actual most-recent ts via
  // GET /lab/projects/{slug}/evals/latest, then replaceState so the address
  // bar pins to a canonical, bookmarkable URL. resolvedTs is null while
  // resolving; we render a Loading state and skip store loads in that window.
  const [resolvedTs, setResolvedTs] = useState<string | null>(
    ts === 'latest' ? null : ts,
  )
  const [latestMissing, setLatestMissing] = useState(false)

  useEffect(() => {
    if (ts !== 'latest') {
      setResolvedTs(ts)
      setLatestMissing(false)
      return
    }
    let cancelled = false
    setResolvedTs(null)
    setLatestMissing(false)
    getLatestEval(slug)
      .then((blob) => {
        if (cancelled) return
        if (!blob || !blob.ts) {
          setLatestMissing(true)
          return
        }
        setResolvedTs(blob.ts)
        // pathForEvalMatrix produces the new `/p/<slug>?eval=<ts>` shape so
        // the address bar stays in sync whether we're modal or standalone.
        window.history.replaceState(null, '', pathForEvalMatrix(slug, blob.ts))
      })
      .catch(() => {
        if (!cancelled) setLatestMissing(true)
      })
    return () => { cancelled = true }
  }, [slug, ts])

  const summary = useEval((s) => (resolvedTs ? s.summary[`${slug}|${resolvedTs}`] : undefined))
  const cells = useEval((s) => (resolvedTs ? s.cells[`${slug}|${resolvedTs}`] : undefined))
  const list = useEval((s) => s.list[slug])
  const loadSummary = useEval((s) => s.loadSummary)
  const loadCells = useEval((s) => s.loadCells)
  const loadList = useEval((s) => s.loadList)
  const schemaFields = useSchema((s) => s.byProject[slug])
  const loadSchema = useSchema((s) => s.load)

  useEffect(() => {
    if (!resolvedTs) return
    loadSummary(slug, resolvedTs)
    loadCells(slug, resolvedTs)
    loadList(slug)
    if (!schemaFields) loadSchema(slug)
  }, [slug, resolvedTs, loadSummary, loadCells, loadList, loadSchema, schemaFields])

  const [filter, setFilter] = useState<MatrixFilter>('errors_only')
  const [drilldown, setDrilldown] = useState<CellVerdict | null>(null)

  const fields = useMemo(() => flattenFieldNames(schemaFields ?? []), [schemaFields])

  // openDrilldown / closeDrilldown also mirror the active cell into
  // useEvalSurface so ChatPanel (compact) can read it at submit time and
  // attach a `surface: 'eval_cell'` SurfaceContext to the chat envelope.
  // resolvedTs is the canonical (non-`latest`) ts captured by the resolver
  // effect above — we read it via the captured local so the snapshot is
  // stable across the drilldown's lifetime.
  const openDrilldown = useCallback((c: CellVerdict) => {
    setDrilldown(c)
    useEvalSurface.getState().setActive(resolvedTs, c)
  }, [resolvedTs])

  const closeDrilldown = useCallback(() => {
    setDrilldown(null)
    useEvalSurface.getState().setActive(null, null)
  }, [])

  // Layered ESC: when the drilldown is open, ESC closes ONLY the drilldown
  // — the modal's window-level ESC handler must not also fire. We register
  // in the capture phase + stopPropagation so the modal's bubble-phase
  // handler never runs while the drilldown owns ESC.
  useEffect(() => {
    if (!drilldown) return
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      e.preventDefault()
      closeDrilldown()
    }
    document.addEventListener('keydown', onKey, { capture: true })
    return () => document.removeEventListener('keydown', onKey, { capture: true })
  }, [drilldown, closeDrilldown])

  // Clean up the eval surface store on unmount so a stale cell can't leak
  // into the next chat turn after the modal closes.
  useEffect(() => {
    return () => {
      useEvalSurface.getState().setActive(null, null)
    }
  }, [])

  const onOpenReview = () => {
    if (!drilldown) return
    const field = drilldown.field
    closeDrilldown()
    // navigateToReview pushes `?review=<filename>` (and drops `?eval=`),
    // App's URL → useReview sync picks it up and calls open(). The modal
    // unmounts via the same popstate cycle because ?eval is gone. No need
    // to call onAfterOpenReview anymore — the URL is the source of truth.
    navigateToReview(slug, drilldown.filename)
    // activeField is a secondary review-store field (not in URL); set after
    // the navigation so the URL→store open path doesn't reset it.
    useReview.setState({ activeField: field })
  }
  // Keep `inModal` and `onAfterOpenReview` referenced so the lint/tsc layer
  // doesn't warn about unused params; both remain part of the public surface
  // for callers that may still wire a close-when-review-opens hook.
  void inModal; void onAfterOpenReview;

  // Selection ring: pass a stable key to MatrixGrid so the currently-open
  // drilldown's cell gets `ring-2 ring-ochre` highlighting. Format matches
  // MatrixGrid's `${filename}|${field}|${entity_idx}` lookup.
  const selectedKey = drilldown
    ? `${drilldown.filename}|${drilldown.field}|${drilldown.entity_idx}`
    : undefined

  // Compare-link target: latest ts that isn't this one (if any).
  const compareTargetA = useMemo(() => {
    if (!list || list.length === 0 || !resolvedTs) return null
    const other = list.find((row) => row.ts !== resolvedTs)
    return other?.ts ?? null
  }, [list, resolvedTs])

  if (latestMissing) {
    return (
      <div className="text-ink-3 text-sm">
        这个项目还没有任何 eval 快照。从 chat 跑 <code>/eval</code> 后再来。
      </div>
    )
  }

  return (
    <>
      {/* Header is rendered by the modal host in modal mode; in standalone
          mode we still emit the page-level header so EvalMatrixPage has a
          back-link to the project shell. */}
      {!inModal && (
        <header className="mb-6 flex items-baseline justify-between">
          <div>
            <a
              href={pathForSlug(slug)}
              className="text-ink-3 hover:text-ink-2 text-sm"
            >
              ← {slug}
            </a>
            <h1 className="text-xl font-semibold mt-1">eval · {resolvedTs ?? '…'}</h1>
          </div>
          <SummaryStrip summary={summary} />
        </header>
      )}

      {/* Modal mode — render summary strip as a sub-header above the filters
          so the modal card's own title bar stays minimal. */}
      {inModal && summary && (
        <div className="mb-3">
          <SummaryStrip summary={summary} />
        </div>
      )}

      <div className="mb-4 flex items-center gap-4 text-sm">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={filter === 'errors_only'}
            onChange={(e) =>
              setFilter(e.target.checked ? 'errors_only' : 'all')
            }
          />
          只看错误
        </label>
        {resolvedTs && (
          <a
            href={evalMatrixCsvUrl(slug, resolvedTs)}
            download
            className="text-ochre hover:underline"
          >
            下载 CSV
          </a>
        )}
        {resolvedTs && compareTargetA && (
          <a
            href={pathForEvalCompare(slug, compareTargetA, resolvedTs)}
            className="text-ochre hover:underline"
          >
            对比 {compareTargetA}
          </a>
        )}
        <MatrixLegend />
      </div>

      {!summary && <div className="text-ink-3 text-sm">Loading…</div>}

      {/* `relative` anchors the click-catcher overlay below — using
          `absolute inset-0` (inside this container) keeps the catcher
          scoped to the matrix area, so clicking it closes the drilldown
          but clicking the modal backdrop outside the card still closes
          the modal. */}
      <div className="relative">
        {cells && (
          <MatrixGrid
            cells={cells}
            fields={fields}
            filter={filter}
            onCellClick={openDrilldown}
            selectedKey={selectedKey}
          />
        )}

        {/* Click-catcher: rendered behind the `z-50` drilldown sidebar but
            above the matrix. Clicking the matrix area while the drilldown is
            open closes only the drilldown — matrix layer absorbs the click,
            modal backdrop never sees it. */}
        {drilldown && (
          <div
            className="absolute inset-0 z-40"
            onClick={closeDrilldown}
            aria-hidden="true"
          />
        )}
      </div>

      {drilldown && (
        <CellDrilldown
          slug={slug}
          cell={drilldown}
          onClose={closeDrilldown}
          onOpenReview={onOpenReview}
        />
      )}
    </>
  )
}


// Legend chips mirror MatrixGrid's `statusBgClass` mapping so users can
// decode the cell colors without having to click into one. Right-aligned via
// `ml-auto` so it floats opposite "只看错误" / "下载 CSV" without consuming
// space when the row is narrow.
function MatrixLegend() {
  return (
    <div className="ml-auto flex items-center gap-3 text-xs text-ink-3">
      <span className="flex items-center gap-1">
        <span className="inline-block w-3 h-3 rounded-sm bg-moss-soft border border-rule" />
        正确
      </span>
      <span className="flex items-center gap-1">
        <span className="inline-block w-3 h-3 rounded-sm bg-rose-soft border border-rule" />
        错误
      </span>
      <span className="flex items-center gap-1">
        <span className="inline-block w-3 h-3 rounded-sm bg-ochre-soft border border-rule" />
        漏/多
      </span>
    </div>
  )
}


function SummaryStrip({ summary }: { summary: ScoreResultSummary | undefined }) {
  if (!summary) return null
  // M12.x.d — anchor chip: which (model, prompt) produced these metrics.
  // We prefer the resolved labels (e.g. `gemini-2.5-flash · baseline`) so
  // users address runs by the semantic name they already use in chat, not
  // by hash IDs. Falls back to IDs only when labels are missing (e.g. a
  // legacy summary that pre-dates this anchor).
  const modelChip = summary.extract_model ?? summary.model_id ?? null
  const promptChip = summary.prompt_label ?? summary.prompt_id ?? null
  return (
    <div className="flex items-center gap-4 text-sm">
      {(modelChip || promptChip) && (
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-rule bg-paper-2 text-ink-2 font-mono text-xs"
          title={`prompt_id=${summary.prompt_id ?? '?'} · model_id=${summary.model_id ?? '?'}`}
        >
          {modelChip && <span>{modelChip}</span>}
          {modelChip && promptChip && <span className="text-ink-4">·</span>}
          {promptChip && <span>{promptChip}</span>}
        </span>
      )}
      <span>
        字段准确率 <strong>{pct(synthesizeAccuracyMacro(summary))}</strong>
      </span>
      <span>
        文档准确率 <strong>{pct(summary.doc_accuracy)}</strong>
      </span>
      <span className="text-ink-3">{summary.n_reviewed} docs</span>
      {summary.judge_used > 0 && (
        <span className="text-ochre">LLM judged: {summary.judge_used}</span>
      )}
    </div>
  )
}


