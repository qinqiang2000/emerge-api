import { useEffect } from 'react'
import { Pause, Play, X, Check } from 'lucide-react'

import { useJob } from '../../stores/jobs'
import type { JobSlice } from '../../stores/jobs'
import { useProjects } from '../../stores/projects'

interface Props { jobId: string }

export function formatJobLine(slice: Pick<JobSlice, 'turns' | 'bestTurn'>): string {
  const { turns, bestTurn } = slice
  if (turns.length === 0) return 'starting...'
  const baseline = turns[0]?.macro_f1 ?? 0
  const best = bestTurn?.macro_f1 ?? baseline
  const bestTurnN = bestTurn?.turn ?? 0
  const delta = best - baseline
  const deltaStr = delta === 0 ? '±0.00' : `${delta > 0 ? '+' : ''}${delta.toFixed(2)}`
  return `turn ${turns.length - 1} · best f1 ${best.toFixed(2)} (turn ${bestTurnN}) · baseline ${baseline.toFixed(2)} (Δ ${deltaStr})`
}

export default function JobProgressCard({ jobId }: Props) {
  const { selectedSlug } = useProjects()
  const slice = useJob((s) => s.byId[jobId])
  const { subscribe, pause, resume, cancel, accept } = useJob()

  useEffect(() => {
    if (selectedSlug && jobId) void subscribe(selectedSlug, jobId)
  }, [selectedSlug, jobId, subscribe])

  if (!slice) return null

  const { status, turns, bestTurn, endedReason } = slice

  return (
    <div className="border-l-2 border-rule bg-paper px-3 py-2 font-mono text-xs space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-ink-4">job</span>
        <span>{jobId}</span>
        <span className="px-1 py-0.5 bg-paper-2 rounded text-[10px] uppercase">{status}</span>
        <span className="ml-auto flex items-center gap-1">
          {status === 'running' && (
            <button aria-label="pause" onClick={() => void pause(jobId)} className="p-1 hover:bg-paper-2">
              <Pause size={12} />
            </button>
          )}
          {status === 'paused' && (
            <button aria-label="resume" onClick={() => void resume(jobId)} className="p-1 hover:bg-paper-2">
              <Play size={12} />
            </button>
          )}
          {(status === 'running' || status === 'paused') && (
            <button aria-label="cancel" onClick={() => void cancel(jobId)} className="p-1 hover:bg-paper-2">
              <X size={12} />
            </button>
          )}
        </span>
      </div>
      <div className="text-ink-3">{formatJobLine(slice)}</div>
      {endedReason && (
        <div className="flex items-center gap-2 text-ink-4">
          ended ({endedReason})
          {(status === 'done' || status === 'cancelled') && bestTurn && (
            bestTurn.turn === 0 || (bestTurn.macro_f1 <= (turns[0]?.macro_f1 ?? 0)) ? (
              <span className="ml-auto text-[10px] uppercase tracking-wide text-ink-4">
                baseline still best — schema unchanged
              </span>
            ) : (
              <button
                onClick={() => void accept(jobId, bestTurn.turn)}
                className="ml-auto inline-flex items-center gap-1 px-2 py-1 bg-ochre text-paper rounded uppercase tracking-wide text-[10px]"
                aria-label="accept candidate"
              >
                <Check size={12} /> accept turn {bestTurn.turn}
              </button>
            )
          )}
        </div>
      )}
    </div>
  )
}
