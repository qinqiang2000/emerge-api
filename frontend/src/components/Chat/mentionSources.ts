// frontend/src/components/Chat/mentionSources.ts
//
// Registry of `@`-mentionable resource kinds for the chat composer.
//
// The mention menu surfaces three categories. Two are built into the Composer
// because they have bespoke addressing/lifecycle:
//   - **files** — a hierarchical, lazily-fetched, cached tree (`/tree?dir=…`);
//   - **projects** — global cross-project nav, addressed by bare `@<slug>`.
// Everything else is a *flat list of named, pid-scoped resources* (models now;
// versions / experiments / metrics next). Those are homogeneous, so they share
// one shape here: a `ResourceSource` descriptor + a `MentionCandidate[]`
// builder. Adding a kind = one entry below + one store-hook line in Composer,
// with zero changes to the menu or keyboard handling.
import { Sparkles, type LucideIcon } from 'lucide-react'

import type { ModelRow } from '../../stores/models'

/** A single pickable row produced by a resource source. `insert` is the text
 *  placed after the leading `@` (no trailing space); the composer wraps it as
 *  `@<insert> ` on pick. */
export interface MentionCandidate {
  /** Stable React/activeIdx key — the resource's internal id. */
  key: string
  /** Primary label shown in the row (the semantic name, never a hash id). */
  display: string
  /** Optional right-aligned hint (e.g. provider). */
  sublabel?: string
  /** Post-`@` token, path-style `<scope>/<id>` — mirrors the spine + filesystem. */
  insert: string
}

/** Static descriptor for a pid-scoped resource kind. */
export interface ResourceSource {
  kind: string
  /** Group header in the menu (lowercase noun, matches the `projects` label). */
  label: string
  icon: LucideIcon
  /** Addressing segment. `@<scope>/<id>` drills into this source; the same
   *  candidates also fan out at the root for cross-kind fuzzy search. */
  scope: string
}

export const MODELS_SOURCE: ResourceSource = {
  kind: 'model',
  label: 'models',
  icon: Sparkles,
  scope: 'models',
}

/** All registered resource sources, in menu display order. */
export const RESOURCE_SOURCES: ResourceSource[] = [MODELS_SOURCE]

/** Build model candidates from loaded store rows. Models are addressed by
 *  `provider_model_id` — the semantic name the user and the spine both see —
 *  never the internal `model_id` hash. */
export function modelCandidates(rows: ModelRow[]): MentionCandidate[] {
  return rows.map((r) => ({
    key: r.model_id,
    display: r.provider_model_id,
    sublabel: r.provider,
    insert: `${MODELS_SOURCE.scope}/${r.provider_model_id}`,
  }))
}

/** Case-insensitive substring filter on the candidate display label. */
export function filterCandidates(cands: MentionCandidate[], query: string): MentionCandidate[] {
  const q = query.trim().toLowerCase()
  if (!q) return cands
  return cands.filter((c) => c.display.toLowerCase().includes(q))
}
