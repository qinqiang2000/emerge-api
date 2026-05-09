import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

import { pdfPageUrl } from '../../lib/api'
import { useDocs } from '../../stores/docs'
import { useReview } from '../../stores/review'

export default function PdfViewer() {
  const { activeProjectId, activeDocId, page, pageCount, goPage, setPageCount } = useReview()
  const { byProject } = useDocs()
  const [loadError, setLoadError] = useState(false)
  const url = activeProjectId && activeDocId ? pdfPageUrl(activeProjectId, activeDocId, page) : ''

  useEffect(() => {
    if (!activeProjectId || !activeDocId) return
    const pageCountFromDoc = byProject[activeProjectId]?.find((d) => d.doc_id === activeDocId)?.page_count
    if (pageCountFromDoc) setPageCount(pageCountFromDoc)
  }, [activeProjectId, activeDocId, byProject, setPageCount])

  return (
    <div className="flex flex-col h-full bg-subtle">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-subtle bg-canvas">
        <button
          type="button"
          onClick={() => goPage(page - 1)}
          disabled={page <= 1}
          className="p-1 disabled:opacity-30 hover:bg-subtle rounded"
          aria-label="previous page"
        >
          <ChevronLeft size={16} />
        </button>
        <span className="text-xs font-mono text-fg-secondary">
          {page} / {pageCount}
        </span>
        <button
          type="button"
          onClick={() => goPage(page + 1)}
          disabled={page >= pageCount}
          className="p-1 disabled:opacity-30 hover:bg-subtle rounded"
          aria-label="next page"
        >
          <ChevronRight size={16} />
        </button>
      </div>
      <div className="flex-1 overflow-auto grid place-items-start p-4">
        {loadError ? (
          <div className="text-sm text-fg-muted">page render failed</div>
        ) : (
          <img
            src={url}
            alt={`page ${page}`}
            onError={() => setLoadError(true)}
            onLoad={() => setLoadError(false)}
            className="max-w-full shadow"
          />
        )}
      </div>
    </div>
  )
}
