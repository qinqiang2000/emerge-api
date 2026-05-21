import { useCallback, useEffect, useState } from 'react'
import { Maximize2, Minimize2, X } from 'lucide-react'

import { pathForSlug } from '../../lib/slugUrl'
import EvalMatrixBody from './EvalMatrixBody'


interface Props {
  slug: string
  ts: string
}


/** EvalMatrixModal — full-viewport overlay that hosts <EvalMatrixBody>.
 *
 *  M-modal — the matrix used to be a standalone route (`/projects/<slug>/eval/<ts>`)
 *  which unmounted the chat shell on every open. That destroyed the chat
 *  composer draft + focus + scroll. Now we render on top of the persistent
 *  shell via `?eval=<ts>` so the composer stays mounted underneath.
 *
 *  Close behaviors: X click, ESC key, click on backdrop (NOT inside card).
 *  All three drop the `?eval=` param via pushState + popstate, so back-button
 *  history works naturally. */
export default function EvalMatrixModal({ slug, ts }: Props) {
  // Maximize is intentionally NOT persisted — SSU: one less preference for
  // the user to discover / unlearn. Resets per open. Toggling animates via
  // the `transition-all duration-300 ease-out` on the card classes.
  const [maximized, setMaximized] = useState(false)

  const close = useCallback(() => {
    // Pop the ?eval=<ts> param so App.tsx unmounts the modal. We use
    // pushState (not replaceState) so the browser back button can re-open the
    // matrix the way the user expects.
    window.history.pushState(null, '', pathForSlug(slug))
    window.dispatchEvent(new PopStateEvent('popstate'))
  }, [slug])

  // ESC closes the modal. We attach at the window level so the handler fires
  // regardless of focus target. CellDrilldown has no ESC handler of its own,
  // so this single hook owns ESC for both layers — the drilldown is just a
  // panel inside the body and the user's mental model is "ESC = close
  // overlay → back to chat" which works fine even when the drilldown is open
  // (the body unmounts the drilldown with the modal).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        close()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [close])

  return (
    <div
      className="fixed inset-0 z-40 backdrop-blur-sm flex items-center justify-center p-6"
      // `--ink` is hex in tokens.css so `bg-ink/30` can't decompose to rgba.
      // Inline rgba derived from --ink (#1B1A16) at 35% so the chat shell
      // behind the modal stays legibly dimmed.
      style={{ background: 'rgba(27, 26, 22, 0.35)' }}
      onClick={close}
      role="dialog"
      aria-label="eval-matrix"
      aria-modal="true"
    >
      <div
        className={
          maximized
            ? 'bg-paper text-ink rounded-none shadow-xl border border-rule flex flex-col w-screen max-w-none h-screen max-h-none overflow-hidden transition-all duration-300 ease-out'
            : 'bg-paper text-ink rounded-lg shadow-xl border border-rule flex flex-col w-full max-w-[min(1400px,95vw)] max-h-[90vh] overflow-hidden transition-all duration-300 ease-out'
        }
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal header — keep it minimal; the body emits the summary strip + */}
        {/* filter controls. */}
        <header className="flex items-center justify-between px-5 py-3 border-b border-rule bg-paper-2">
          <div className="flex items-baseline gap-3 min-w-0">
            <span className="text-ink-3 text-xs font-mono truncate">{slug}</span>
            <span className="text-ink-4">/</span>
            <h2 className="text-base font-semibold truncate">eval · {ts}</h2>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setMaximized((m) => !m)}
              aria-label={maximized ? 'Restore' : 'Maximize'}
              title={maximized ? 'Restore' : 'Maximize'}
              className="p-1.5 rounded hover:bg-paper-3 text-ink-3 hover:text-ink-2"
            >
              {maximized ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>
            <button
              type="button"
              onClick={close}
              aria-label="close"
              className="p-1.5 rounded hover:bg-paper-3 text-ink-3 hover:text-ink-2"
            >
              <X size={16} />
            </button>
          </div>
        </header>

        {/* Body scrolls; flex-1 + min-h-0 lets the inner overflow-auto take
            the remaining card height so the sticky <thead> in MatrixGrid
            actually sticks. */}
        <div className="flex-1 min-h-0 overflow-auto p-5">
          <EvalMatrixBody
            slug={slug}
            ts={ts}
            inModal
            onAfterOpenReview={close}
          />
        </div>
      </div>
    </div>
  )
}
