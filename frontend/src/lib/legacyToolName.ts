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
  // Task 9 — ui_focus(target=) folds the four "point the UI at X" actions
  // (same (slug, filename, <one value>) shape, all idempotent, all browser-
  // only; ui_open_review is a different verb and stays independent).
  ui_goto_page: 'ui_focus',
  ui_set_active_field: 'ui_focus',
  ui_set_active_tab: 'ui_focus',
  ui_set_active_entity: 'ui_focus',
  // Task 10 — render_board(kind=) folds the two board renderers (same noun,
  // two media: page-image circling vs. structured-table highlighting).
  render_audit_board: 'render_board',
  render_review_board: 'render_board',
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

export type BoardKind = 'audit' | 'review'

/**
 * Which board kind a tool_call represents, for hoist dispatch AND card
 * selection (P4 Task 10 folded render_audit_board/render_review_board into
 * `render_board(kind=)`). Same posture as `scoreKindOf` (Task 7) — one
 * function that groupChatEvents.ts and MessageList.tsx both read from, so
 * they cannot drift from each other.
 *
 * Unlike `score`, `kind` has NO server-side default here — the schema marks
 * it `required` (auto-dispatching on project type would be a semantics
 * change this milestone forbids; see t_render_board). So this does NOT fall
 * back to either kind when `kind` is missing or unrecognized: a `render_board`
 * record with no `kind` is either a pre-`kind`-argument impossibility (the
 * tool never existed without it) or a validation-error record the server
 * rejected before the handler ran — in both cases there is no legend/images/
 * docs payload to render specially, so this resolves to `null` and the
 * caller falls back to the generic tool card, exactly like any other
 * unrecognized tool call.
 *
 * Legacy transcripts recorded the OLD standalone names before `kind` existed
 * as an argument at all, so for those the NAME itself is the kind signal —
 * old recorded tool_input never carries `kind`.
 */
export function boardKindOf(toolName: string, toolInput: unknown): BoardKind | null {
  const bare = bareToolName(toolName)
  if (bare === 'render_audit_board') return 'audit'
  if (bare === 'render_review_board') return 'review'
  if (bare !== 'render_board') return null
  const kind = (toolInput as { kind?: unknown } | null | undefined)?.kind
  return kind === 'audit' || kind === 'review' ? kind : null
}
