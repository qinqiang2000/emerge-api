import type { CellVerdict } from '../../types/eval'

export type MatrixFilter = 'all' | 'errors_only'


export function rowKey(c: CellVerdict): string {
  return `${c.filename}|${c.entity_idx}`
}


export function groupCellsIntoRows(cells: CellVerdict[]): Map<string, CellVerdict[]> {
  const out = new Map<string, CellVerdict[]>()
  for (const c of cells) {
    const k = rowKey(c)
    const list = out.get(k)
    if (list) list.push(c)
    else out.set(k, [c])
  }
  return out
}


export function applyFilter(
  cells: CellVerdict[],
  filter: MatrixFilter,
): Map<string, CellVerdict[]> {
  const grouped = groupCellsIntoRows(cells)
  if (filter === 'all') return grouped
  // errors_only: drop rows where every cell is correct or absent_both.
  const filtered = new Map<string, CellVerdict[]>()
  for (const [k, cs] of grouped.entries()) {
    const hasError = cs.some(
      (c) => c.status === 'wrong' || c.status === 'missing' || c.status === 'spurious',
    )
    if (hasError) filtered.set(k, cs)
  }
  return filtered
}


export function pct(value: number | null | undefined): string {
  if (value == null) return '—'
  return `${(value * 100).toFixed(1)}%`
}
