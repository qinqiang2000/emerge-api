// Experiment tab strip — inlined into ReviewBar's row.
//
// Renders every non-archived experiment as a 2-line card (model on top,
// prompt label below). There is no explicit "Active" tab — the canonical
// editable view is the default state when no experiment is selected.
// Clicking the currently-selected tab again toggles back to canonical.
//
// Overflow handling: a ResizeObserver compares each card's bounding rect
// against the inner container; clipped cards collapse behind a » N
// dropdown. Hidden tabs use visibility:hidden so their widths stay stable
// across re-measurements and avoid layout oscillation.
import { FlaskConical } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { ExperimentSummary } from '../../types/review'

type Props = {
  activeTabKey: 'active' | string
  availableExperiments: ExperimentSummary[]
  onSwitch: (key: 'active' | string) => void
  modelLabels: Record<string, string>
}

type TabSpec = {
  key: string
  model: string
  prompt: string
  title: string
}

const GAP = 4

export default function ExperimentTabStrip({
  activeTabKey,
  availableExperiments,
  onSwitch,
  modelLabels,
}: Props) {
  const tabs: TabSpec[] = availableExperiments
    .filter((e) => e.status !== 'archived')
    .map((e) => {
      const model = modelLabels[e.model_id] ?? e.model_id
      // label is "{prompt_name} × {model_label}"; strip the model suffix so
      // the prompt line is just the prompt's own name and doesn't repeat the
      // top line.
      const prompt = e.label.includes(' × ') ? e.label.split(' × ')[0] : e.label
      return {
        key: e.experiment_id,
        model,
        prompt,
        title: `${model} · ${prompt}`,
      }
    })

  const innerRef = useRef<HTMLDivElement>(null)
  const tabRefs = useRef<Map<string, HTMLButtonElement>>(new Map())
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set())
  const [popoverOpen, setPopoverOpen] = useState(false)

  // Click-to-toggle: clicking the already-selected tab returns to canonical.
  const onTabClick = (key: string) => {
    onSwitch(activeTabKey === key ? 'active' : key)
  }

  const tabsKey = tabs.map((t) => t.key + '|' + t.model + '|' + t.prompt).join('::')

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
          const isOn = activeTabKey === t.key
          return (
            <button
              key={t.key}
              ref={(el) => {
                if (el) tabRefs.current.set(t.key, el)
                else tabRefs.current.delete(t.key)
              }}
              role="tab"
              aria-selected={isOn}
              aria-hidden={isClipped || undefined}
              className={'rev-tab rev-tab-card' + (isOn ? ' on' : '')}
              style={isClipped ? { visibility: 'hidden', pointerEvents: 'none' } : undefined}
              tabIndex={isClipped ? -1 : 0}
              onClick={() => onTabClick(t.key)}
              title={isOn ? 'click again to return to editable view' : t.title}
              type="button"
            >
              <span className="rev-tab-ico" aria-hidden="true">
                <FlaskConical size={12} strokeWidth={1.6} />
              </span>
              <span className="rev-tab-text">
                <span className="rev-tab-model">{t.model}</span>
                <span className="rev-tab-prompt">{t.prompt}</span>
              </span>
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
              {hidden.map((t) => {
                const isOn = activeTabKey === t.key
                return (
                  <button
                    key={t.key}
                    role="menuitem"
                    className={'rev-tab-popover-item rev-tab-card' + (isOn ? ' on' : '')}
                    onClick={() => {
                      onTabClick(t.key)
                      setPopoverOpen(false)
                    }}
                    title={t.title}
                    type="button"
                  >
                    <span className="rev-tab-ico" aria-hidden="true">
                      <FlaskConical size={12} strokeWidth={1.6} />
                    </span>
                    <span className="rev-tab-text">
                      <span className="rev-tab-model">{t.model}</span>
                      <span className="rev-tab-prompt">{t.prompt}</span>
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
