import type { CellVerdict } from '../../types/eval'


interface Props {
  slug: string
  cell: CellVerdict
  onClose: () => void
  onOpenReview: () => void
}


function statusLabel(status: CellVerdict['status']): string {
  switch (status) {
    case 'correct': return '正确'
    case 'wrong': return '错误'
    case 'missing': return '漏抽'
    case 'spurious': return '多抽'
    case 'absent_both': return '双方留空'
  }
}


function verdictLabel(c: CellVerdict): string {
  if (c.verdict_source === 'exact') return '字面相等'
  if (c.verdict_source === 'normalize') {
    return c.normalizer ? `归一化命中 (${c.normalizer})` : '归一化判定'
  }
  if (c.verdict_source === 'llm_judge') return `LLM 判定 (${c.judge_model ?? ''})`
  return '存在性判定'
}


export default function CellDrilldown({ slug: _slug, cell, onClose, onOpenReview }: Props) {
  return (
    <aside
      className="fixed right-0 top-0 h-full w-[400px] border-l border-rule bg-paper text-ink shadow-lg p-5 overflow-y-auto z-50"
      role="dialog"
      aria-label="cell-drilldown"
    >
      <header className="flex items-baseline justify-between mb-4">
        <h3 className="text-base font-semibold">
          {cell.filename}
        </h3>
        <button
          type="button"
          className="text-ink-3 hover:text-ink-2 text-sm"
          onClick={onClose}
        >
          关闭
        </button>
      </header>
      <div className="text-xs text-ink-3 mb-4">
        <span className="font-mono">{cell.field}</span>
        {cell.entity_idx > 0 && <span className="ml-2">· 实体 #{cell.entity_idx}</span>}
        <span className="ml-2">· {statusLabel(cell.status)}</span>
      </div>

      <section className="mb-4">
        <div className="text-xs uppercase tracking-wide text-ink-3 mb-1">正确值</div>
        <div className="font-mono text-sm break-all">
          {cell.truth ?? <em className="text-ink-4">—</em>}
        </div>
      </section>

      <section className="mb-4">
        <div className="text-xs uppercase tracking-wide text-ink-3 mb-1">当前值</div>
        <div className="font-mono text-sm break-all">
          {cell.pred ?? <em className="text-ink-4">—</em>}
        </div>
      </section>

      <section className="mb-6">
        <div className="text-xs uppercase tracking-wide text-ink-3 mb-1">判定依据</div>
        <div className="text-sm">
          {verdictLabel(cell)}
          {cell.judge_reason && (
            <div className="text-xs text-ink-3 mt-1">{cell.judge_reason}</div>
          )}
        </div>
      </section>

      <button
        type="button"
        className="w-full bg-paper-3 hover:bg-paper-2 text-ink text-sm py-2 rounded border border-rule"
        onClick={onOpenReview}
      >
        查看 doc →
      </button>
    </aside>
  )
}
