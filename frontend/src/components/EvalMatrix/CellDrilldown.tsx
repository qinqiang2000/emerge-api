import { useEffect, useRef, useState } from 'react'

import { useChat } from '../../stores/chat'
import type { CellVerdict } from '../../types/eval'
import ChatPanel from '../Chat/ChatPanel'
import { useT } from '../../i18n'


interface Props {
  slug: string
  cell: CellVerdict
  onClose: () => void
  onOpenReview: () => void
}


function statusLabel(status: CellVerdict['status'], t: (k: string) => string): string {
  switch (status) {
    case 'correct': return t('eval.verdict.correct')
    case 'wrong': return t('eval.verdict.wrong')
    case 'missing': return t('eval.verdict.missing')
    case 'spurious': return t('eval.verdict.spurious')
    case 'absent_both': return t('eval.verdict.absentBoth')
  }
}


// Predicted-value tone follows the cell status — green when the prediction
// matched ground truth, rose when it diverged, muted when one side is empty.
// Truth is always shown in moss since it's the reference value by definition.
function predToneClass(status: CellVerdict['status']): string {
  switch (status) {
    case 'correct': return 'text-moss'
    case 'wrong': return 'text-rose'
    case 'spurious': return 'text-rose'
    case 'missing': return 'text-ink-3'
    case 'absent_both': return 'text-ink-3'
  }
}


function verdictLabel(c: CellVerdict, t: (k: string, vars?: Record<string, string | number>) => string): string {
  if (c.verdict_source === 'exact') return t('eval.source.exact')
  if (c.verdict_source === 'normalize') {
    return c.normalizer ? t('eval.source.normalizedWith', { normalizer: c.normalizer }) : t('eval.source.normalized')
  }
  if (c.verdict_source === 'llm_judge') return t('eval.source.llmJudge', { model: c.judge_model ?? '' })
  return t('eval.source.presence')
}


// M12.x — when a cell value is a JSON array/object (e.g. an `items` field),
// pretty-print so the drilldown shows readable structure instead of one long
// line. Falls back to the raw string for plain scalars.
function prettyValue(v: string | null): string | null {
  if (v == null) return null
  const trimmed = v.trimStart()
  if (!trimmed.startsWith('[') && !trimmed.startsWith('{')) return v
  try {
    const parsed = JSON.parse(v) as unknown
    if (typeof parsed === 'object' && parsed !== null) {
      return JSON.stringify(parsed, null, 2)
    }
  } catch { /* fall through */ }
  return v
}


// Width clamp for the resizable sidebar. Floor keeps the truth/pred blocks
// readable; ceiling stops a runaway drag from eating the whole modal so the
// matrix stays visible behind the drilldown.
const MIN_WIDTH = 320
const MAX_WIDTH = 1000
const DEFAULT_WIDTH = 560

