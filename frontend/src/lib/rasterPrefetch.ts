// frontend/src/lib/rasterPrefetch.ts
//
// Look-ahead warmer for page rasters — the single most expensive thing a doc
// switch waits on.
//
// Two costs hide behind `/pages/{n}`: the backend renders the page on demand
// the first time anyone asks (`.cache/_render/{sha}/p{n}.png`), and the PNG
// then has to travel. In a 285-doc review queue the reviewer walks the list in
// order, so both costs are perfectly predictable — and the response carries
// `Cache-Control: immutable`, so a warmed page costs zero on the real request.
//
// Deliberately an `Image()` and not `fetch()`: the decoded bitmap lands in the
// same memory cache the `<img>` will hit, so the switch skips decode too, and
// the browser gives it low priority automatically.
import { pdfPageUrl } from './api'

// URLs already warmed this session. `immutable` means a page is never worth
// fetching twice, and the set stays tiny (one entry per doc page walked past).
const warmed = new Set<string>()

export function prefetchPage(slug: string, filename: string, page: number): void {
  if (!slug || !filename || !page) return
  const url = pdfPageUrl(slug, filename, page)
  if (warmed.has(url)) return
  warmed.add(url)
  const img = new Image()
  img.decoding = 'async'
  // `low` keeps the warmer behind anything the visible page still needs.
  ;(img as HTMLImageElement & { fetchPriority?: string }).fetchPriority = 'low'
  img.src = url
}

/** Test seam — the module-level cache would otherwise leak between cases. */
export function resetPagePrefetch(): void {
  warmed.clear()
}
