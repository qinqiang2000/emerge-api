import { useRef, useState } from 'react'

import type { CellVerdict } from '../../types/eval'
import ChatPanel from '../Chat/ChatPanel'


interface Props {
  slug: string
  cell: CellVerdict
  onClose: () => void
  onOpenReview: () => void
}


function statusLabel(status: CellVerdict['status']): string {
  switch (status) {
    case 'correct': return '正确'
    case 'wrong': return '错误'
    case 'missing': return '漏抽'
    case 'spurious': return '多抽'
    case 'absent_both': return '双方留空'
  }
}


function verdictLabel(c: CellVerdict): string {
  if (c.verdict_source === 'exact') return '字面相等'
  if (c.verdict_source === 'normalize') {
    return c.normalizer ? `归一化命中 (${c.normalizer})` : '归一化判定'
  }
  if (c.verdict_source === 'llm_judge') return `LLM 判定 (${c.judge_model ?? ''})`
  return '存在性判定'
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
const DEFAULT_WIDTH = 480

export default function CellDrilldown({ slug: _slug, cell, onClose, onOpenReview }: Props) {
  // Width is local + ephemeral — not persisted. Per SSU, one less preference
  // for the user to manage; they can re-drag if a wider matrix needs it.
  const [width, setWidth] = useState(DEFAULT_WIDTH)
  const draggingRef = useRef(false)

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
      {/* Cell content scrolls independently from the inline composer below.
          The composer owns its own scroll region; min-h-0 + overflow-auto
          here keeps the truth/pred blocks reachable when the composer is
          tall (it can grow with focus + multiline input). */}
      <div className="flex-1 min-h-0 overflow-y-auto p-5">
        <header className="flex items-baseline justify-between mb-4">
          <h3 className="text-base font-semibold">
            {cell.filename}
          </h3>
          <button
            type="button"
            className="text-ink-3 hover:text-ink-2 text-sm"
            onClick={onClose}
          >
            关闭
          </button>
        </header>
        <div className="text-xs text-ink-3 mb-4">
          <span className="font-mono">{cell.field}</span>
          {cell.entity_idx > 0 && <span className="ml-2">· 实体 #{cell.entity_idx}</span>}
          <span className="ml-2">· {statusLabel(cell.status)}</span>
        </div>

        <section className="mb-4">
          <div className="text-xs uppercase tracking-wide text-ink-3 mb-1">正确值</div>
          <pre className="font-mono text-xs break-all whitespace-pre-wrap m-0 max-h-[40vh] overflow-auto">
            {prettyValue(cell.truth) ?? '—'}
          </pre>
        </section>

        <section className="mb-4">
          <div className="text-xs uppercase tracking-wide text-ink-3 mb-1">当前值</div>
          <pre className="font-mono text-xs break-all whitespace-pre-wrap m-0 max-h-[40vh] overflow-auto">
            {prettyValue(cell.pred) ?? '—'}
          </pre>
        </section>

        <section className="mb-4">
          <div className="text-xs uppercase tracking-wide text-ink-3 mb-1">判定依据</div>
          <div className="text-sm">
            {verdictLabel(cell)}
            {cell.judge_reason && (
              <div className="text-xs text-ink-3 mt-1">{cell.judge_reason}</div>
            )}
          </div>
        </section>

        <button
          type="button"
          className="w-full bg-paper-3 hover:bg-paper-2 text-ink text-sm py-2 rounded border border-rule"
          onClick={onOpenReview}
        >
          查看 doc →
        </button>
      </div>

      {/* Inline composer — writes to the main chat with `surface: 'eval_cell'`
          surface_context (assembled by ChatPanel.compact at submit time via
          useEvalSurface). The user's draft and the agent's reply both land
          in the main chat shell behind the modal; the drilldown only
          provides the input surface so they can ask "why is this prediction
          wrong?" without losing sight of the cell. */}
      <div className="border-t border-rule p-3 max-h-[40vh] overflow-hidden flex flex-col">
        <ChatPanel compact composerPlaceholder="问 agent…" />
      </div>
    </aside>
  )
}
