// frontend/src/components/Shell/PanelToggle.tsx
//
// Single source of truth for left/right panel toggle buttons.
//
// Used by:
//   - FSSpine (header collapse, side="left", state="visible")
//   - ContextSurface (header collapse, side="right", state="visible")
//   - ReviewBar (inline expand button, state="hidden")
//   - App floating overlay (state="hidden", outside review mode)
//
// Icon set: lucide-react PanelLeft{Open,Close} / PanelRight{Open,Close}.
// The two icons are visually paired (matched stroke + viewbox), so a single
// component swap by `hidden` flag keeps the chrome consistent.
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export type PanelSide = 'left' | 'right'

type Props = {
  side: PanelSide
  /** true → show the "Open" icon (panel is currently hidden, click to reveal).
   *  false → show the "Close" icon (panel is currently visible, click to hide). */
  hidden: boolean
  onClick: () => void
  className?: string
  /** Pixel size for the icon. Default 16. */
  size?: number
  /** Override the auto-generated title; otherwise we synthesize from side+hidden. */
  title?: string
  /** Override the auto-generated aria-label. */
  ariaLabel?: string
}

const ICONS: Record<PanelSide, { open: LucideIcon; close: LucideIcon }> = {
  left:  { open: PanelLeftOpen,  close: PanelLeftClose  },
  right: { open: PanelRightOpen, close: PanelRightClose },
}

const DEFAULT_LABELS: Record<PanelSide, { show: string; hide: string; key: string }> = {
  left:  { show: 'Show projects',  hide: 'Hide projects',  key: '⌘.'  },
  right: { show: 'Show context',   hide: 'Hide context',   key: '⌘⇧.' },
}

export default function PanelToggle({
  side,
  hidden,
  onClick,
  className,
  size = 16,
  title,
  ariaLabel,
}: Props) {
  const Icon = hidden ? ICONS[side].open : ICONS[side].close
  const labels = DEFAULT_LABELS[side]
  const action = hidden ? labels.show : labels.hide
  const resolvedTitle = title ?? `${action} (${labels.key})`
  const resolvedAria  = ariaLabel ?? action
  return (
    <button
      type="button"
      className={className}
      onClick={onClick}
      title={resolvedTitle}
      aria-label={resolvedAria}
    >
      <Icon size={size} strokeWidth={1.5} />
    </button>
  )
}
