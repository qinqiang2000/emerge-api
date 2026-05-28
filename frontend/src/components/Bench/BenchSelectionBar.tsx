// BenchSelectionBar — sticky action strip that appears when ≥1 row is
// selected in the matrix.
//
// Behavior matrix (per plan T5 spec):
//   0 selected → render nothing (return null)
//   1 selected → "compare (need 2)" disabled CTA + clear button
//   2 selected → "compare →" enabled, click → onCompare()
//   3+        → "compare (need 2)" disabled again (only 2-way diff is
//                supported per plan; multi-way is explicitly YAGNI'd)
//
// `disabled` on a <button> already swallows the click so the test
// asserting "disabled compare doesn't fire onCompare" passes via the DOM
// semantics rather than a hand-rolled guard.

import { useT } from '../../i18n'
import './Bench.css'

interface Props {
  selectedIds: Set<string>
  onClear: () => void
  onCompare: () => void
}

export default function BenchSelectionBar({ selectedIds, onClear, onCompare }: Props) {
  const t = useT()
  const n = selectedIds.size
  if (n === 0) return null

  const canCompare = n === 2

  return (
    <div className="b-selbar" role="region" aria-label="bench-selection">
      <span className="b-selbar-count">
        {t('bench.selection.count', { n })}
      </span>
      <button type="button" className="b-selbar-clear" onClick={onClear}>
        {t('bench.selection.clear')}
      </button>
      <span className="b-selbar-spacer" />
      <button
        type="button"
        className="b-selbar-btn"
        disabled={!canCompare}
        onClick={canCompare ? onCompare : undefined}
        title={canCompare
          ? t('bench.selection.compare.title.ready')
          : t('bench.selection.compare.title.needTwo')}
      >
        {canCompare ? t('bench.selection.compare') : t('bench.selection.compare_need_two')}
      </button>
    </div>
  )
}
