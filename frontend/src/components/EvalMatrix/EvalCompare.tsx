import { useEffect, useMemo } from 'react'

import { pathForEvalMatrix, pathForSlug } from '../../lib/slugUrl'
import { useEval } from '../../stores/eval'
import { useSchema } from '../../stores/schema'
import type { CellStatus, CellVerdict, FieldScoreSummary } from '../../types/eval'
import { pct } from './filters'


interface Props {
  slug: string
  a: string | null
  b: string | null
}


function cellKey(filename: string, entityIdx: number, field: string): string {
  return `${filename}|${entityIdx}|${field}`
}


function buildCellMap(cells: CellVerdict[] | undefined): Map<string, CellVerdict> {
  const m = new Map<string, CellVerdict>()
  if (!cells) return m
  for (const c of cells) {
    m.set(cellKey(c.filename, c.entity_idx, c.field), c)
  }
  return m
}


function deltaClass(a: CellStatus | undefined, b: CellStatus | undefined): string {
  if (a === undefined || b === undefined) return 'bg-paper-2'
  const aOk = a === 'correct' || a === 'absent_both'
  const bOk = b === 'correct' || b === 'absent_both'
  if (aOk && bOk) return 'bg-moss-soft'
  if (!aOk && !bOk) return 'bg-rose-soft'
  if (aOk && !bOk) return 'bg-ochre-soft'
  return 'bg-paper'
}


function statusLabel(s: CellStatus | undefined): string {
  if (!s) return '—'
  if (s === 'absent_both') return '∅'
  if (s === 'correct') return '✓'
  if (s === 'wrong') return '✗'
  if (s === 'missing') return '–'
  return '+'
}


interface DeltaRow {
  field: string
  a: number | null
  b: number | null
  delta: number
}


function buildFieldDeltas(
  fieldsA: FieldScoreSummary[] | undefined,
  fieldsB: FieldScoreSummary[] | undefined,
): DeltaRow[] {
  const byA = new Map((fieldsA ?? []).map((f) => [f.field, f]))
  const byB = new Map((fieldsB ?? []).map((f) => [f.field, f]))
  const names = new Set<string>([...byA.keys(), ...byB.keys()])
  const rows: DeltaRow[] = []
  for (const n of names) {
    const a = byA.get(n)?.f1 ?? null
    const b = byB.get(n)?.f1 ?? null
    const delta = (b ?? 0) - (a ?? 0)
    rows.push({ field: n, a, b, delta })
  }
  rows.sort((x, y) => Math.abs(y.delta) - Math.abs(x.delta))
  return rows
}


