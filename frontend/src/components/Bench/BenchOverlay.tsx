// BenchOverlay — modal shell that assembles the bench leaderboard surface.
//
// Lifecycle mirrors `EvalMatrixModal`:
//   - App.tsx mounts this component when `?bench=1` is in the URL search
//     string AND a project is selected. The presence of the query param IS
//     the open state (bench has no sub-state worth encoding).
//   - The overlay does not push/pop the URL itself; App.tsx owns the URL ↔
//     mount mapping. `onClose` lets App.tsx strip `?bench=1` from search.
//   - ESC, the close button, and a project switch all funnel into `onClose`.
//   - Row click on a scored experiment calls `onOpenRow(row)` so App.tsx can
//     push `?eval=<summary_ts>` (and close bench — the two overlays are
//     mutually exclusive for this milestone; see plan T6 simplification).
//
// Local state owned here:
//   - `selectedIds: Set<string>`  → toggled by the matrix checkbox cell;
//     drives BenchSelectionBar's compare CTA enablement.
//   - `hovered: AxisHovered|null` → fed back into both AxisRails so a chip
//     hover dims non-matching matrix rows.
//   - `diffOpen: boolean`         → BenchDiff modal hook. T7 will replace
//     the `data-testid="bench-diff-placeholder"` div with the real diff
//     component; for now we keep the open/close plumbing so the SelectionBar
//     compare CTA has somewhere to land.
//
// The store side: `useBench` is cache-first per slug. We trigger `load(slug)`
// on mount; if the slug is already cached the call is a no-op and the matrix
// renders synchronously on the first paint. Cache misses show a small
// `data-testid="bench-loading"` placeholder; surfaced errors get a retry
// affordance (T9's mutation invalidation hook keeps the cache fresh after
// experiment / prompt / model edits).

