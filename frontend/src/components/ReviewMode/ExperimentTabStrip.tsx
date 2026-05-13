// Entity tab strip — inlined into ReviewBar's row.
// Auto-shows the ⭐ Active tab + every non-archived experiment.
// When tabs don't fit, the tail collapses behind a » N dropdown.
//
// Overflow detection measures each tab's bounding rect against the inner
// container (whose width auto-accounts for the trigger via flex layout).
// Hidden tabs use visibility:hidden so their widths stay stable across
// re-measurements, preventing oscillation.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { ExperimentSummary } from '../../types/review'

type Props = {
  activeTabKey: 'active' | string
  availableExperiments: ExperimentSummary[]
  onSwitch: (key: 'active' | string) => void
  modelLabels: Record<string, string>
}

type TabSpec = { key: 'active' | string; label: string; title?: string }

const GAP = 4

export default function ExperimentTabStrip({
  activeTabKey,
  availableExperiments,
  onSwitch,
  modelLabels,
}: Props) {
  const tabs: TabSpec[] = [
    { key: 'active', label: '⭐ Active' },
    ...availableExperiments
      .filter((e) => e.status !== 'archived')
      .map((e) => ({
        key: e.experiment_id,
        label: e.label,
        title: `${modelLabels[e.model_id] ?? e.model_id} · ${e.prompt_id}`,
      })),
  ]

  const innerRef = useRef<HTMLDivElement>(null)
  const tabRefs = useRef<Map<string, HTMLButtonElement>>(new Map())
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set())
  const [popoverOpen, setPopoverOpen] = useState(false)

  const tabsKey = tabs.map((t) => t.key + '|' + t.label).join('::')

  useLayoutEffect(() => {
    const inner = innerRef.current
    if (!inner) return

    const update = () => {
      const innerWidth = inner.clientWidth
      // In jsdom (or before first layout), widths are 0 — bail and show all.
      if (innerWidth === 0) {
        setHiddenIds((prev) => (prev.size === 0 ? prev : new Set()))
        return
      }

      let cum = 0
      let visibleN = 0
      for (let i = 0; i < tabs.length; i++) {
        const el = tabRefs.current.get(tabs[i].key)
        if (!el) continue
        const w = el.getBoundingClientRect().width
        const next = cum + w + (i > 0 ? GAP : 0)
        if (next > innerWidth + 0.5) break
        cum = next
        visibleN = i + 1
      }
      // Always keep ⭐ Active visible (index 0).
      visibleN = Math.max(1, visibleN)

      const next = new Set(tabs.slice(visibleN).map((t) => t.key))
      setHiddenIds((prev) => {
        if (prev.size === next.size && [...prev].every((x) => next.has(x))) return prev
        return next
      })
    }

    update()
    const ro = new ResizeObserver(update)
    ro.observe(inner)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabsKey])

  // Close popover on outside click.
  useEffect(() => {
    if (!popoverOpen) return
    const onDown = (e: MouseEvent) => {
      if (!innerRef.current?.parentElement?.contains(e.target as Node)) {
        setPopoverOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [popoverOpen])

  const hidden = tabs.filter((t) => hiddenIds.has(t.key))
  const activeHidden = hidden.some((t) => t.key === activeTabKey)

  return (
    <div className="rev-tabstrip" role="tablist">
      <div className="rev-tabstrip-inner" ref={innerRef}>
        {tabs.map((t) => {
          const isClipped = hiddenIds.has(t.key)
          return (
            <button
              key={t.key}
              ref={(el) => {
                if (el) tabRefs.current.set(t.key, el)
                else tabRefs.current.delete(t.key)
              }}
              role="tab"
              aria-selected={activeTabKey === t.key}
              aria-hidden={isClipped || undefined}
              className={'rev-tab' + (activeTabKey === t.key ? ' on' : '')}
              style={isClipped ? { visibility: 'hidden', pointerEvents: 'none' } : undefined}
              tabIndex={isClipped ? -1 : 0}
              onClick={() => onSwitch(t.key)}
              title={t.title}
              type="button"
            >
              {t.label}
            </button>
          )
        })}
      </div>

      {hidden.length > 0 && (
        <div className="rev-tab-overflow">
          <button
            className={'rev-tab-overflow-trigger' + (activeHidden ? ' has-active' : '')}
            onClick={() => setPopoverOpen((o) => !o)}
            aria-label={`${hidden.length} more tab${hidden.length > 1 ? 's' : ''}`}
            type="button"
          >
            » {hidden.length}
          </button>
          {popoverOpen && (
            <div className="rev-tab-popover" role="menu">
              {hidden.map((t) => (
                <button
                  key={t.key}
                  role="menuitem"
                  className={'rev-tab-popover-item' + (activeTabKey === t.key ? ' on' : '')}
                  onClick={() => {
                    onSwitch(t.key)
                    setPopoverOpen(false)
                  }}
                  title={t.title}
                  type="button"
                >
                  {t.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
