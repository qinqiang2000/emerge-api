import { Download } from 'lucide-react'

import { exportBundleUrl } from '../../lib/api'

interface Props { projectId: string; activeVersionId: string | null }

export default function ExportBundleButton({ projectId, activeVersionId }: Props) {
  if (!activeVersionId) return null
  return (
    <a
      aria-label={`export ${activeVersionId} bundle`}
      href={exportBundleUrl(projectId)}
      className="p-1 hover:bg-paper-2 rounded text-ink-4 hover:text-ink transition-colors"
    >
      <Download size={12} />
    </a>
  )
}
