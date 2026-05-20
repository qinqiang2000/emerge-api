import { useMemo } from 'react'

import type { CellVerdict } from '../../types/eval'
import { applyFilter, groupCellsIntoRows, type MatrixFilter } from './filters'


interface Props {
  cells: CellVerdict[]
  fields: string[]
  filter: MatrixFilter
  onCellClick: (cell: CellVerdict) => void
}


function statusBgClass(status: CellVerdict['status']): string {
  switch (status) {
    case 'correct': return 'bg-moss-soft'
    case 'wrong': return 'bg-rose-soft'
    case 'missing': return 'bg-ochre-soft'
    case 'spurious': return 'bg-ochre-soft'
    case 'absent_both': return 'bg-paper-2'
  }
}


// M12.x — truncation helpers for the matrix UI.
//
// Real dogfood (默沙东_小票) had `items` cells holding 50+-row JSON arrays.
// Without truncation the row height explodes and the whole matrix becomes
// unreadable. We render up to MAX_LINES (~6) of content per cell; the user
// clicks through to the CellDrilldown (already wired by EvalMatrixPage) for
// the full content.
const MAX_LINES = 6

function isJsonArrayLike(v: string): { isArr: true; len: number } | { isArr: false } {
  // Cheap probe — avoid JSON.parse for non-array strings.
  const trimmed = v.trimStart()
  if (!trimmed.startsWith('[')) return { isArr: false }
  try {
    const parsed = JSON.parse(v)
    if (Array.isArray(parsed)) return { isArr: true, len: parsed.length }
  } catch {
    // fall through
  }
  return { isArr: false }
}

function truncateForCell(v: string | null): { display: string; truncated: boolean; suffix?: string } {
  if (v == null) return { display: '', truncated: false }
  // Special-case JSON arrays so users see `… (n total)` not just `…`.
  const probe = isJsonArrayLike(v)
  if (probe.isArr && probe.len > MAX_LINES) {
    // Show first MAX_LINES "items" rendered as pretty JSON, then ellipsis.
    try {
      const parsed = JSON.parse(v) as unknown[]
      const head = parsed.slice(0, MAX_LINES)
      const pretty = JSON.stringify(head, null, 2)
      return {
        display: pretty,
        truncated: true,
        suffix: `… (${probe.len} total)`,
      }
    } catch {
      // fallback to plain truncate
    }
  }
  const lines = v.split('\n')
  if (lines.length <= MAX_LINES && v.length <= 240) {
    return { display: v, truncated: false }
  }
  const head = lines.slice(0, MAX_LINES).join('\n')
  const display = head.length > 240 ? `${head.slice(0, 240)}` : head
  return { display, truncated: true }
}


export default function MatrixGrid({ cells, fields, filter, onCellClick }: Props) {
  const rows = useMemo(() => applyFilter(cells, filter), [cells, filter])
  // Total rows for "empty-state" message (errors-only with all correct).
  const totalRows = useMemo(() => groupCellsIntoRows(cells).size, [cells])

  if (rows.size === 0) {
    return (
      <div className="p-8 text-center text-ink-3 text-sm">
        {filter === 'errors_only' && totalRows > 0
          ? '没有错误 — 全部命中'
          : '尚无评测数据'}
      </div>
    )
  }

  const sortedKeys = Array.from(rows.keys()).sort()

  return (
    <div className="overflow-auto">
      {/* M12.x — table-layout:fixed pins column widths so any single cell
          can't push the entire row wider. Combined with cell `max-height`
          + overflow:hidden, this keeps the page readable when one cell
          carries a 50-row JSON array. */}
      <table
        className="text-sm border-collapse"
        style={{ tableLayout: 'fixed', minWidth: '100%' }}
      >
        <colgroup>
          {/* Filename column: ~14ch (filename + hash) sticky-left. */}
          <col style={{ width: '14ch' }} />
          {/* Value columns: uniform 18ch min so headers + values stay tight. */}
          {fields.map((f) => (
            <col key={f} style={{ width: '18ch' }} />
          ))}
        </colgroup>
        <thead>
          <tr className="bg-paper-2 text-xs uppercase tracking-wide text-ink-3 sticky top-0">
            <th className="text-left px-3 py-2 border-b border-rule sticky left-0 bg-paper-2 z-10">
              文件
            </th>
            {fields.map((f) => (
              <th
                key={f}
                className="text-left px-3 py-2 border-b border-rule font-mono normal-case truncate"
                title={f}
              >
                {f}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedKeys.map((rowKey) => {
            const rowCells = rows.get(rowKey)!
            const cellByField = new Map(rowCells.map((c) => [c.field, c]))
            const first = rowCells[0]
            const label = first.entity_idx > 0
              ? `${first.filename} · #${first.entity_idx}`
              : first.filename
            return (
              <tr key={rowKey} className="border-b border-rule-soft align-top">
                <td
                  className="px-3 py-2 sticky left-0 bg-paper font-mono text-xs truncate"
                  title={label}
                >
                  {label}
                </td>
                {fields.map((f) => {
                  const c = cellByField.get(f)
                  if (!c) {
                    return <td key={f} className="px-3 py-2 bg-paper-2" />
                  }
                  const truth = truncateForCell(c.truth)
                  const pred =
                    c.pred !== c.truth ? truncateForCell(c.pred) : null
                  return (
                    <td
                      key={f}
                      className={`px-3 py-2 ${statusBgClass(c.status)} cursor-pointer hover:opacity-80 align-top`}
                      onClick={() => onCellClick(c)}
                      title="click to see full content"
                    >
                      <div
                        className="text-xs font-mono whitespace-pre-wrap break-all"
                        style={{
                          maxHeight: '96px',
                          overflow: 'hidden',
                        }}
                      >
                        <div className="text-ink">
                          {c.truth == null ? (
                            <em className="text-ink-4">—</em>
                          ) : (
                            <>
                              {truth.display}
                              {truth.truncated && (
                                <span className="text-ink-4">
                                  {truth.suffix ? ` ${truth.suffix}` : ' …'}
                                </span>
                              )}
                            </>
                          )}
                        </div>
                        {pred != null && (
                          <div className="text-ink-3 mt-0.5">
                            {c.pred == null ? (
                              <em className="text-ink-4">—</em>
                            ) : (
                              <>
                                {pred.display}
                                {pred.truncated && (
                                  <span className="text-ink-4">
                                    {pred.suffix ? ` ${pred.suffix}` : ' …'}
                                  </span>
                                )}
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
