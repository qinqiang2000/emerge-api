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
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-paper-2 text-xs uppercase tracking-wide text-ink-3 sticky top-0">
            <th className="text-left px-3 py-2 border-b border-rule sticky left-0 bg-paper-2 z-10">
              文件
            </th>
            {fields.map((f) => (
              <th
                key={f}
                className="text-left px-3 py-2 border-b border-rule font-mono normal-case"
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
              <tr key={rowKey} className="border-b border-rule-soft">
                <td className="px-3 py-2 sticky left-0 bg-paper font-mono text-xs">
                  {label}
                </td>
                {fields.map((f) => {
                  const c = cellByField.get(f)
                  if (!c) {
                    return <td key={f} className="px-3 py-2 bg-paper-2" />
                  }
                  return (
                    <td
                      key={f}
                      className={`px-3 py-2 ${statusBgClass(c.status)} cursor-pointer hover:opacity-80`}
                      onClick={() => onCellClick(c)}
                    >
                      <div className="text-xs font-mono break-all">
                        <div className="text-ink">{c.truth ?? <em className="text-ink-4">—</em>}</div>
                        {c.pred !== c.truth && (
                          <div className="text-ink-3 mt-0.5">{c.pred ?? <em className="text-ink-4">—</em>}</div>
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
