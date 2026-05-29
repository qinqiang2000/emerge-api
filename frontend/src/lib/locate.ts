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
