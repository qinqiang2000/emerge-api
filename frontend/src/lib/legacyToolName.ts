/**
 * Historical chats store the tool name that was live when the turn ran — 764
 * of them across prod + local as of 2026-08-16. P4 folded several tools into
 * multi-op ones and the server no longer answers to the old names, so the
 * renderer is the only thing that can still make old transcripts legible.
 *
 * Keep in sync with `backend/app/tools/_merged.py::MERGED_TOOLS` (one entry per
 * swallowed old name). This map is RENDER-ONLY — never send these names back
 * to the server.
 */
export const LEGACY_TOOL_NAMES: Record<string, string> = {
  // filled in per family by P4 Tasks 4-11
}

const CHAT_PREFIX = 'mcp__emerge_tools__'
const SERVICE_PREFIX = 'emerge_'

/** Bare, current-generation tool name for any recorded tool_name. */
export function canonicalToolName(toolName: string): string {
  let bare = toolName
  if (bare.startsWith(CHAT_PREFIX)) bare = bare.slice(CHAT_PREFIX.length)
  else if (bare.startsWith(SERVICE_PREFIX)) bare = bare.slice(SERVICE_PREFIX.length)
  return LEGACY_TOOL_NAMES[bare] ?? bare
}
