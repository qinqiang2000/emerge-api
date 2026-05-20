import { useEffect, useMemo, useState } from 'react'

import { evalMatrixCsvUrl } from '../../lib/api'
import { pathForEvalCompare, pathForSlug } from '../../lib/slugUrl'
import { useEval } from '../../stores/eval'
import { useReview } from '../../stores/review'
import { useSchema } from '../../stores/schema'
import type { CellVerdict } from '../../types/eval'
import CellDrilldown from './CellDrilldown'
import MatrixGrid from './MatrixGrid'
import { type MatrixFilter, pct } from './filters'


function flattenFieldNames(fields: Array<{ name: string | null }>): string[] {
  return fields.map((f) => f.name ?? '').filter(Boolean)
}


interface Props {
  slug: string
  ts: string
}


export default function EvalMatrixPage({ slug, ts }: Props) {
  const summary = useEval((s) => s.summary[`${slug}|${ts}`])
  const cells = useEval((s) => s.cells[`${slug}|${ts}`])
  const list = useEval((s) => s.list[slug])
  const loadSummary = useEval((s) => s.loadSummary)
  const loadCells = useEval((s) => s.loadCells)
  const loadList = useEval((s) => s.loadList)
  const schemaFields = useSchema((s) => s.byProject[slug])
  const loadSchema = useSchema((s) => s.load)

  useEffect(() => {
    loadSummary(slug, ts)
    loadCells(slug, ts)
    loadList(slug)
    if (!schemaFields) loadSchema(slug)
  }, [slug, ts, loadSummary, loadCells, loadList, loadSchema, schemaFields])

  const [filter, setFilter] = useState<MatrixFilter>('errors_only')
  const [drilldown, setDrilldown] = useState<CellVerdict | null>(null)

  const fields = useMemo(() => flattenFieldNames(schemaFields ?? []), [schemaFields])

  const onCellClick = (c: CellVerdict) => setDrilldown(c)

  const onOpenReview = () => {
    if (!drilldown) return
    useReview.getState().open(slug, drilldown.filename)
    useReview.setState({ activeField: drilldown.field })
    window.history.pushState(null, '', pathForSlug(slug))
    setDrilldown(null)
  }

  // Compare-link target: latest ts that isn't this one (if any).
  const compareTargetA = useMemo(() => {
    if (!list || list.length === 0) return null
    const other = list.find((row) => row.ts !== ts)
    return other?.ts ?? null
  }, [list, ts])

  return (
    <div className="min-h-screen bg-paper text-ink p-6">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <a
            href={pathForSlug(slug)}
            className="text-ink-3 hover:text-ink-2 text-sm"
          >
            ← {slug}
          </a>
          <h1 className="text-xl font-semibold mt-1">eval · {ts}</h1>
        </div>
        <div className="flex items-center gap-4 text-sm">
          {summary && (
            <>
              <span>
                文档准确率 <strong>{pct(summary.doc_accuracy)}</strong>
              </span>
              <span className="text-ink-3">
                macro F1 {summary.macro_f1.toFixed(2)}
              </span>
              <span className="text-ink-3">{summary.n_reviewed} docs</span>
              {summary.judge_used > 0 && (
                <span className="text-ochre">
                  LLM judged: {summary.judge_used}
                </span>
              )}
            </>
          )}
        </div>
      </header>

      <div className="mb-4 flex items-center gap-4 text-sm">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={filter === 'errors_only'}
            onChange={(e) =>
              setFilter(e.target.checked ? 'errors_only' : 'all')
            }
          />
          只看错误
        </label>
        <a
          href={evalMatrixCsvUrl(slug, ts)}
          download
          className="text-ochre hover:underline"
        >
          下载 CSV
        </a>
        {compareTargetA && (
          <a
            href={pathForEvalCompare(slug, compareTargetA, ts)}
            className="text-ochre hover:underline"
          >
            对比 {compareTargetA}
          </a>
        )}
      </div>

      {!summary && <div className="text-ink-3 text-sm">Loading…</div>}

      {cells && (
        <MatrixGrid
          cells={cells}
          fields={fields}
          filter={filter}
          onCellClick={onCellClick}
        />
      )}

      {drilldown && (
        <CellDrilldown
          slug={slug}
          cell={drilldown}
          onClose={() => setDrilldown(null)}
          onOpenReview={onOpenReview}
        />
      )}
    </div>
  )
}
