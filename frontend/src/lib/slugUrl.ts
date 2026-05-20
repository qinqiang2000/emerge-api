// URL ↔ selectedSlug helpers. Centralised so App.tsx and any future deep-link
// callers share one parser/encoder pair, and so vitest can exercise the edge
// cases (missing slug, malformed encoding, query/hash preservation) without
// touching the React tree.
//
// Three address shapes coexist post Phase-2:
//   `/`             → empty hero (no project, no conversation)
//   `/p/<slug>`     → bound to a project
//   `/c/<chat_id>`  → an unbound conversation (lives under workspace/_chats/)
//
// The `/c/<cid>` parser exists so an unbound chat is bookmarkable; the
// scope-aware popover and empty-hero strip key off which of the three is
// active.

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

/** Parse `/c/{encoded_chat_id}` from a pathname. Returns `null` when the path
 *  is anything else (project route, root, empty after `/c/`). Decoding is
 *  permissive — a malformed percent-encoding yields `null` rather than
 *  throwing into the App mount effect. */
export function readChatIdFromPathname(pathname: string): string | null {
  const m = pathname.match(/^\/c\/([^/?#]+)/)
  if (!m) return null
  try {
    return decodeURIComponent(m[1])
  } catch {
    return null
  }
}

/** Build the canonical pathname for an unbound chat id, preserving search +
 *  hash. The chat id shape (`c_xxxxxxxxxxxx`) is URL-safe already; encoding
 *  is defensive so a future change of id shape (e.g. CJK labels) keeps the
 *  builder honest. */
export function pathForChatId(chatId: string | null, search: string = '', hash: string = ''): string {
  return chatId ? `/c/${encodeURIComponent(chatId)}${search}${hash}` : `/${search}${hash}`
}


// M12 — eval matrix routes ────────────────────────────────────────────────
//
// Address shapes:
//   `/projects/<slug>/eval/<ts>`       → single eval matrix
//   `/projects/<slug>/eval/latest`     → resolves to the most-recent ts
//   `/projects/<slug>/eval/compare`    → side-by-side (?a=<ts1>&b=<ts2>)


export interface EvalMatrixRoute {
  kind: 'eval'
  slug: string
  ts: string
}


export interface EvalCompareRoute {
  kind: 'compare'
  slug: string
  a: string | null
  b: string | null
}


/** Parse an eval-matrix path. Returns `null` if the path isn't an eval route. */
export function readEvalRouteFromUrl(pathname: string, search: string): EvalMatrixRoute | EvalCompareRoute | null {
  const compare = pathname.match(/^\/projects\/([^/]+)\/eval\/compare\/?$/)
  if (compare) {
    let slug: string
    try {
      slug = decodeURIComponent(compare[1])
    } catch {
      return null
    }
    const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
    return {
      kind: 'compare',
      slug,
      a: params.get('a'),
      b: params.get('b'),
    }
  }
  const m = pathname.match(/^\/projects\/([^/]+)\/eval\/([^/]+)\/?$/)
  if (!m) return null
  let slug: string
  let ts: string
  try {
    slug = decodeURIComponent(m[1])
    ts = decodeURIComponent(m[2])
  } catch {
    return null
  }
  return { kind: 'eval', slug, ts }
}


export function pathForEvalMatrix(slug: string, ts: string): string {
  return `/projects/${encodeURIComponent(slug)}/eval/${encodeURIComponent(ts)}`
}


export function pathForEvalCompare(slug: string, a?: string, b?: string): string {
  const base = `/projects/${encodeURIComponent(slug)}/eval/compare`
  const qs: string[] = []
  if (a) qs.push(`a=${encodeURIComponent(a)}`)
  if (b) qs.push(`b=${encodeURIComponent(b)}`)
  return qs.length ? `${base}?${qs.join('&')}` : base
}
