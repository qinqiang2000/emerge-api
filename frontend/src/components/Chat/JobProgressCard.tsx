import { useEffect } from 'react'
import { Pause, Play, X, Check } from 'lucide-react'

import { useJob } from '../../stores/jobs'
import type { JobSlice } from '../../stores/jobs'
import { useProjects } from '../../stores/projects'
import { t as tImperative, useT } from '../../i18n'

interface Props { jobId: string }

// M12.x — turn payloads now optimize against `field_accuracy_macro`; the
// `macro_f1` key still ships (with the same value) for legacy decoder paths.
// Read the new field with fallback so transcript replays from older job
// JSONLs still render a sensible line.
function turnScore(t: { field_accuracy_macro?: number; macro_f1?: number } | null | undefined): number {
  if (!t) return 0
  if (typeof t.field_accuracy_macro === 'number') return t.field_accuracy_macro
  if (typeof t.macro_f1 === 'number') return t.macro_f1
  return 0
}

export function formatJobLine(slice: Pick<JobSlice, 'turns' | 'bestTurn'>): string {
  const { turns, bestTurn } = slice
  if (turns.length === 0) return tImperative('job.starting')
  const baseline = turnScore(turns[0])
  const best = bestTurn ? turnScore(bestTurn) : baseline
  const bestTurnN = bestTurn?.turn ?? 0
  const delta = best - baseline
  const deltaStr = delta === 0 ? '±0.00' : `${delta > 0 ? '+' : ''}${delta.toFixed(2)}`
  return tImperative('job.line', {
    turn: turns.length - 1,
    best: best.toFixed(2),
    bestTurn: bestTurnN,
    baseline: baseline.toFixed(2),
    delta: deltaStr,
  })
}

export default function JobProgressCard({ jobId }: Props) {
  const t = useT()
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
        <span className="text-ink-4">{t('job.label')}</span>
        <span>{jobId}</span>
        <span className="px-1 py-0.5 bg-paper-2 rounded text-[10px] uppercase">{status}</span>
        <span className="ml-auto flex items-center gap-1">
          {status === 'running' && (
            <button aria-label={t('job.pause')} onClick={() => void pause(jobId)} className="p-1 hover:bg-paper-2">
              <Pause size={12} />
            </button>
          )}
          {status === 'paused' && (
            <button aria-label={t('job.resume')} onClick={() => void resume(jobId)} className="p-1 hover:bg-paper-2">
              <Play size={12} />
            </button>
          )}
          {(status === 'running' || status === 'paused') && (
            <button aria-label={t('job.cancel')} onClick={() => void cancel(jobId)} className="p-1 hover:bg-paper-2">
              <X size={12} />
            </button>
          )}
        </span>
      </div>
      <div className="text-ink-3">{formatJobLine(slice)}</div>
      {endedReason && (
        <div className="flex items-center gap-2 text-ink-4">
          {t('job.ended', { reason: endedReason })}
          {(status === 'done' || status === 'cancelled') && bestTurn && (
            bestTurn.turn === 0 || (turnScore(bestTurn) <= turnScore(turns[0])) ? (
              <span className="ml-auto text-[10px] uppercase tracking-wide text-ink-4">
                {t('job.baselineBest')}
              </span>
            ) : (
              <button
                onClick={() => void accept(jobId, bestTurn.turn)}
                className="ml-auto inline-flex items-center gap-1 px-2 py-1 bg-ochre text-paper rounded uppercase tracking-wide text-[10px]"
                aria-label={t('job.accept')}
              >
                <Check size={12} /> {t('job.accept.label', { turn: bestTurn.turn })}
              </button>
            )
          )}
        </div>
      )}
    </div>
  )
}
