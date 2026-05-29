// AxisRail — one chip per prompt (kind="prompt") or model (kind="model").
//
// Two filter modes share the same `{kind, id}` shape and are rendered through
// the matrix's dim logic:
//   - Hover  (transient): mouseenter emits `onHover`, mouseleave clears.
//   - Pinned (persistent): chip click emits `onPin` to toggle. Click again on
//     the same chip clears. Click any other chip swaps. ESC also clears
//     (handled by BenchOverlay).
//
// The parent (BenchOverlay) owns both states and computes "effective filter"
// = pinned ?? hovered. Pinned wins so user can "lock the lens" then continue
// glancing other chips for compare without losing the lock.
//
// A trailing `+ new` chip is rendered as an inert placeholder for now —
// per plan, this is a T8 follow-up (out of scope: tying it to chat NL).

import { useT } from '../../i18n'
import type { BenchAxisItem } from '../../types/bench'
import './Bench.css'

export type AxisKind = 'prompt' | 'model'

export interface AxisHovered {
  kind: AxisKind
  id: string
}

interface Props {
  kind: AxisKind
  items: BenchAxisItem[]
  hovered: AxisHovered | null
  pinned: AxisHovered | null
  onHover: (h: AxisHovered | null) => void
  onPin: (h: AxisHovered | null) => void
}

export default function AxisRail({ kind, items, hovered, pinned, onHover, onPin }: Props) {
  const t = useT()
  const headerKey = kind === 'prompt' ? 'bench.rails.prompts' : 'bench.rails.models'
  return (
    <div className="b-rail">
      <span className="b-rail-h">{t(headerKey)}</span>
      <div className="b-rail-chips">
        {items.map((it) => {
          const isHov = hovered != null && hovered.kind === kind && hovered.id === it.id
          const isPin = pinned != null && pinned.kind === kind && pinned.id === it.id
          const classes = [
            'b-chip',
            it.is_active ? 'active' : '',
            isHov ? 'hover' : '',
            isPin ? 'pinned' : '',
          ].filter(Boolean).join(' ')
          return (
            <button
              key={it.id}
              type="button"
              className={classes}
              aria-pressed={isPin}
              title={isPin
                ? t('bench.rails.chip.unpin', { label: it.label })
                : t('bench.rails.chip.pin', { label: it.label })}
              onMouseEnter={() => onHover({ kind, id: it.id })}
              onMouseLeave={() => onHover(null)}
              onClick={() => onPin(isPin ? null : { kind, id: it.id })}
            >
              {it.is_active && <span className="b-star" data-testid="axisrail-star">⭐</span>}
              <span className="b-chip-label">{it.label}</span>
              <span
                className="b-chip-refs"
                data-testid="axisrail-refs"
                title={t('bench.rails.chip.refs', { n: String(it.refs ?? 0) })}
              >·{it.refs ?? 0}</span>
            </button>
          )
        })}
        <button
          type="button"
          className="b-chip new"
          tabIndex={-1}
          disabled
          title={t('bench.rails.new.disabled')}
          aria-disabled="true"
        >
          {t('bench.rails.new')}
        </button>
      </div>
    </div>
  )
}
