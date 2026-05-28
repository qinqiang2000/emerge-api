// BenchTopBar — minimal header on top of the bench surface.
//
// Owns only the right-side counter ("n = N reviewed") and a close button. The
// project-level brand strip / chat-tab strip from the demo lives in the
// BenchOverlay shell (T6) so this leaf stays task-agnostic.
import { X } from 'lucide-react'

import { useT } from '../../i18n'
import './Bench.css'

interface Props {
  reviewedCount: number
  onClose: () => void
}

export default function BenchTopBar({ reviewedCount, onClose }: Props) {
  const t = useT()
  return (
    <div className="b-topbar">
      <div className="b-toprail">
        <span className="b-rail-meta">{t('bench.topbar.reviewed', { n: reviewedCount })}</span>
        <button
          type="button"
          className="b-topbar-close"
          aria-label={t('bench.topbar.close.aria')}
          title={t('bench.topbar.close')}
          onClick={onClose}
        >
          <X size={16} />
        </button>
      </div>
    </div>
  )
}
