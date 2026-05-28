// BenchHeadline — the big score callout at the top of the bench body.
//
// Renders the best (prompt × model) row's score as a one-decimal percentage
// and the alphabetically chained chips that identify which combination won.
// On the right, a counts strip surfaces totals (experiments, prompts ×
// models, reviewed docs). Inputs are pre-resolved labels rather than the raw
// id strings so the headline can render before the rail data round-trips.
//
// Score formatting: `0.912` → `91.2` (we never render trailing zeros that
// look like `91.20%`). `null` → em-dash so we don't flash a misleading
// "0.0%" before the first eval finishes.

import { useT } from '../../i18n'
import './Bench.css'

interface Props {
  bestScore: number | null
  bestPromptLabel: string | null
  bestModelLabel: string | null
  experimentCount: number
  promptCount: number
  modelCount: number
  reviewedCount: number
}

function fmtPct(score: number): string {
  return (score * 100).toFixed(1)
}

export default function BenchHeadline({
  bestScore,
  bestPromptLabel,
  bestModelLabel,
  experimentCount,
  promptCount,
  modelCount,
  reviewedCount,
}: Props) {
  const t = useT()
  return (
    <div className="b-headline">
      <div className="b-headline-best">
        <span className="b-headline-h">{t('bench.headline.best')}</span>
        <span className="b-headline-pct" data-testid="bench-headline-score">
          {bestScore == null ? (
            t('bench.headline.score.none')
          ) : (
            <>
              {fmtPct(bestScore)}
              <span className="b-pct-sm">%</span>
            </>
          )}
        </span>
        {bestPromptLabel && bestModelLabel && (
          <span className="b-headline-by">
            <span className="b-axis-chip prompt small">{bestPromptLabel}</span>
            <span className="b-headline-x">×</span>
            <span className="b-axis-chip model small">{bestModelLabel}</span>
          </span>
        )}
      </div>
      <div className="b-headline-counts">
        <span>
          {experimentCount === 1
            ? t('bench.headline.experiments.one')
            : t('bench.headline.experiments.many', { n: experimentCount })}
        </span>
        <span className="b-h-sep">·</span>
        <span>{t('bench.headline.prompts_models', { p: promptCount, m: modelCount })}</span>
        <span className="b-h-sep">·</span>
        <span>{t('bench.headline.reviewed', { n: reviewedCount })}</span>
      </div>
    </div>
  )
}
