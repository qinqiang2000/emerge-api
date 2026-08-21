// CompareBoardOverlay — the compare board (`?compareboard=1&a=<ts>&b=<ts>`),
// the third `render_board` kind. Even lighter than ReviewBoardOverlay: one
// comparison is ONE self-contained HTML, so there is no left rail to pick
// from — just the header and a single `<iframe srcDoc>`. The frontend never
// parses that HTML.
//
// Lifecycle mirrors ReviewBoardOverlay: AppShell mounts this when
// `?compareboard=1` plus both `a` and `b` are in the URL AND a project is
// selected. `onClose` strips the params. ESC + the close button funnel into
// `onClose`; `hidden` cedes layout + keyboard while a higher overlay layers
// on top (display:none keeps state mounted).
//
// The verdict chip is NOT cosmetic: `noise` means the gap failed the backend's
// two-threshold gate, and the UI must not present the challenger as a winner.
// That is the whole point of this board existing — a stakeholder reading a
// single number off a chat table is exactly how a run of batch noise gets
// promoted into a model switch.

import { X } from 'lucide-react'
import { useEffect } from 'react'

import { useT } from '../../i18n'
import { compareKey, useCompareBoard } from '../../stores/compareBoard'

// Semantic tokens only (repo red line: no bare Tailwind color classes).
const VERDICT_CHIP: Record<'win' | 'noise' | 'stale' | 'no_gt', string> = {
  win: 'text-moss',
  noise: 'text-ink-4',
  stale: 'text-ochre',
  no_gt: 'text-ochre',
}

interface Props {
  slug: string
  a: string
  b: string
  hidden?: boolean
  onClose: () => void
}

export default function CompareBoardOverlay({
  slug, a, b, onClose, hidden = false,
}: Props) {
  const key = compareKey(slug, a, b)
  const entry = useCompareBoard(s => s.byKey[key])
  const loading = useCompareBoard(s => !!s.loading[key])
  const error = useCompareBoard(s => s.errors[key])
  const load = useCompareBoard(s => s.load)
  const t = useT()

  // Cache-first load. The store dedupes concurrent loads per comparison key.
  useEffect(() => {
    void load(slug, a, b)
  }, [slug, a, b, load])

  // ESC closes — stood down while hidden (same convention as ReviewBoardOverlay).
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

  return (
    <div
      className="fixed inset-0 z-40"
      style={{ display: hidden ? 'none' : undefined }}
      role="dialog"
      aria-label={t('compareboard.title')}
      aria-modal="true"
      aria-hidden={hidden}
    >
      <div className="bg-paper text-ink flex flex-col w-full h-full overflow-hidden">
        {/* Header — title + the two sides + verdict chip + close */}
        <div className="shrink-0 flex items-center gap-3 px-4 py-2 border-b border-rule-soft font-mono text-sm">
          <span className="text-ink font-semibold">{t('compareboard.title')}</span>
          {entry && (
            <>
              <span className="text-ink-4 text-xs min-w-0 truncate">
                {entry.b_label} vs {entry.a_label}
              </span>
              <span
                data-testid="compareboard-verdict"
                className={`text-xs ${VERDICT_CHIP[entry.verdict] ?? 'text-ink-4'}`}
              >
                {t(`compareboard.verdict.${entry.verdict}`)}
              </span>
            </>
          )}
          <button
            type="button"
            data-testid="compareboard-close"
            className="ml-auto p-1 rounded-sm text-ink-3 hover:text-ink hover:bg-paper-2"
            aria-label={t('compareboard.close.aria')}
            title={t('compareboard.close')}
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>

        {error ? (
          <div data-testid="compareboard-error" role="alert" className="m-auto font-mono text-sm text-ink-3">
            {error}
          </div>
        ) : !entry ? (
          <div data-testid="compareboard-loading" aria-busy={loading} className="m-auto font-mono text-sm text-ink-3">
            {t('compareboard.loading')}
          </div>
        ) : (
          <div className="flex-1 min-w-0">
            <iframe
              srcDoc={entry.html}
              title={t('compareboard.title')}
              sandbox=""
              className="w-full h-full border-0"
            />
          </div>
        )}
      </div>
    </div>
  )
}
