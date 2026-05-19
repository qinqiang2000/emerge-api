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