export default function CellDrilldown({ slug: _slug, cell, onClose, onOpenReview }: Props) {
  const t = useT()
  // Width is local + ephemeral — not persisted. Per SSU, one less preference
  // for the user to manage; they can re-drag if a wider matrix needs it.
  const [width, setWidth] = useState(DEFAULT_WIDTH)
  const draggingRef = useRef(false)

  // History clipping: capture the chat events length when this drilldown
  // opens (and again when the user clicks into a different cell) so the
  // embedded ChatPanel shows an empty surface focused on this cell, not the
  // project's accumulated main-chat history. New turns sent from here append
  // to the shared chat as usual and become visible because they sit past the
  // captured baseline.
  const cellKey = `${cell.filename}::${cell.field}::${cell.entity_idx}`
  const [historyOffset, setHistoryOffset] = useState<number>(
    () => useChat.getState().events.length,
  )
  useEffect(() => {
    setHistoryOffset(useChat.getState().events.length)
  }, [cellKey])

  // Drag-to-resize: mousedown on the left-edge handle attaches window-level
  // listeners until mouseup. We compute width from `window.innerWidth - clientX`
  // because the sidebar is right-anchored, so dragging the handle leftward
  // grows the width. preventDefault keeps the text selection from running
  // away during the drag.
  function startResize(e: React.MouseEvent) {
    e.preventDefault()
    draggingRef.current = true
    const onMove = (ev: globalThis.MouseEvent) => {
      if (!draggingRef.current) return
      const w = window.innerWidth - ev.clientX
      setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, w)))
    }
    const onUp = () => {
      draggingRef.current = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  return (
    <aside
      className="fixed right-0 top-0 h-full border-l border-rule bg-paper text-ink shadow-lg z-50 flex flex-col"
      style={{ width: `${width}px` }}
      role="dialog"
      aria-label="cell-drilldown"
    >
      {/* Drag handle: 4px-wide strip on the left edge. Visible hover state
          via ochre tint so the affordance is discoverable; cursor switches
          to col-resize on hover. */}
      <div
        className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-ochre/40"
        onMouseDown={startResize}
        aria-hidden="true"
      />
      {/* Cell content sits on top, sized to its content with a hard ceiling
          so the chat area below always claims the rest of the panel. Without
          the ceiling a long pred JSON would still leave the composer in a
          40vh sliver; with `flex-shrink-0` + `max-h-[60%]` short cells
          collapse and let chat breathe (the common case), long cells cap
          at 60% and scroll internally. */}
      <div className="shrink-0 overflow-y-auto p-5 max-h-[60%]">
        <header className="flex items-baseline justify-between mb-4">
          <h3 className="text-base font-semibold">
            {cell.filename}
          </h3>
          <button
            type="button"
            className="text-ink-3 hover:text-ink-2 text-sm"
            onClick={onClose}
          >
            {t('eval.cell.close')}
          </button>
        </header>
        <div className="text-xs text-ink-3 mb-4">
          <span className="font-mono">{cell.field}</span>
          {cell.entity_idx > 0 && <span className="ml-2">· {t('eval.cell.entity', { idx: cell.entity_idx })}</span>}
          <span className="ml-2">· {statusLabel(cell.status, t)}</span>
        </div>

        {/* Side-by-side compare. For short scalars (the common case —
            amounts, dates, IDs) this halves the vertical real estate the
            cell card takes, leaving more room for chat below. The inner
            `min-w-0` is needed so `break-all` actually wraps inside a grid
            cell instead of pushing the column wider. */}
        <section className="mb-4 grid grid-cols-2 gap-3">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wide text-ink-3 mb-1">{t('eval.cell.truth')}</div>
            <pre className="font-mono text-xs break-all whitespace-pre-wrap m-0 max-h-[40vh] overflow-auto text-moss">
              {prettyValue(cell.truth) ?? '—'}
            </pre>
          </div>
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wide text-ink-3 mb-1">{t('eval.cell.current')}</div>
            <pre className={`font-mono text-xs break-all whitespace-pre-wrap m-0 max-h-[40vh] overflow-auto ${predToneClass(cell.status)}`}>
              {prettyValue(cell.pred) ?? '—'}
            </pre>
          </div>
        </section>

        {/* Basis line is inline: label + verdict on one row. The optional
            judge reason drops to a second row in muted small text so the
            primary verdict stays scannable. */}
        <section className="mb-4 text-sm">
          <div className="flex items-baseline gap-2">
            <span className="text-xs uppercase tracking-wide text-ink-3 shrink-0">{t('eval.cell.basis')}</span>
            <span className="min-w-0 break-words">{verdictLabel(cell, t)}</span>
          </div>
          {cell.judge_reason && (
            <div className="text-xs text-ink-3 mt-1">{cell.judge_reason}</div>
          )}
        </section>

        <button
          type="button"
          className="w-full bg-paper-3 hover:bg-paper-2 text-ink text-sm py-2 rounded border border-rule"
          onClick={onOpenReview}
        >
          {t('eval.cell.openDoc')}
        </button>
      </div>

      {/* Inline composer — writes to the main chat with `surface: 'eval_cell'`
          surface_context (assembled by ChatPanel.compact at submit time via
          useEvalSurface). The user's draft and the agent's reply both land
          in the main chat shell behind the modal; the drilldown only
          provides the input surface so they can ask "why is this prediction
          wrong?" without losing sight of the cell.

          `flex-1 min-h-0` lets this region claim every remaining pixel below
          the cell card so the conversation has room to render — the cell
          card above is the bounded one, not the chat. */}
      <div className="border-t border-rule p-3 flex-1 min-h-0 overflow-hidden flex flex-col">
        <ChatPanel
          compact
          composerPlaceholder={t('eval.askAgent.placeholder')}
          historyOffset={historyOffset}
        />
      </div>
    </aside>
  )
}
