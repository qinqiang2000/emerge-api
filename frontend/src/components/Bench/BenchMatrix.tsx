// BenchMatrix — the experiments × schema-fields leaderboard table.
//
// Each row is one BenchRow (experiment or synthetic baseline); columns iter
// `fields` (active prompt's flat schema). Cell coloring policy mirrors the
// design demo:
//   r >= 0.9   → ok    (moss tint)
//   r >= 0.75  → mid   (ochre tint)
//   r <  0.75  → bad   (rose tint)
//   c == null  → empty (paper-2 fill, em-dash placeholder)
//
// Hover protocol: when AxisRail emits `{kind:'prompt', id}`, rows whose
// `prompt_id` differs gain a `.dimmed` class. Same for kind='model'.
//
// Click protocol: clicking anywhere on a data row fires `onOpenRow(row)`
// (deep-link to EvalMatrixModal via `?eval=<summary_ts>`). The checkbox
// cell and the action button both `stopPropagation` so they don't
// double-fire.

import { useT } from '../../i18n'
import type {
  BenchCell,
  BenchModelAxisItem,
  BenchPromptAxisItem,
  BenchRow,
} from '../../types/bench'
import type { AxisHovered } from './AxisRail'
import './Bench.css'

interface Props {
  rows: BenchRow[]
  fields: string[]
  prompts: BenchPromptAxisItem[]
  models: BenchModelAxisItem[]
  selectedIds: Set<string>
  hovered: AxisHovered | null
  onToggleSelect: (id: string) => void
  onOpenRow: (row: BenchRow) => void
  onPromote: (id: string) => void
  onRunEval: (id: string) => void
}

function cellTint(cell: BenchCell | undefined): string {
  if (!cell) return 'b-cell-empty'
  if (cell.total === 0) return 'b-cell-empty'
  const r = cell.correct / cell.total
  if (r >= 0.9) return 'b-cell-ok'
  if (r >= 0.75) return 'b-cell-mid'
  return 'b-cell-bad'
}

function fmtDelta(d: number | null | undefined): string | null {
  if (d == null) return null
  const sign = d > 0 ? '+' : ''
  // Drop trailing zeros but keep one digit minimum (matches design demo)
  const body = d.toFixed(3).replace(/0+$/, '').replace(/\.$/, '.0')
  return sign + body
}

function indexBy<T extends { id: string }>(arr: T[]): Record<string, T> {
  const out: Record<string, T> = {}
  for (const it of arr) out[it.id] = it
  return out
}

export default function BenchMatrix({
  rows,
  fields,
  prompts,
  models,
  selectedIds,
  hovered,
  onToggleSelect,
  onOpenRow,
  onPromote,
  onRunEval,
}: Props) {
  const t = useT()
  const promptIx = indexBy(prompts)
  const modelIx = indexBy(models)

  return (
    <div className="b-matrix-wrap">
      <table className="b-matrix">
        <colgroup>
          <col style={{ width: 30 }} />
          <col style={{ width: 145 }} />
          <col style={{ width: 145 }} />
          {fields.map((f) => <col key={f} style={{ width: 88 }} />)}
          <col style={{ width: 84 }} />
          <col style={{ width: 96 }} />
        </colgroup>
        <thead>
          <tr>
            <th></th>
            <th className="b-th-axis">{t('bench.matrix.col.prompt')}</th>
            <th className="b-th-axis">{t('bench.matrix.col.model')}</th>
            {fields.map((f) => <th key={f} className="b-th-field">{f}</th>)}
            <th className="b-th-overall">{t('bench.matrix.col.overall')}</th>
            <th className="b-th-actions">{t('bench.matrix.col.action')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const p = promptIx[row.prompt_id]
            const m = modelIx[row.model_id]
            const sel = selectedIds.has(row.id)
            const dimmed = hovered != null && (
              (hovered.kind === 'prompt' && row.prompt_id !== hovered.id) ||
              (hovered.kind === 'model' && row.model_id !== hovered.id)
            )
            const rowClasses = [
              'b-row',
              row.is_active ? 'active' : '',
              sel ? 'selected' : '',
              dimmed ? 'dimmed' : '',
            ].filter(Boolean).join(' ')
            return (
              <tr
                key={row.id}
                className={rowClasses}
                onClick={() => onOpenRow(row)}
              >
                <td
                  className="b-row-pick"
                  onClick={(e) => { e.stopPropagation(); onToggleSelect(row.id) }}
                >
                  <div className={'b-pick' + (sel ? ' on' : '')}>
                    {sel && <span className="b-pick-mark">✓</span>}
                  </div>
                </td>
                <td className="b-row-prompt">
                  <span className="b-axis-chip prompt">
                    {p && p.is_active && '⭐ '}
                    {p ? p.label : row.prompt_id}
                  </span>
                </td>
                <td className="b-row-model">
                  <span className="b-axis-chip model">
                    {m && m.is_active && '⭐ '}
                    {m ? m.label : row.model_id}
                  </span>
                </td>
                {fields.map((f) => {
                  const c = row.cells[f]
                  return (
                    <td key={f} className={'b-cell ' + cellTint(c)}>
                      {c ? (
                        <>
                          <div className="b-cell-score">
                            <span className="num">{c.correct}</span>
                            <span className="den">/{c.total}</span>
                          </div>
                          <div className="b-cell-strip">
                            {c.strip.map((s, i) => (
                              <span
                                key={i}
                                className={'b-tick ' + (s === 1 ? 'ok' : s === 0 ? 'no' : '')}
                              >
                                {s === 1 ? '✓' : s === 0 ? '✗' : '·'}
                              </span>
                            ))}
                          </div>
                        </>
                      ) : (
                        <div className="b-cell-pending">{t('bench.matrix.cell.empty')}</div>
                      )}
                    </td>
                  )
                })}
                <td className="b-row-overall">
                  {row.score == null ? (
                    <span className="b-overall-pending">{t('bench.matrix.row.draft')}</span>
                  ) : (
                    <>
                      <div className="b-overall-num">
                        {(row.score * 100).toFixed(1)}<span className="b-overall-pct">%</span>
                      </div>
                      {row.delta != null && (
                        <div
                          className={'b-overall-delta ' + (row.delta > 0 ? 'up' : 'down')}
                        >
                          {fmtDelta(row.delta)}
                        </div>
                      )}
                    </>
                  )}
                </td>
                <td className="b-row-action" onClick={(e) => e.stopPropagation()}>
                  {row.is_active ? (
                    <span className="b-action-active">{t('bench.matrix.action.active')}</span>
                  ) : row.score == null ? (
                    <button
                      type="button"
                      className="b-action-run"
                      onClick={(e) => { e.stopPropagation(); onRunEval(row.id) }}
                    >
                      {t('bench.matrix.action.run_eval')}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="b-action-promote"
                      onClick={(e) => { e.stopPropagation(); onPromote(row.id) }}
                    >
                      {t('bench.matrix.action.promote')}
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
