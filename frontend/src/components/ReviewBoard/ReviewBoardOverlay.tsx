// ReviewBoardOverlay — the review board (`?reviewboard=1`), a light shell (NOT
// excalidraw — it never touches the heavy `Board/` chunk). Left: a fixed-width
// doc list; right: a single `<iframe srcDoc>` rendering the selected doc's
// self-contained HTML (backend-authored, inlined CSS + light/dark). The
// frontend never parses that HTML.
//
// Lifecycle mirrors BoardOverlay/BenchOverlay: App.tsx mounts this when
// `?reviewboard=1` is in the URL AND a project is selected; presence of the
// param IS the open state. `onClose` lets App.tsx strip the param. ESC + the
// close button funnel into `onClose`; `hidden` cedes layout + keyboard while a
// higher overlay layers on top (display:none keeps state mounted).

import { PanelLeftClose, PanelLeftOpen, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { useT } from '../../i18n'
import { useReviewBoard } from '../../stores/reviewBoard'

// Verdict → colored dot class (semantic tokens only — repo red line: no bare
// Tailwind color classes). Mirrors AuditCard's STATUS_GLYPH intent.
const VERDICT_DOT: Record<'pass' | 'fail' | 'unclear', string> = {
  pass: 'bg-moss',
  fail: 'bg-rose',
  unclear: 'bg-ink-4',
}

// Left doc-list collapse — same vocabulary as the audit BoardOverlay's rail
// (persist to localStorage, toggle with the PanelLeft icons). Simpler here:
// the list has no drag-resize, just shown ↔ a narrow strip with verdict dots.
const RAIL_COLLAPSED_KEY = 'emerge.reviewBoardRailCollapsed'

function readStoredCollapsed(): boolean {
  try { return localStorage.getItem(RAIL_COLLAPSED_KEY) === '1' } catch { return false }
}

interface Props {
  slug: string
  hidden?: boolean
  onClose: () => void
}

export default function ReviewBoardOverlay({ slug, onClose, hidden = false }: Props) {
  const entry = useReviewBoard(s => s.byProject[slug])
  const loading = useReviewBoard(s => !!s.loading[slug])
  const error = useReviewBoard(s => s.errors[slug])
  const load = useReviewBoard(s => s.load)
  const t = useT()

  // Coalesce the doc list in a memo (selector discipline: never `?? []` /
  // `.map` inside the store selector).
  const docs = useMemo(() => entry?.docs ?? [], [entry])

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<boolean>(readStoredCollapsed)

  const toggleCollapsed = useCallback(() => {
    setCollapsed(prev => {
      const next = !prev
      try { localStorage.setItem(RAIL_COLLAPSED_KEY, next ? '1' : '0') } catch { /* ignore */ }
      return next
    })
  }, [])

  // Cache-first load. The store dedupes concurrent loads per slug.
  useEffect(() => {
    void load(slug)
  }, [slug, load])

  // Keep selection valid: default to docs[0], reset when the current selection
  // falls out of the list (project switch / docs change).
  useEffect(() => {
    if (!docs.length) {
      if (selectedId !== null) setSelectedId(null)
      return
    }
    if (selectedId === null || !docs.some(d => d.id === selectedId)) {
      setSelectedId(docs[0].id)
    }
  }, [docs, selectedId])

  // ESC closes — stood down while hidden (same convention as BoardOverlay).
  useEffect(() => {
    if (hidden) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, hidden])

  const html = selectedId ? entry?.html_by_id[selectedId] : undefined

  return (
    <div
      className="fixed inset-0 z-40"
      style={{ display: hidden ? 'none' : undefined }}
      role="dialog"
      aria-label={t('reviewboard.title')}
      aria-modal="true"
      aria-hidden={hidden}
    >
      <div className="bg-paper text-ink flex flex-col w-full h-full overflow-hidden">
        {/* Header — collapse toggle + title + tally + model label + close */}
        <div className="shrink-0 flex items-center gap-3 px-4 py-2 border-b border-rule-soft font-mono text-sm">
          {entry && docs.length > 0 && (
            <button
              type="button"
              data-testid="reviewboard-collapse"
              className="p-1 rounded-sm text-ink-3 hover:text-ink hover:bg-paper-2"
              aria-label={t(collapsed ? 'reviewboard.rail.expand' : 'reviewboard.rail.collapse')}
              aria-pressed={collapsed}
              title={t(collapsed ? 'reviewboard.rail.expand' : 'reviewboard.rail.collapse')}
              onClick={toggleCollapsed}
            >
              {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          )}
          <span className="text-ink font-semibold">{t('reviewboard.title')}</span>
          {entry && (
            <>
              {entry.tally.fail > 0 && (
                <span className="text-rose text-xs">
                  {t('reviewboard.tally.fail', { n: entry.tally.fail })}
                </span>
              )}
              {entry.tally.pass > 0 && (
                <span className="text-moss text-xs">
                  {t('reviewboard.tally.pass', { n: entry.tally.pass })}
                </span>
              )}
              {entry.model_label && (
                <span className="text-ink-4 text-xs">{entry.model_label}</span>
              )}
            </>
          )}
          <button
            type="button"
            data-testid="reviewboard-close"
            className="ml-auto p-1 rounded-sm text-ink-3 hover:text-ink hover:bg-paper-2"
            aria-label={t('reviewboard.close.aria')}
            title={t('reviewboard.close')}
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>

        {error ? (
          <div data-testid="reviewboard-error" role="alert" className="m-auto font-mono text-sm text-ink-3">
            {error}
          </div>
        ) : !entry ? (
          <div data-testid="reviewboard-loading" aria-busy={loading} className="m-auto font-mono text-sm text-ink-3">
            {t('reviewboard.loading')}
          </div>
        ) : docs.length === 0 ? (
          <div data-testid="reviewboard-empty" className="m-auto font-mono text-sm text-ink-3">
            {t('reviewboard.empty')}
          </div>
        ) : (
          <div className="flex-1 min-h-0 flex">
            {/* Left doc list — collapses to a narrow dot strip (still switches
                docs), same collapse vocabulary as the audit board rail. */}
            <div
              data-testid="reviewboard-rail"
              className="shrink-0 border-r border-rule-soft overflow-y-auto font-mono text-sm"
              style={{ width: collapsed ? 44 : 240 }}
            >
              {docs.map(d => (
                <button
                  key={d.id}
                  type="button"
                  data-testid={`reviewboard-doc-${d.id}`}
                  aria-current={selectedId === d.id}
                  onClick={() => setSelectedId(d.id)}
                  title={collapsed ? `${d.id}${d.supplier ? ' · ' + d.supplier : ''}` : undefined}
                  className={`w-full text-left border-b border-rule-soft ${
                    collapsed ? 'px-0 py-2.5 flex justify-center' : 'px-3 py-2'
                  } ${selectedId === d.id ? 'bg-paper-3' : 'hover:bg-paper-2'}`}
                >
                  {collapsed ? (
                    <span
                      className={`shrink-0 w-2.5 h-2.5 rounded-full ${VERDICT_DOT[d.verdict]} ${
                        selectedId === d.id ? 'ring-2 ring-ochre-2 ring-offset-1 ring-offset-paper-3' : ''
                      }`}
                      aria-hidden="true"
                    />
                  ) : (
                    <>
                      <div className="flex items-center gap-2">
                        <span
                          className={`shrink-0 w-2 h-2 rounded-full ${VERDICT_DOT[d.verdict]}`}
                          aria-hidden="true"
                        />
                        <span className="text-ink min-w-0 truncate">{d.id}</span>
                      </div>
                      {d.supplier && (
                        <div className="pl-4 text-xs text-ink-4 truncate">{d.supplier}</div>
                      )}
                    </>
                  )}
                </button>
              ))}
            </div>

            {/* Right iframe — the backend's self-contained per-doc HTML */}
            <div className="flex-1 min-w-0">
              {html ? (
                <iframe
                  srcDoc={html}
                  title={selectedId ?? t('reviewboard.title')}
                  sandbox="allow-forms"
                  className="w-full h-full border-0"
                />
              ) : (
                <div className="m-auto font-mono text-sm text-ink-3 flex items-center justify-center h-full">
                  {t('reviewboard.loading')}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
