// Tab strip rendered inside ReviewBar.
//
// First tab is ✏ annotation — the editable ground-truth view (label-studio
// terminology). Subsequent tabs are model/prompt predictions for comparison,
// rendered as 2-line cards (model on top, prompt below). Annotation has a
// distinct visual treatment so users always see where the editable view is.
//
// Overflow handling: a ResizeObserver compares each tab's bounding rect
// against the inner container; clipped tabs collapse behind a » N dropdown.
// The annotation tab is always pinned visible (visibleN >= 1).
import { FlaskConical, Pencil } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { ExperimentSummary } from '../../types/review'

type Props = {
  activeTabKey: 'active' | string
  availableExperiments: ExperimentSummary[]
  onSwitch: (key: 'active' | string) => void
  modelLabels: Record<string, string>
}

type TabSpec =
  | { kind: 'annotation'; key: 'active' }
  | { kind: 'prediction'; key: string; model: string; prompt: string; title: string }

const GAP = 4

export default function ExperimentTabStrip({
  activeTabKey,
  availableExperiments,
  onSwitch,
  modelLabels,
}: Props) {
  const tabs: TabSpec[] = [
    { kind: 'annotation', key: 'active' },
    ...availableExperiments
      .filter((e) => e.status !== 'archived')
      .map<TabSpec>((e) => {
        const model = modelLabels[e.model_id] ?? e.model_id
        // label is typically "{prompt_name} × {model_label}"; strip the model
        // suffix so the second line is just the prompt's own name.
        const prompt = e.label.includes(' × ') ? e.label.split(' × ')[0] : e.label
        return {
          kind: 'prediction',
          key: e.experiment_id,
          model,
          prompt,
          title: `${model} · ${prompt}`,
        }
      }),
  ]

  const innerRef = useRef<HTMLDivElement>(null)
  const tabRefs = useRef<Map<string, HTMLButtonElement>>(new Map())
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set())
  const [popoverOpen, setPopoverOpen] = useState(false)

  const tabsKey = tabs
    .map((t) => (t.kind === 'annotation' ? 'annot' : `p:${t.key}|${t.model}|${t.prompt}`))
    .join('::')

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
      // Pin the ✏ annotation tab (index 0) — it's the editable anchor.
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

  const renderTab = (t: TabSpec, isPopover = false) => {
    const isOn = activeTabKey === t.key
    const isClipped = !isPopover && hiddenIds.has(t.key)
    const commonProps = {
      role: isPopover ? 'menuitem' : 'tab',
      'aria-selected': isPopover ? undefined : isOn,
      'aria-hidden': isClipped || undefined,
      tabIndex: isClipped ? -1 : 0,
      style: isClipped ? { visibility: 'hidden' as const, pointerEvents: 'none' as const } : undefined,
      type: 'button' as const,
      onClick: () => {
        onSwitch(t.key)
        if (isPopover) setPopoverOpen(false)
      },
      ref: isPopover ? undefined : (el: HTMLButtonElement | null) => {
        if (el) tabRefs.current.set(t.key, el)
        else tabRefs.current.delete(t.key)
      },
    }
    if (t.kind === 'annotation') {
      return (
        <button
          {...commonProps}
          key={t.key}
          className={
            'rev-tab rev-tab-annotation' +
            (isOn ? ' on' : '') +
            (isPopover ? ' rev-tab-popover-item' : '')
          }
          title="✏ editable ground truth — your annotation"
        >
          <Pencil size={12} strokeWidth={1.7} aria-hidden="true" />
          <span>annotation</span>
        </button>
      )
    }
    return (
      <button
        {...commonProps}
        key={t.key}
        className={
          'rev-tab rev-tab-card' +
          (isOn ? ' on' : '') +
          (isPopover ? ' rev-tab-popover-item' : '')
        }
        title={t.title}
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
  }

  return (
    <div className="rev-tabstrip" role="tablist">
      <div className="rev-tabstrip-inner" ref={innerRef}>
        {tabs.map((t) => renderTab(t))}
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
              {hidden.map((t) => renderTab(t, true))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
