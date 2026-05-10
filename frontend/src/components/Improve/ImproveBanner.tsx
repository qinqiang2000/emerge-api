// frontend/src/components/Improve/ImproveBanner.tsx
import type { JobSlice } from '../../stores/jobs'

interface Props {
  job: JobSlice
  onOpen: () => void
}

export default function ImproveBanner({ job, onOpen }: Props) {
  // Estimate progress: use turns as proxy, cap at 100%.
  // We don't know max_turn client-side; 10 is a reasonable placeholder.
  const pct = Math.min(Math.round((job.turns.length / 10) * 100), 100)

  return (
    <div className="improvebar">
      <span className="live" />
      <span className="lab">
        <b>/improve</b> running · turn {job.turns.length}
      </span>
      <div className="progress">
        <span>{pct}%</span>
        <div className="miniseg">
          <i style={{ width: `${pct}%` }} />
        </div>
      </div>
      <button className="openbtn" onClick={onOpen}>
        open
      </button>
    </div>
  )
}
