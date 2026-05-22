import PanelToggle from './PanelToggle'
import UserMenu from './UserMenu'

type Props = {
  onToggleLeft: () => void
}

/**
 * Thin (52px) icon rail shown when the sidebar is collapsed. Mirrors
 * claude.ai's collapsed-sidebar pattern: panel toggle at top, identity
 * affordance at bottom. Middle is intentionally empty for now — future
 * primary actions (new project, search, etc.) land here when we wire them.
 */
export default function CollapsedRail({ onToggleLeft }: Props) {
  return (
    <div className="fs-rail">
      <div className="fs-rail-top">
        <PanelToggle
          side="left"
          hidden={true}
          onClick={onToggleLeft}
          className="fs-rail-btn"
        />
      </div>
      <div className="fs-rail-spacer" />
      <div className="fs-rail-bot">
        <UserMenu variant="rail" />
      </div>
    </div>
  )
}
