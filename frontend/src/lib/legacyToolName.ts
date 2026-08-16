/**
 * Historical chats store the tool name that was live when the turn ran — 764
 * of them across prod + local as of 2026-08-16. P4 folded several tools into
 * multi-op ones and the server no longer answers to the old names, so the
 * renderer is the only thing that can still make old transcripts legible.
 *
 * Keep in sync with `backend/app/tools/_merged.py::MERGED_TOOLS` (one entry per
 * swallowed old name). This map is RENDER-ONLY — never send these names back
 * to the server.
 *
 * Exception: Task 11 folded `history_log` + `history_diff` into `history(op=)`
 * with NO entry here. That family only became reachable in this same P4 pass
 * (Task 1, 2026-08-16) — no chat transcript has ever recorded either old name,
 * so there is nothing for this renderer to translate.
 */
export const LEGACY_TOOL_NAMES: Record<string, string> = {
  // Task 4 — set_model(role=) folded 4 byte-identical (slug, model_id) setters.
  set_labeler_model: 'set_model',
  set_proposer_model: 'set_model',
  set_translate_model: 'set_model',
  switch_active_model: 'set_model',
  // Task 5 — get_project_config absorbed get_labeler_config (already a
  // superset of its return shape, minus env_default — now added).
  get_labeler_config: 'get_project_config',
  // Task 6 — extract(experiment_id?) folds the two hottest tools in the
  // system (extract_one 147 calls, extract_with_experiment 53 calls); they
  // differed by exactly one optional argument.
  extract_one: 'extract',
  extract_with_experiment: 'extract',
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