import { X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { useT } from '../../i18n'
import { useBench } from '../../stores/bench'
import { useProjects } from '../../stores/projects'
import type { BenchRow } from '../../types/bench'
import AxisRail, { type AxisHovered } from './AxisRail'
import BenchDiff from './BenchDiff'
import BenchHeadline from './BenchHeadline'
import BenchMatrix from './BenchMatrix'
import BenchSelectionBar from './BenchSelectionBar'
import './Bench.css'

/** Format a PromptVariant blob into plain text for BenchDiff's line-by-line
 *  diff. We flatten the schema array into `# field_name\n  description` blocks
 *  and append `global_notes` so the same prompt always serializes to the
 *  same string regardless of how the user authored it. Kept here (not in
 *  BenchDiff) so the diff component stays prop-driven and easy to test. */
function formatPromptBody(blob: {
  schema?: Array<{ name?: string; description?: string }>
  global_notes?: string
}): string {
  const parts: string[] = []
  for (const f of blob.schema ?? []) {
    if (!f.name) continue
    parts.push(`# ${f.name}`)
    if (f.description) parts.push(`  ${f.description}`)
  }
  if (blob.global_notes && blob.global_notes.trim()) {
    parts.push('')
    parts.push('## global_notes')
    parts.push(blob.global_notes)
  }
  return parts.join('\n')
}


interface Props {
  slug: string
  onClose: () => void
  onOpenRow: (row: BenchRow) => void
  /** True when an EvalMatrix (or any other higher-z overlay) is layered on
   *  top: render Bench's DOM tree (so selection / scroll / hovered state
   *  survive), but yank it out of layout + event flow with `display: none`
   *  and stand down our Esc listener so the layered overlay owns the
   *  keyboard. Mirrors the EvalMatrixModal `hidden` prop. */
  hidden?: boolean
}


export default function BenchOverlay({ slug, onClose, onOpenRow, hidden = false }: Props) {
  const bench = useBench(s => s.byProject[slug])
  const loading = useBench(s => !!s.loading[slug])
  const load = useBench(s => s.load)
  const [error, setError] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [hovered, setHovered] = useState<AxisHovered | null>(null)
  // Click-to-pin a chip → persistent dim filter that survives mouseleave.
  // Click the same chip again to clear; click another chip to swap.
  // ESC clears (handled below). The matrix reads `pinned ?? hovered` so the
  // pin "locks the lens" but hovering another chip still gives a transient
  // preview without dropping the lock.
  const [pinned, setPinned] = useState<AxisHovered | null>(null)
  const [diffOpen, setDiffOpen] = useState(false)
  // Prompt body cache keyed by prompt_id — populated lazily when the diff
  // modal opens. The bench response itself only carries prompt labels +
  // `refs` counts, not the full schema/global_notes blob, so we hit
  // `/lab/projects/<slug>/prompts/<pr_id>` on demand. `null` = in-flight;
  // missing key = "not yet asked".
  const [promptBodies, setPromptBodies] = useState<Record<string, string | null>>({})
  const t = useT()

  // Cache-first load. The store dedupes concurrent loads on the same slug so
  // we don't have to guard mount-vs-StrictMode-double-effect here.
  useEffect(() => {
    setError(null)
    void load(slug).catch(e => setError(e instanceof Error ? e.message : String(e)))
  }, [slug, load])

  // ESC closes — single window-level listener so the handler fires regardless
  // of focus target. BenchDiff registers its own Esc handler (also
  // window-level); listener-order semantics mean both run on a single Esc
  // press, but BenchDiff's `preventDefault` doesn't stop the overlay's
  // handler from also firing. To get the conventional "Esc closes the
  // top-most layer first" UX we early-return here when the diff is open —
  // the user has to press Esc twice to fully close the modal stack, which
  // matches PromptQuickLook + ReviewOverlay.
  useEffect(() => {
    if (hidden) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (diffOpen) return
        e.preventDefault()
        // Esc layering: pinned chip filter wins over closing the overlay,
        // mirroring how Esc clears search input before closing a dialog
        // elsewhere. Each press peels one layer.
        if (pinned) {
          setPinned(null)
          return
        }
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, diffOpen, hidden, pinned])

  // Project switch → auto-close. Mirrors `PromptQuickLook` pattern: subscribe
  // synchronously to `useProjects` (zustand subscribers fire on setState
  // before the next render) so the modal evicts immediately when the user
  // picks another project in FSSpine, rather than flashing stale data.
  useEffect(() => {
    const unsub = useProjects.subscribe(s => {
      if (s.selectedSlug !== null && s.selectedSlug !== slug) {
        onClose()
      }
    })
    return unsub
  }, [slug, onClose])

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const clearSelected = () => setSelectedIds(new Set())
  const closeDiff = () => setDiffOpen(false)

  // Resolve the two rows + axis label dicts up-front so the rest of the
  // render can be straight-line and BenchDiff's prop set stays narrow.
  const selectedRows: BenchRow[] = useMemo(() => {
    if (!bench) return []
    return bench.rows.filter(r => selectedIds.has(r.id))
  }, [bench, selectedIds])
  const promptLabels = useMemo(() => {
    const m: Record<string, string> = {}
    for (const p of bench?.prompts ?? []) m[p.id] = p.label
    return m
  }, [bench])
  const modelLabels = useMemo(() => {
    const m: Record<string, string> = {}
    for (const mm of bench?.models ?? []) m[mm.id] = mm.label
    return m
  }, [bench])

  // Lazy prompt-body fetch: when the user opens diff, we need full
  // `{schema, global_notes}` blobs for both selected rows (skipped if the
  // two rows share the same prompt_id). The fetch is fire-and-forget per
  // prompt_id, deduped via the `promptBodies` keyspace: `undefined` = not
  // yet requested, `null` = in-flight, string = ready.
  const openDiff = () => {
    setDiffOpen(true)
    if (!bench || selectedRows.length !== 2) return
    if (selectedRows[0].prompt_id === selectedRows[1].prompt_id) return
    for (const row of selectedRows) {
      const pid = row.prompt_id
      if (pid in promptBodies) continue
      setPromptBodies(prev => ({ ...prev, [pid]: null }))
      const slugEnc = encodeURIComponent(slug)
      const pidEnc = encodeURIComponent(pid)
      fetch(`/lab/projects/${slugEnc}/prompts/${pidEnc}`)
        .then(r => r.ok ? r.json() : Promise.reject(new Error(`prompt ${pid} ${r.status}`)))
        .then((blob: unknown) => {
          const text = formatPromptBody(
            blob as { schema?: Array<{ name?: string; description?: string }>; global_notes?: string },
          )
          setPromptBodies(prev => ({ ...prev, [pid]: text }))
        })
        .catch(() => {
          // Fail-soft: leave the entry as null so the diff modal shows its
          // loading skeleton; the user can close + retry.
          setPromptBodies(prev => ({ ...prev, [pid]: '' }))
        })
    }
  }

  // Counts surfaced in the topbar + headline. We derive from the active
  // payload rather than threading through props so the inputs stay narrow.
  const reviewedCount = useMemo(() => {
    if (!bench) return 0
    // The "reviewed count" headline displays the doc coverage of any one
    // experiment's eval. We approximate via the max `total` across all
    // (row, field) cells — every row shares the same review set per plan
    // T2, so the largest non-zero `total` is the universal coverage.
    let m = 0
    for (const row of bench.rows) {
      for (const f in row.cells) {
        const c = row.cells[f]
        if (c && c.total > m) m = c.total
      }
    }
    return m
  }, [bench])

  const headlineCtx = useMemo(() => {
    if (!bench) {
      return {
        bestPromptLabel: null as string | null,
        bestModelLabel: null as string | null,
        experimentCount: 0,
        promptCount: 0,
        modelCount: 0,
      }
    }
    const bestPrompt = bench.headline.best_prompt_id
      ? bench.prompts.find(p => p.id === bench.headline.best_prompt_id)?.label ?? null
      : null
    const bestModel = bench.headline.best_model_id
      ? bench.models.find(m => m.id === bench.headline.best_model_id)?.label ?? null
      : null
    return {
      bestPromptLabel: bestPrompt,
      bestModelLabel: bestModel,
      experimentCount: bench.rows.filter(r => r.kind === 'experiment').length,
      promptCount: bench.prompts.length,
      modelCount: bench.models.length,
    }
  }, [bench])

  // Promote / runEval action stubs. The wider mutation flow lives in chat NL
  // ("/promote ex_…" etc.) — for now we surface the buttons in the matrix
  // but defer the actual API call to follow-up. The placeholders keep the
  // component contract stable so T9 can wire mutation invalidation without
  // re-shaping the props.
  const onPromote = (_id: string) => { /* T9 wires this */ }
  const onRunEval = (_id: string) => { /* T9 wires this */ }

  return (
    <div
      className="fixed inset-0 z-40 backdrop-blur-sm flex items-center justify-center p-6"
      // Inline rgba derived from --ink (#1B1A16) at 35% — matches
      // EvalMatrixModal so chat shell dimming is consistent.
      // display:none when hidden keeps the React tree mounted (selectedIds /
      // hovered / promptBodies cache intact) but yanks the backdrop + card
      // out of layout / event flow so the layered EvalMatrix takes the
      // keyboard + clicks cleanly. Same pattern as EvalMatrixModal#hidden.
      style={{ background: 'rgba(27, 26, 22, 0.35)', display: hidden ? 'none' : undefined }}
      onClick={hidden ? undefined : onClose}
      role="dialog"
      aria-label="bench"
      aria-modal="true"
      aria-hidden={hidden}
    >
      <div
        className="bg-paper text-ink rounded-lg shadow-xl border border-rule flex flex-col w-full max-w-[min(1480px,96vw)] max-h-[92vh] overflow-hidden relative"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="b-card-close"
          aria-label={t('bench.topbar.close.aria')}
          title={t('bench.topbar.close')}
          onClick={onClose}
        >
          <X size={16} />
        </button>

        <div className="bench-root">
          <div className="bench-scroll">
            <div className="bench-body">
              {error ? (
                <div
                  data-testid="bench-error"
                  className="b-headline-counts"
                  role="alert"
                >
                  <span>{t('bench.overlay.error.title')}</span>
                  <span className="b-h-sep">·</span>
                  <button
                    type="button"
                    onClick={() => {
                      setError(null)
                      useBench.getState().invalidate(slug)
                      void load(slug).catch(e =>
                        setError(e instanceof Error ? e.message : String(e)),
                      )
                    }}
                  >
                    {t('bench.overlay.error.retry')}
                  </button>
                </div>
              ) : !bench ? (
                <div
                  data-testid="bench-loading"
                  className="b-headline-counts"
                  aria-busy={loading}
                >
                  <span>{t('bench.overlay.loading')}</span>
                </div>
              ) : (
                <>
                  <BenchHeadline
                    bestScore={bench.headline.best_score}
                    bestPromptLabel={headlineCtx.bestPromptLabel}
                    bestModelLabel={headlineCtx.bestModelLabel}
                    experimentCount={headlineCtx.experimentCount}
                    promptCount={headlineCtx.promptCount}
                    modelCount={headlineCtx.modelCount}
                    reviewedCount={reviewedCount}
                  />
                  <div className="b-rails">
                    <AxisRail
                      kind="prompt"
                      items={bench.prompts}
                      hovered={hovered}
                      pinned={pinned}
                      onHover={setHovered}
                      onPin={setPinned}
                    />
                    <AxisRail
                      kind="model"
                      items={bench.models}
                      hovered={hovered}
                      pinned={pinned}
                      onHover={setHovered}
                      onPin={setPinned}
                    />
                  </div>
                  <BenchMatrix
                    rows={bench.rows}
                    fields={bench.fields}
                    prompts={bench.prompts}
                    models={bench.models}
                    selectedIds={selectedIds}
                    hovered={pinned ?? hovered}
                    onToggleSelect={toggleSelect}
                    onOpenRow={onOpenRow}
                    onPromote={onPromote}
                    onRunEval={onRunEval}
                  />
                </>
              )}
            </div>
          </div>
          {bench && (
            <BenchSelectionBar
              selectedIds={selectedIds}
              onClear={clearSelected}
              onCompare={openDiff}
            />
          )}
        </div>

        {/* Diff modal — opens on selection bar's "compare →" CTA when exactly
            two rows are checked. Layered inside the overlay so it inherits
            the dialog's focus context; BenchDiff owns its own backdrop +
            stopPropagation so this wrapper stays inert. */}
        {diffOpen && bench && selectedRows.length === 2 && (
          <BenchDiff
            base={selectedRows[0]}
            target={selectedRows[1]}
            basePromptBody={
              selectedRows[0].prompt_id === selectedRows[1].prompt_id
                ? null
                : promptBodies[selectedRows[0].prompt_id] ?? null
            }
            targetPromptBody={
              selectedRows[0].prompt_id === selectedRows[1].prompt_id
                ? null
                : promptBodies[selectedRows[1].prompt_id] ?? null
            }
            fields={bench.fields}
            promptLabels={promptLabels}
            modelLabels={modelLabels}
            onClose={closeDiff}
            onPromote={(id) => { onPromote(id); closeDiff() }}
          />
        )}
      </div>
    </div>
  )
}
