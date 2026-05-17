/**
 * Shared serializers for the prompt blob shown in QuickLook.
 *
 * The prompt form and the raw-json tab are two views of one document
 * (`{ schema, global_notes, ...meta }`). Keeping the (de)serialization
 * here avoids drift between them and lets the form's blur-commit and
 * the editor's save-button funnel through the same string layout.
 */
import type { SchemaField } from '../stores/schema'

/**
 * Reorder keys so `global_notes` sits immediately above `schema`. The
 * server may return them in any order, but humans skim better when notes
 * (often the most-edited surface) appears next to the field array.
 */
export function hoistGlobalNotes(obj: unknown): unknown {
  if (typeof obj !== 'object' || obj === null || Array.isArray(obj)) return obj
  const rec = obj as Record<string, unknown>
  if (!('schema' in rec) || !('global_notes' in rec)) return rec
  const result: Record<string, unknown> = {}
  for (const key of Object.keys(rec)) {
    if (key === 'global_notes') continue
    if (key === 'schema') result['global_notes'] = rec['global_notes']
    result[key] = rec[key]
  }
  return result
}

/**
 * Recursively drop keys whose value is null. After the SchemaField redesign
 * each field carries four optional attrs (`format / enum / properties / items`)
 * that are null for most types — keeping them produces noisy raw JSON. Empty
 * strings and `false` are kept (semantic), only literal nulls go.
 */
function stripNulls(value: unknown): unknown {
  if (value === null) return undefined
  if (Array.isArray(value)) return value.map(stripNulls).filter(v => v !== undefined)
  if (typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      const cleaned = stripNulls(v)
      if (cleaned !== undefined) out[k] = cleaned
    }
    return out
  }
  return value
}

export function serializePrompt(prompt: unknown): string {
  return JSON.stringify(stripNulls(hoistGlobalNotes(prompt)), null, 2)
}

export interface ParsedPrompt {
  /** The parsed root object (preserves extra keys so save can spread them back). */
  root: Record<string, unknown>
  schema: SchemaField[]
  global_notes: string
}

export type ParseResult =
  | { ok: true; value: ParsedPrompt }
  | { ok: false; error: string }

/**
 * Parse + shape-check raw-json buffer. Caller saves only `schema` and
 * `global_notes` (the existing PUT endpoint only writes those two), but
 * we surface the full root so callers can preserve unknown keys if they
 * ever need to.
 */
export function parsePromptJson(text: string): ParseResult {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (e) {
    return { ok: false, error: (e as Error).message }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, error: 'root must be a JSON object' }
  }
  const rec = parsed as Record<string, unknown>
  if (!Array.isArray(rec.schema)) {
    return { ok: false, error: '`schema` must be an array' }
  }
  if (typeof rec.global_notes !== 'string') {
    return { ok: false, error: '`global_notes` must be a string' }
  }
  return {
    ok: true,
    value: {
      root: rec,
      schema: rec.schema as SchemaField[],
      global_notes: rec.global_notes,
    },
  }
}
