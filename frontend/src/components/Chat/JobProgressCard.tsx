import { useEffect } from 'react'
import { Pause, Play, X, Check } from 'lucide-react'

import { useJob } from '../../stores/jobs'
import { useProjects } from '../../stores/projects'

interface Props { jobId: string }

export default function JobProgressCard({ jobId }: Props) {
  const { selectedId } = useProjects()
  const { status, turns, bestTurn, endedReason, subscribe, pause, resume, cancel, accept } = useJob()

  useEffect(() => {
    if (selectedId && jobId) void subscribe(selectedId, jobId)
  }, [selectedId, jobId, subscribe])

  return (
    <div className="border-l-2 border-accent-info bg-surface px-3 py-2 font-mono text-xs space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-fg-muted">job</span>
        <span>{jobId}</span>
        <span className="px-1 py-0.5 bg-subtle rounded text-[10px] uppercase">{status}</span>
        <span className="ml-auto flex items-center gap-1">
          {status === 'running' && (
            <button aria-label="pause" onClick={() => void pause()} className="p-1 hover:bg-subtle">
              <Pause size={12} />
            </button>
          )}
          {status === 'paused' && (
            <button aria-label="resume" onClick={() => void resume()} className="p-1 hover:bg-subtle">
              <Play size={12} />
            </button>
          )}
          {(status === 'running' || status === 'paused') && (
            <button aria-label="cancel" onClick={() => void cancel()} className="p-1 hover:bg-subtle">
              <X size={12} />
            </button>
          )}
        </span>
      </div>
      <div className="text-fg-secondary">
        {turns.length === 0 ? 'starting...' : (
          <>turn {turns.length - 1} · best f1 {(bestTurn?.macro_f1 ?? turns[0]?.macro_f1).toFixed(2)} (turn {bestTurn?.turn ?? 0})</>
        )}
      </div>
      {endedReason && (
        <div className="flex items-center gap-2 text-fg-muted">
          ended ({endedReason})
          {bestTurn && status === 'done' && bestTurn.turn === 0 && (
            <span className="ml-auto text-[10px] uppercase tracking-wide">
              baseline still best — schema unchanged
            </span>
          )}
          {bestTurn && status === 'done' && bestTurn.turn > 0 && (
            <button
              onClick={() => void accept(bestTurn.turn)}
              className="ml-auto inline-flex items-center gap-1 px-2 py-1 bg-accent-primary text-canvas rounded uppercase tracking-wide text-[10px]"
              aria-label="accept candidate"
            >
              <Check size={12} /> accept turn {bestTurn.turn}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
