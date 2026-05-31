import { useEffect } from 'react'
import { Pause, Play, X, Check } from 'lucide-react'

import { useJob } from '../../stores/jobs'
import type { JobSlice } from '../../stores/jobs'
import { useProjects } from '../../stores/projects'
import { t as tImperative, useT } from '../../i18n'
import type { TurnEvent, FieldScoreSummary } from '../../types/job'

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

function fieldScore(f: FieldScoreSummary): number {
  if (typeof f.accuracy === 'number') return f.accuracy
  if (typeof f.f1 === 'number') return f.f1
  return 0
}

/** Field names whose per-field accuracy moved up from baseline (turn_0) to the
 *  best candidate turn — the human-legible "what got better" surface. */
function improvedFields(baseline: TurnEvent | undefined, best: TurnEvent): string[] {
  const base: Record<string, number> = {}
  for (const f of baseline?.per_field ?? []) base[f.field] = fieldScore(f)
  const out: string[] = []
  for (const f of best.per_field ?? []) {
    const before = base[f.field]
    if (before === undefined) continue
    if (fieldScore(f) - before > 0.001) out.push(f.field)
  }
  return out
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

  const { status, turns, bestTurn, endedReason, accepting, accepted } = slice

  // A genuine improvement candidate (best turn beats baseline) — gates both the
  // pre-accept Δ block and the accept button.
  const hasCandidate =
    !!bestTurn && bestTurn.turn !== 0 && turnScore(bestTurn) > turnScore(turns[0])
  const baselineScore = turnScore(turns[0])
  const bestScore = bestTurn ? turnScore(bestTurn) : baselineScore
  const delta = bestScore - baselineScore
  const fields = hasCandidate && bestTurn ? improvedFields(turns[0], bestTurn) : []

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

      {/* Candidate decision aid: Δ vs baseline + which fields moved (or the
          proposer's rationale as a fallback). Only shown once a real
          improvement candidate exists and before it's accepted. */}
      {hasCandidate && !accepted && (
        <div className="space-y-0.5 text-ink-3">
          <div className="text-moss">
            {t('job.candidate.delta', {
              delta: delta.toFixed(2),
              best: bestScore.toFixed(2),
              baseline: baselineScore.toFixed(2),
            })}
          </div>
          {fields.length > 0 ? (
            <div className="text-ink-4">{t('job.candidate.fields', { fields: fields.join(', ') })}</div>
          ) : bestTurn?.rationale ? (
            <div className="text-ink-4">{t('job.candidate.rationale', { rationale: bestTurn.rationale })}</div>
          ) : null}
        </div>
      )}

      {endedReason && !accepted && (
        <div className="flex items-center gap-2 text-ink-4">
          {t('job.ended', { reason: endedReason })}
          {(status === 'done' || status === 'cancelled') && bestTurn && (
            !hasCandidate ? (
              <span className="ml-auto text-[10px] uppercase tracking-wide text-ink-4">
                {t('job.baselineBest')}
              </span>
            ) : (
              <button
                onClick={() => void accept(jobId, bestTurn.turn)}
                disabled={accepting}
                className="ml-auto inline-flex items-center gap-1 px-2 py-1 bg-ochre text-paper rounded uppercase tracking-wide text-[10px] disabled:opacity-50"
                aria-label={t('job.accept')}
              >
                <Check size={12} /> {t('job.accept.label', { turn: bestTurn.turn })}
              </button>
            )
          )}
        </div>
      )}

      {/* Accept confirmation — inline "toast" mirroring the app's card idiom
          (no portal lib). Surfaces the minted variant + Δ and points the user
          to the Prompts tab to review or roll back. */}
      {accepted && (
        <div className="border-l-2 border-moss bg-moss-soft px-2 py-1.5 space-y-0.5">
          <div className="flex items-center gap-1 text-moss uppercase tracking-wide text-[10px]">
            <Check size={12} /> {t('job.accepted.title')}
          </div>
          <div className="text-ink-2">
            {typeof accepted.delta === 'number'
              ? t('job.accepted.deltaLine', {
                  variant: accepted.new_prompt_id,
                  delta: accepted.delta.toFixed(2),
                })
              : t('job.accepted.noDelta', { variant: accepted.new_prompt_id })}
          </div>
          <div className="text-ink-4">{t('job.accepted.hint')}</div>
        </div>
      )}
    </div>
  )
}