export default function EvalCompare({ slug, a, b }: Props) {
  const summaryA = useEval((s) => (a ? s.summary[`${slug}|${a}`] : undefined))
  const summaryB = useEval((s) => (b ? s.summary[`${slug}|${b}`] : undefined))
  const cellsA = useEval((s) => (a ? s.cells[`${slug}|${a}`] : undefined))
  const cellsB = useEval((s) => (b ? s.cells[`${slug}|${b}`] : undefined))
  const loadSummary = useEval((s) => s.loadSummary)
  const loadCells = useEval((s) => s.loadCells)
  const schemaFields = useSchema((s) => s.byProject[slug])
  const loadSchema = useSchema((s) => s.load)

  useEffect(() => {
    if (a) {
      loadSummary(slug, a)
      loadCells(slug, a)
    }
    if (b) {
      loadSummary(slug, b)
      loadCells(slug, b)
    }
    if (!schemaFields) loadSchema(slug)
  }, [slug, a, b, loadSummary, loadCells, loadSchema, schemaFields])

  const fields = useMemo(() => {
    return (schemaFields ?? []).map((f) => f.name ?? '').filter(Boolean)
  }, [schemaFields])

  const mapA = useMemo(() => buildCellMap(cellsA), [cellsA])
  const mapB = useMemo(() => buildCellMap(cellsB), [cellsB])

  const rowKeys = useMemo(() => {
    const s = new Set<string>()
    for (const c of cellsA ?? []) s.add(`${c.filename}|${c.entity_idx}`)
    for (const c of cellsB ?? []) s.add(`${c.filename}|${c.entity_idx}`)
    return Array.from(s).sort()
  }, [cellsA, cellsB])

  const fieldDeltas = useMemo(
    () => buildFieldDeltas(summaryA?.per_field, summaryB?.per_field),
    [summaryA, summaryB],
  )

  if (!a || !b) {
    return (
      <div className="min-h-screen bg-paper text-ink p-6">
        <h1 className="text-xl font-semibold">eval compare</h1>
        <div className="text-ink-3 text-sm mt-4">
          需要 ?a=&lt;ts1&gt;&amp;b=&lt;ts2&gt; 查询参数。
        </div>
        <a className="text-ochre hover:underline" href={pathForSlug(slug)}>
          ← 返回项目
        </a>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-paper text-ink p-6">
      <header className="mb-6">
        <a href={pathForSlug(slug)} className="text-ink-3 hover:text-ink-2 text-sm">
          ← {slug}
        </a>
        <h1 className="text-xl font-semibold mt-1">eval compare</h1>
        <div className="text-sm text-ink-3 mt-1">
          <a className="font-mono hover:underline" href={pathForEvalMatrix(slug, a)}>
            A · {a}
          </a>
          {' → '}
          <a className="font-mono hover:underline" href={pathForEvalMatrix(slug, b)}>
            B · {b}
          </a>
        </div>
      </header>

      <section className="mb-6 grid grid-cols-2 gap-4">
        <div className="border border-rule rounded p-3 text-sm">
          <div className="text-xs uppercase tracking-wide text-ink-3 mb-1">A</div>
          <div>doc accuracy {pct(summaryA?.doc_accuracy)}</div>
          <div className="text-ink-3">macro F1 {summaryA?.macro_f1.toFixed(2) ?? '—'}</div>
        </div>
        <div className="border border-rule rounded p-3 text-sm">
          <div className="text-xs uppercase tracking-wide text-ink-3 mb-1">B</div>
          <div>doc accuracy {pct(summaryB?.doc_accuracy)}</div>
          <div className="text-ink-3">macro F1 {summaryB?.macro_f1.toFixed(2) ?? '—'}</div>
        </div>
      </section>

      <section className="mb-6">
        <h2 className="text-sm font-semibold mb-2">per-field 变化</h2>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-ink-3">
              <th className="text-left px-2 py-1 border-b border-rule">字段</th>
              <th className="text-right px-2 py-1 border-b border-rule">A · F1</th>
              <th className="text-right px-2 py-1 border-b border-rule">B · F1</th>
              <th className="text-right px-2 py-1 border-b border-rule">Δ</th>
            </tr>
          </thead>
          <tbody>
            {fieldDeltas.map((row) => (
              <tr key={row.field} className="border-b border-rule-soft">
                <td className="px-2 py-1 font-mono text-xs">{row.field}</td>
                <td className="px-2 py-1 text-right font-mono text-xs">
                  {row.a == null ? '—' : row.a.toFixed(2)}
                </td>
                <td className="px-2 py-1 text-right font-mono text-xs">
                  {row.b == null ? '—' : row.b.toFixed(2)}
                </td>
                <td
                  className={`px-2 py-1 text-right font-mono text-xs ${
                    row.delta > 0 ? 'text-moss' : row.delta < 0 ? 'text-rose' : 'text-ink-3'
                  }`}
                >
                  {row.delta > 0 ? '+' : ''}
                  {row.delta.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2 className="text-sm font-semibold mb-2">cell-level diff</h2>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-ink-3 bg-paper-2">
              <th className="text-left px-3 py-2 border-b border-rule sticky left-0 bg-paper-2">
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
            {rowKeys.map((k) => {
              const [filename, entityStr] = k.split('|')
              const entity = parseInt(entityStr, 10)
              const label = entity > 0 ? `${filename} · #${entity}` : filename
              return (
                <tr key={k} className="border-b border-rule-soft">
                  <td className="px-3 py-2 sticky left-0 bg-paper font-mono text-xs">
                    {label}
                  </td>
                  {fields.map((f) => {
                    const ca = mapA.get(cellKey(filename, entity, f))
                    const cb = mapB.get(cellKey(filename, entity, f))
                    return (
                      <td
                        key={f}
                        className={`px-3 py-2 font-mono text-xs ${deltaClass(ca?.status, cb?.status)}`}
                      >
                        {statusLabel(ca?.status)} / {statusLabel(cb?.status)}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>
    </div>
  )
}
