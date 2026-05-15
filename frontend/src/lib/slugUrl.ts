// URL ↔ selectedSlug helpers. Centralised so App.tsx and any future deep-link
// callers share one parser/encoder pair, and so vitest can exercise the edge
// cases (missing slug, malformed encoding, query/hash preservation) without
// touching the React tree.

/** Parse `/p/{encoded_slug}` from a pathname. Returns `null` when the path
 *  is anything else (root, deep nested, empty after `/p/`). */
export function readSlugFromPathname(pathname: string): string | null {
  const m = pathname.match(/^\/p\/([^/?#]+)/)
  if (!m) return null
  try {
    return decodeURIComponent(m[1])
  } catch {
    return null
  }
}

/** Build the canonical pathname for a selected slug (or root when null),
 *  preserving the current search + hash. Intentionally takes search/hash
 *  as arguments so callers can pass `window.location.search` etc. without
 *  this helper having to touch globals (cleaner to test). */
export function pathForSlug(slug: string | null, search: string = '', hash: string = ''): string {
  return slug ? `/p/${encodeURIComponent(slug)}${search}${hash}` : `/${search}${hash}`
}
