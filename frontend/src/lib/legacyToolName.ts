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
  // Task 7 — score(kind=) folds the three scoring verbs (same noun, same
  // policy, compatible input shapes: slug[, use_llm_judge]).
  score_audit: 'score',
  score_match: 'score',
  // Task 8 — control_job(action=) folds pause/resume/cancel_job (byte-
  // identical (job_id) schemas, all idempotent).
  pause_job: 'control_job',
  resume_job: 'control_job',
  cancel_job: 'control_job',
}

const CHAT_PREFIX = 'mcp__emerge_tools__'
const SERVICE_PREFIX = 'emerge_'

function bareToolName(toolName: string): string {
  if (toolName.startsWith(CHAT_PREFIX)) return toolName.slice(CHAT_PREFIX.length)
  if (toolName.startsWith(SERVICE_PREFIX)) return toolName.slice(SERVICE_PREFIX.length)
  return toolName
}

/** Bare, current-generation tool name for any recorded tool_name. */
export function canonicalToolName(toolName: string): string {
  const bare = bareToolName(toolName)
  return LEGACY_TOOL_NAMES[bare] ?? bare
}

export type ScoreKind = 'extract' | 'audit' | 'match'

/**
 * Which score kind a tool_call represents, for card-selection AND hoist
 * dispatch (P4 Task 7 folded score_audit/score_match into `score(kind=)`).
 * Mirrors the server's own default exactly — `args.get("kind") or "extract"`
 * in `backend/app/tools/__init__.py::t_score` — so the frontend and backend
 * cannot drift (same posture as the `extract(experiment_id?)` merge, Task 6).
 *
 * Two frontend layers need this same answer — groupChatEvents.ts (hoist vs.
 * collapse into the ToolStack) and MessageList.tsx (which card component) —
 * so it lives here once rather than being recomputed twice and risking the
 * two go out of sync with each other.
 *
 * Legacy transcripts recorded the OLD standalone names before `kind` existed
 * as an argument at all, so for those the NAME itself is the kind signal —
 * old recorded tool_input never carries `kind`. Returns null for any
 * non-score tool call.
 */
export function scoreKindOf(toolName: string, toolInput: unknown): ScoreKind | null {
  const bare = bareToolName(toolName)
  if (bare === 'score_audit') return 'audit'
  if (bare === 'score_match') return 'match'
  if (bare !== 'score') return null
  const kind = (toolInput as { kind?: unknown } | null | undefined)?.kind
  return kind === 'audit' || kind === 'match' ? kind : 'extract'
}
