/**
 * Source-grounding location for one extracted field value.
 *
 * `rects` carry PDF-point bbox units — exactly the same unit the textlayer /
 * translate render layers already consume — so the render layer can reuse the
 * `(x0/pageW)*100%` formula verbatim (see BBoxRect).
 *
 * RED LINE: these rects only ever live in the render layer. `locate` is a
 * render-only HTTP endpoint, never an @tool, so coordinates never enter any
 * agent / extract / labeler / proposer context.
 */
export interface FieldLocation {
  entity_index: number
  path: string
  rects: number[][]
  page: number | null
  status: 'exact' | 'fuzzy' | 'normalized' | 'quote' | 'none'
  score: number
}

const API_BASE = ''

/**
 * POST the currently-displayed tab's entities + evidence to the locate endpoint
 * and resolve each field value back to source rects.
 *
 * locate is an enhancement, never load-bearing: any failure (404 doc_not_found,
 * network, bad envelope) resolves to `[]` so review never crashes. The page
 * hint comes from the evidence body, not a query param, so we pass no `page`.
 */
/**
 * A single field's evidence value on the wire — either the legacy page-integer
 * form, or the new {page, source} object from field-source-grounding (2026-05-29).
 */
export type EvidenceValue = number | null | { page?: number | null; source?: string | null }

/**
 * Extract the page hint from either evidence shape.
 * Returns null when the value is absent, unresolvable, or from a derived field.
 */
export function evidencePageOf(v: EvidenceValue | undefined): number | null {
  if (v == null) return null
  if (typeof v === 'number') return v
  if (typeof v === 'object') return (v as { page?: number | null }).page ?? null
  return null
}

/**
 * POST to the grounding endpoint to resolve (and cache) per-field evidence
 * (page + verbatim source quote) for a prediction blob. This is the anchor the
 * high-precision locate resolver needs to disambiguate repeated values; it runs
 * a separate LLM pass server-side, cached into the blob, so it fires once.
 *
 * Like locate, grounding is best-effort: any failure resolves to `null` and the
 * caller falls back to whatever evidence it already had (often none → page-level).
 */
export async function fetchGround(
  projectId: string,
  filename: string,
  tab: '_draft' | '_pending',
  entities: Record<string, unknown>[],
): Promise<(Record<string, unknown> | null)[] | null> {
  try {
    const res = await fetch(
      `${API_BASE}/lab/projects/${encodeURIComponent(projectId)}/docs/by-name/${encodeURIComponent(
        filename,
      )}/ground`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // send the displayed entities so we ground exactly what's shown (the
        // merged `active` view may be backed by pending, not the `tab` blob).
        body: JSON.stringify({ tab, entities }),
      },
    )
    if (!res.ok) return null
    const data = (await res.json()) as { evidence?: (Record<string, unknown> | null)[] }
    return Array.isArray(data?.evidence) ? data.evidence : null
  } catch {
    return null
  }
}

/** True if any entity's evidence carries a page hint or a source quote. */
export function hasEvidenceSignal(
  evidence: (Record<string, unknown> | null)[] | null,
): boolean {
  if (!evidence) return false
  for (const entry of evidence) {
    if (!entry) continue
    for (const v of Object.values(entry)) {
      if (typeof v === 'number') return true
      if (v && typeof v === 'object') {
        const o = v as { page?: number | null; source?: string | null }
        if (o.page != null || (o.source && o.source !== '')) return true
      }
    }
  }
  return false
}

/**
 * One verbatim quote's location, keyed by the input index of the quote
 * (mirrors backend `QuoteLocation`). Same units / same red line as
 * `FieldLocation`: rects are PDF points (raster px for jpg/png docs) and only
 * ever live in the render layer — locate-quotes is a render-only HTTP route,
 * never an @tool.
 */
export interface QuoteLocationResult {
  index: number
  rects: number[][]
  page: number | null
  status: 'exact' | 'fuzzy' | 'normalized' | 'quote' | 'none'
  score: number
}

/**
 * POST a batch of verbatim quotes (audit evidence) against one doc and resolve
 * them to page rects. `page` per quote is an optional hint — searched first,
 * a miss falls back to a whole-doc scan server-side. Best-effort like
 * `fetchLocate`: any failure (doc_not_found, network, bad envelope) resolves
 * to `[]` so the board degrades to badges instead of crashing.
 */
export async function fetchLocateQuotes(
  projectId: string,
  filename: string,
  quotes: { page?: number | null; quote: string }[],
): Promise<QuoteLocationResult[]> {
  try {
    const res = await fetch(
      `${API_BASE}/lab/projects/${encodeURIComponent(projectId)}/docs/by-name/${encodeURIComponent(
        filename,
      )}/locate-quotes`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quotes }),
      },
    )
    if (!res.ok) return []
    const data = (await res.json()) as QuoteLocationResult[]
    return Array.isArray(data) ? data : []
  } catch {
    return []
  }
}

export async function fetchLocate(
  projectId: string,
  filename: string,
  entities: Record<string, unknown>[],
  evidence: (Record<string, unknown> | null)[] | null,
  lang = 'zh',
): Promise<FieldLocation[]> {
  try {
    const res = await fetch(
      `${API_BASE}/lab/projects/${encodeURIComponent(projectId)}/docs/by-name/${encodeURIComponent(
        filename,
      )}/locate?lang=${encodeURIComponent(lang)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entities, evidence }),
      },
    )
    if (!res.ok) {
      // graceful: swallow doc_not_found / bad_request and fall back to page-level
      return []
    }
    const data = (await res.json()) as FieldLocation[]
    return Array.isArray(data) ? data : []
  } catch {
    // network / parse failure — never propagate; locate is best-effort
    return []
  }
}
