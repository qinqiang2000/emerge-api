import type {
  DocSummary,
  Experiment,
  ExperimentPredictionPayload,
  ExperimentSummary,
  PendingPayload,
  PredictionPayload,
  ReviewedPayload,
} from '../types/review'

/** A project listing row. `project_id` is the immutable internal event anchor
 *  (`p_xxx`) that chat events keep referencing; `slug` is the human-readable
 *  folder name on disk and the canonical handle for every lab API call.
 *  `published_ids` is the append-only list of frozen `pub_xxx` artifacts —
 *  the latest entry is what production deploys would point at. */
export interface Project {
  project_id: string
  slug: string
  name: string
  project_type: string
  active_version_id: string | null
  published_ids?: string[]
  status?: 'live' | 'draft' | 'empty'
}

const API = '' // same origin via vite proxy

export async function listProjects(): Promise<Project[]> {
  const r = await fetch(`${API}/lab/projects`)
  if (!r.ok) throw new Error(`listProjects ${r.status}`)
  return r.json()
}

export interface UploadDocResponse {
  /** Final on-disk filename (may differ from `file.name` after dedupe — e.g.
   *  `"f (1).pdf"`). The only doc handle the frontend should hold. */
  filename: string
  ext: string
  page_count: number
  sha256: string
  uploaded_at: string
  original_name: string
}

export async function uploadDoc(slug: string, file: File): Promise<UploadDocResponse> {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${API}/lab/projects/${encodeURIComponent(slug)}/upload`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error(`upload ${r.status}`)
  return r.json()
}

/** Kind of an attached file, classified from extension + content sniff on the
 *  backend. Drives the agent's routing decision (doc → docs/, schema → ask
 *  before importing, etc.). Optional on the wire because the backend rolls
 *  out the field after the frontend can read it. */
export type AttachmentKind = 'doc' | 'schema' | 'data' | 'note'

export interface ChatAttachmentResponse {
  /** Final on-disk filename inside `chats/<chat_id>/attachments/` after
   *  dedupe. The frontend stores this on the user-bubble attachment record. */
  filename: string
  kind?: AttachmentKind
}

/** Paste/drop a file into a chat's conversational scratch (NOT into `docs/`).
 *  `docs/` is the curated sample set; entries there power eval + predictions
 *  + review-mode. To promote a chat attachment into `docs/`, the agent must
 *  call `promote_attachment_to_docs` after explicit user ack. */
export async function attachToChat(
  slug: string,
  chatId: string,
  file: File,
): Promise<ChatAttachmentResponse> {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(
    `${API}/lab/projects/${encodeURIComponent(slug)}/chats/${encodeURIComponent(chatId)}/attach`,
    { method: 'POST', body: fd },
  )
  if (!r.ok) {
    let detail = ''
    try { detail = (await r.json()).detail ?? '' } catch { /* swallow */ }
    throw new Error(detail || `attachToChat ${r.status}`)
  }
  return r.json()
}

/** Inline-renderable URL for a chat attachment (image thumbnail, PDF chip
 *  link). Returns 404 if the file was promoted to docs/ in between renders —
 *  the caller should fall back to `pdfPageUrl` once `source === 'docs'`. */
export function chatAttachmentUrl(
  slug: string,
  chatId: string,
  filename: string,
): string {
  return `/lab/projects/${encodeURIComponent(slug)}/chats/${encodeURIComponent(chatId)}/attachments/${encodeURIComponent(filename)}`
}

export interface StagedFile {
  stage_token: string
  filename: string
  ext: string
  sha256: string
  page_count: number
  size: number
  kind?: AttachmentKind
}

// Pre-project staging upload. The file is held under
// `workspace/_staging/{stage_token}/` until a chat turn claims it into a
// project. Cleanup of unclaimed staging dirs is automatic (24h TTL, applied
// on backend startup).
export async function stageUpload(file: File, signal?: AbortSignal): Promise<StagedFile> {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${API}/lab/uploads/staging`, { method: 'POST', body: fd, signal })
  if (!r.ok) {
    let detail = ''
    try { detail = (await r.json()).detail ?? '' } catch { /* swallow */ }
    throw new Error(detail || `stageUpload ${r.status}`)
  }
  return r.json()
}

export async function listProjectDocs(slug: string): Promise<DocSummary[]> {
  const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/docs`)
  if (!r.ok) throw new Error(`listProjectDocs ${r.status}`)
  return r.json()
}

export async function deleteProjectDoc(slug: string, filename: string): Promise<void> {
  const r = await fetch(
    `/lab/projects/${encodeURIComponent(slug)}/docs/by-name/${encodeURIComponent(filename)}`,
    { method: 'DELETE' },
  )
  if (!r.ok) throw new Error(`deleteProjectDoc ${r.status}`)
}

export async function getPrediction(slug: string, filename: string): Promise<PredictionPayload | null> {
  const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/predictions/${encodeURIComponent(filename)}`)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getPrediction ${r.status}`)
  return r.json()
}

export async function getReviewed(slug: string, filename: string): Promise<ReviewedPayload | null> {
  const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/reviewed/${encodeURIComponent(filename)}`)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getReviewed ${r.status}`)
  return r.json()
}

/** Pro-labeler pending draft (awaiting human boss verify). 404 → null so the
 *  caller can fall through to the prediction layer without throwing. */
export async function getPending(
  slug: string, filename: string,
): Promise<PendingPayload | null> {
  const r = await fetch(
    `/lab/projects/${encodeURIComponent(slug)}/pending/${encodeURIComponent(filename)}`,
  )
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getPending ${r.status}`)
  return r.json()
}

export async function saveReviewed(
  slug: string,
  filename: string,
  payload: ReviewedPayload,
): Promise<void> {
  const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/reviewed/${encodeURIComponent(filename)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(`saveReviewed ${r.status}`)
}

export function pdfPageUrl(slug: string, filename: string, page: number): string {
  return `/lab/projects/${encodeURIComponent(slug)}/docs/by-name/${encodeURIComponent(filename)}/pages/${page}`
}

// ── Text layer (rubberband-select + copy on the rendered PDF page) ────────
// Backend returns spans in PDF point units (top-left origin), keyed to the
// same 150dpi raster the `<img>` displays. Scanned pages return `spans: []`
// — the overlay renders nothing, the bitmap stays selectable-free.
export interface TextlayerSpan {
  bbox: [number, number, number, number]  // PDF points, [x0,y0,x1,y1]
  text: string
  font_size: number
}

export interface TextlayerPayload {
  filename: string
  page: number
  page_w: number
  page_h: number
  image_w: number
  image_h: number
  scanned: boolean
  spans: TextlayerSpan[]
}

export async function fetchTextlayer(
  slug: string,
  filename: string,
  page: number,
  signal?: AbortSignal,
): Promise<TextlayerPayload> {
  const r = await fetch(
    `/lab/projects/${encodeURIComponent(slug)}/docs/by-name/${encodeURIComponent(filename)}/textlayer?page=${page}`,
    { signal },
  )
  if (!r.ok) throw new Error(`fetchTextlayer ${r.status}`)
  return r.json()
}

// ── On-demand translation (textlayer OR vision mode, transparent to the
// caller). The overlay is a sibling of the page <img>, just above the
// transparent text layer (z-index 2). bbox is ALWAYS in PDF page units
// (top-left origin) regardless of mode — backend normalises the vision
// path's 0–1000 grid into page units before returning. See
// `backend/app/tools/translate.py`.
export interface TranslateLine {
  bbox: [number, number, number, number]  // PDF points, [x0,y0,x1,y1]
  original: string
  translated: string
}

export interface TranslatePayload {
  filename: string
  page: number
  target_lang: string
  model_id: string
  mode: 'textlayer' | 'vision'
  page_w: number
  page_h: number
  image_w: number
  image_h: number
  lines: TranslateLine[]
  input_tokens: number
  output_tokens: number
}

export async function translatePage(
  slug: string,
  filename: string,
  page: number,
  opts?: { lang?: string; force?: boolean; signal?: AbortSignal },
): Promise<TranslatePayload> {
  const lang = opts?.lang ?? 'zh'
  const force = opts?.force ? 'true' : 'false'
  const url = `/lab/projects/${encodeURIComponent(slug)}/docs/by-name/${encodeURIComponent(filename)}/translate?page=${page}&lang=${encodeURIComponent(lang)}&force=${force}`
  const r = await fetch(url, { method: 'POST', signal: opts?.signal })
  if (!r.ok) {
    let detail = `${r.status}`
    try {
      const j = await r.json()
      detail = j.detail || j.error_message_en || detail
    } catch { /* swallow */ }
    throw new Error(`translate failed: ${detail}`)
  }
  return r.json()
}

/** Correction-backlog summary that drives the review-bar focused-tune
 *  affordance. `corrected_fields` (high→low by correction count) is what the
 *  "optimize this field" button passes as the focused tune's `target_fields`;
 *  `hot_fields` (corrected ≥2×) is the subset strong enough to name in copy. */
export interface TuneSignal {
  corrections_since_tune: number
  reviewed_count: number
  by_field: { field: string; count: number }[]
  hot_fields: string[]
  corrected_fields: string[]
}

export async function getTuneSignal(slug: string): Promise<TuneSignal> {
  const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/tune-signal`)
  if (!r.ok) throw new Error(`getTuneSignal ${r.status}`)
  return r.json()
}

export async function startJob(slug: string, params: Record<string, unknown> = {}): Promise<{ job_id: string }> {
  const r = await fetch('/lab/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // The HTTP body field name `project_id` is grandfathered from the pre-slug
    // era — the value is now a slug. Agent-3 left the field name unchanged for
    // backwards compatibility; renaming it is a follow-up.
    body: JSON.stringify({ skill: 'autoresearch', project_id: slug, params }),
  })
  if (!r.ok) throw new Error(`startJob ${r.status}`)
  return r.json()
}

export async function pauseJob(jobId: string): Promise<void> {
  const r = await fetch(`/lab/jobs/${jobId}/pause`, { method: 'POST' })
  if (!r.ok) throw new Error(`pauseJob ${r.status}`)
}

export async function resumeJob(jobId: string): Promise<void> {
  const r = await fetch(`/lab/jobs/${jobId}/resume`, { method: 'POST' })
  if (!r.ok) throw new Error(`resumeJob ${r.status}`)
}

export async function cancelJob(jobId: string): Promise<void> {
  const r = await fetch(`/lab/jobs/${jobId}/cancel`, { method: 'POST' })
  if (!r.ok) throw new Error(`cancelJob ${r.status}`)
}

/** Response from accepting a candidate. Accepting mints a new prompt variant
 *  and switches active to it; `delta` is candidate macro − turn_0 baseline
 *  macro (null when baseline is unavailable). */
export interface AcceptCandidateResult {
  ok: boolean
  rationale: string
  new_prompt_id: string
  field_accuracy_macro: number
  delta: number | null
  notes_consumed?: Record<string, unknown>
}

export async function acceptCandidate(
  slug: string,
  jobId: string,
  turn: number,
): Promise<AcceptCandidateResult> {
  const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/schema/accept-candidate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, turn }),
  })
  if (!r.ok) throw new Error(`acceptCandidate ${r.status}`)
  return r.json()
}

export function jobEventsUrl(slug: string, jobId: string): string {
  // Query-string `project_id` field is grandfathered; value is now a slug.
  return `/lab/jobs/${jobId}/events?project_id=${encodeURIComponent(slug)}`
}

export function exportBundleUrl(slug: string, version?: number): string {
  const base = `/lab/projects/${encodeURIComponent(slug)}/export`
  return version ? `${base}?version=${version}` : base
}

// M12.x — accuracy-first shape. F1 family is legacy/optional; new writes
// from the backend carry `accuracy` + `correct/total/n_absent_both/
// not_applicable` and emit `null` for the F1 family.
export interface FieldScore {
  field: string
  // M12.x accuracy-first fields — optional so legacy F1-shape summaries
  // (and old test fixtures) still satisfy the type.
  accuracy?: number | null
  correct?: number
  total?: number
  n_absent_both?: number
  not_applicable?: boolean
  // Legacy F1 family — present on pre-M12.x summaries; null on new writes.
  tp?: number | null
  fp?: number | null
  fn?: number | null
  support?: number | null
  precision?: number | null
  recall?: number | null
  f1?: number | null
}

export interface EvalSnapshot {
  n_docs: number
  n_reviewed: number
  // M12.x — may be absent on legacy summaries; ContextSurface synthesizes
  // from per_field as fallback.
  field_accuracy_macro?: number | null
  macro_f1: number | null
  // M12.x.c — semantics shifted to smooth on new writes.
  doc_accuracy?: number | null
  // M12.x.c — legacy "all cells correct" view; presence ⇒ `doc_accuracy`
  // is the new smooth definition.
  doc_accuracy_strict?: number | null
  per_field: FieldScore[]
  errors: string[]
  ts: string
  schema_field_count: number
}

export async function getLatestEval(slug: string): Promise<EvalSnapshot | null> {
  const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/evals/latest`)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getLatestEval ${r.status}`)
  return r.json()
}


// M12 — dir-form eval helpers ─────────────────────────────────────────────
import type {
  CellVerdict,
  EvalListEntry,
  ScoreResultSummary,
} from '../types/eval'

export async function listEvals(slug: string): Promise<EvalListEntry[]> {
  try {
    const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/evals`)
    if (!r.ok) return []
    return (await r.json()) as EvalListEntry[]
  } catch {
    return []
  }
}

export async function getEvalSummary(
  slug: string,
  ts: string,
): Promise<ScoreResultSummary | null> {
  try {
    const r = await fetch(
      `/lab/projects/${encodeURIComponent(slug)}/eval/${encodeURIComponent(ts)}/summary.json`,
    )
    if (!r.ok) return null
    return (await r.json()) as ScoreResultSummary
  } catch {
    return null
  }
}

export async function getEvalCells(
  slug: string,
  ts: string,
): Promise<CellVerdict[]> {
  try {
    const r = await fetch(
      `/lab/projects/${encodeURIComponent(slug)}/eval/${encodeURIComponent(ts)}/cells.jsonl`,
    )
    if (!r.ok) return []
    const text = await r.text()
    return text
      .split('\n')
      .filter(Boolean)
      .map((line) => JSON.parse(line) as CellVerdict)
  } catch {
    return []
  }
}

export function evalMatrixCsvUrl(slug: string, ts: string): string {
  return `/lab/projects/${encodeURIComponent(slug)}/eval/${encodeURIComponent(ts)}/matrix.csv`
}

// Raw chat JSONL log for hydration on project entry. Permissive by design —
// any failure (bad ids, network, parse) degrades to "empty chat", never throws
// into a render.
export async function getChatEvents(slug: string, chatId: string): Promise<unknown[]> {
  try {
    const r = await fetch(`/lab/chats/${encodeURIComponent(slug)}/${chatId}`)
    if (!r.ok) {
      if (r.status !== 404) console.warn('getChatEvents failed', r.status)
      return []
    }
    const body = (await r.json()) as { events?: unknown[] }
    return body.events ?? []
  } catch (err) {
    console.warn('getChatEvents threw', err)
    return []
  }
}

// Resolve a pending SDK `can_use_tool` ask-user round-trip. The agent's chat
// turn is suspended on the backend awaiting this call; backend is idempotent
// (double-click is harmless — second call returns `{ok: false, reason:
// "unknown_or_resolved"}`). Errors are swallowed at the call site: a failed
// resolve still flips the local card to its resolved state so the user isn't
// stuck on a dead button — worst case the agent's await times out / the user
// re-tries via /resume. (Step A: no retry path; out of scope.)
export interface PermissionResolveBody {
  decision: 'approve' | 'deny'
  scope: 'once' | 'always'
  message?: string
}

export interface PermissionResolveResponse {
  ok: boolean
  reason?: string
}

export async function resolvePermission(
  chatId: string,
  requestId: string,
  body: PermissionResolveBody,
): Promise<PermissionResolveResponse> {
  const r = await fetch(
    `/lab/chats/${encodeURIComponent(chatId)}/permission/${encodeURIComponent(requestId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!r.ok) {
    return { ok: false, reason: `http_${r.status}` }
  }
  try {
    return await r.json() as PermissionResolveResponse
  } catch {
    return { ok: false, reason: 'parse_failed' }
  }
}

export interface AskUserAnswerEntry {
  question_index: number
  selected: { option_index: number; label: string }[]
}

export interface AskUserResolveBody {
  answers: AskUserAnswerEntry[]
  /** When true, the user is redirecting via the composer instead of picking
   *  an option. Backend resolves the agent's await as ``ask_user_cancelled``;
   *  the ``answers`` array can be empty. */
  cancelled?: boolean
}

export async function resolveAskUser(
  chatId: string,
  requestId: string,
  body: AskUserResolveBody,
): Promise<PermissionResolveResponse> {
  const r = await fetch(
    `/lab/chats/${encodeURIComponent(chatId)}/ask_user/${encodeURIComponent(requestId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!r.ok) {
    return { ok: false, reason: `http_${r.status}` }
  }
  try {
    return await r.json() as PermissionResolveResponse
  } catch {
    return { ok: false, reason: 'parse_failed' }
  }
}

// Truncate events.jsonl at a user line and clear the SDK session sidecar.
// `targetUserIndex` is a 0-indexed ordinal among user lines; omitted = last.
// Powers retry / edit on any user bubble. Idempotent on the server.
export async function rewindChat(
  slug: string,
  chatId: string,
  targetUserIndex?: number,
): Promise<void> {
  const qs = typeof targetUserIndex === 'number'
    ? `?target_user_index=${targetUserIndex}`
    : ''
  const r = await fetch(`/lab/chats/${encodeURIComponent(slug)}/${chatId}/rewind${qs}`, { method: 'POST' })
  if (!r.ok) throw new Error(`rewindChat ${r.status}`)
}

export interface ChatSummary {
  chat_id: string
  label: string
  kind: string
  ts_iso: string
  n_events: number
}

// Chat list for the conv-header history popover. Permissive — any failure
// degrades to an empty list, never throws into a render.
export async function getChatList(slug: string): Promise<ChatSummary[]> {
  try {
    const r = await fetch(`/lab/chats/${encodeURIComponent(slug)}`)
    if (!r.ok) {
      if (r.status !== 404) console.warn('getChatList failed', r.status)
      return []
    }
    return (await r.json()) as ChatSummary[]
  } catch (err) {
    console.warn('getChatList threw', err)
    return []
  }
}

// ── Unbound chats (Phase 2 frontend) ──────────────────────────────────────
// "Unbound" = chats that haven't been bound to a project yet. They live
// under `workspace/_chats/<cid>.*` on disk (a sibling of `_staging/`,
// filtered out of project enumeration). The frontend talks about them as
// "conversations"; the wire-level term `_chats` never leaks into UI copy.

/** A row returned by `GET /lab/chats` — shape matches the project-scoped
 *  `ChatSummary` plus `attachment_count`. Reused as the source for the
 *  empty-hero "Recent conversations" strip and the unbound-mode popover. */
export interface UnboundChatSummary extends ChatSummary {
  attachment_count: number
}

/** Mint a fresh unbound chat id on the backend. Nothing is materialised on
 *  disk yet — the first `append_event` (or `ensure_chat_meta`) creates
 *  `_chats/<cid>.*`. Caller is expected to navigate to `/c/<cid>` and let
 *  the chat-turn endpoint create the storage when the user actually
 *  sends. */
export async function createUnboundChat(): Promise<{ chat_id: string }> {
  const r = await fetch(`${API}/lab/chats`, { method: 'POST' })
  if (!r.ok) throw new Error(`createUnboundChat ${r.status}`)
  return r.json()
}

/** List unbound chats newest-first. Permissive — any failure degrades to
 *  an empty list, never throws into a render. Same posture as
 *  `getChatList`. */
export async function listUnboundChats(): Promise<UnboundChatSummary[]> {
  try {
    const r = await fetch(`${API}/lab/chats`)
    if (!r.ok) {
      if (r.status !== 404) console.warn('listUnboundChats failed', r.status)
      return []
    }
    return (await r.json()) as UnboundChatSummary[]
  } catch (err) {
    console.warn('listUnboundChats threw', err)
    return []
  }
}

/** Replay an unbound chat's event log. Mirrors `getChatEvents` for the
 *  project-scoped path. */
export async function getUnboundChatEvents(chatId: string): Promise<unknown[]> {
  try {
    const r = await fetch(`${API}/lab/chats/${encodeURIComponent(chatId)}/events`)
    if (!r.ok) {
      if (r.status !== 404) console.warn('getUnboundChatEvents failed', r.status)
      return []
    }
    const body = (await r.json()) as { events?: unknown[] }
    return body.events ?? []
  } catch (err) {
    console.warn('getUnboundChatEvents threw', err)
    return []
  }
}

/** Bind an unbound chat to a fresh project. Backend atomically relocates the
 *  jsonl + meta + attachments from `_chats/<cid>.*` under the new project's
 *  `chats/`. Returns the resulting `slug` and `project_id`. */
export async function promoteChat(
  chatId: string,
  body: { name: string; slug?: string },
): Promise<{ slug: string; project_id: string }> {
  const r = await fetch(`${API}/lab/chats/${encodeURIComponent(chatId)}/promote`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    let detail = ''
    try { detail = (await r.json()).detail ?? '' } catch { /* swallow */ }
    throw new Error(detail || `promoteChat ${r.status}`)
  }
  return r.json()
}

/** Tombstone an unbound chat. Idempotent — deleting an already-tombstoned
 *  chat returns `{ok:true, existed:false}` rather than 404. */
export async function deleteUnboundChat(chatId: string): Promise<{ ok: boolean; existed: boolean }> {
  const r = await fetch(`${API}/lab/chats/${encodeURIComponent(chatId)}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`deleteUnboundChat ${r.status}`)
  return r.json()
}

export async function listExperiments(
  slug: string,
  opts?: { includeArchived?: boolean },
): Promise<ExperimentSummary[]> {
  const q = opts?.includeArchived ? '?include_archived=true' : ''
  const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/experiments${q}`, {})
  if (!r.ok) throw new Error(`listExperiments ${r.status}`)
  return r.json()
}

export async function getExperiment(
  slug: string,
  experimentId: string,
): Promise<Experiment> {
  const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/experiments/${experimentId}`)
  if (!r.ok) throw new Error(`getExperiment ${r.status}`)
  return r.json()
}

export async function getExperimentPrediction(
  slug: string,
  experimentId: string,
  filename: string,
): Promise<ExperimentPredictionPayload | null> {
  const r = await fetch(
    `/lab/projects/${encodeURIComponent(slug)}/experiments/${experimentId}/predictions/${encodeURIComponent(filename)}`,
  )
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getExperimentPrediction ${r.status}`)
  return r.json()
}

export async function runExperimentPrediction(
  slug: string,
  experimentId: string,
  filename: string,
): Promise<ExperimentPredictionPayload> {
  const r = await fetch(
    `/lab/projects/${encodeURIComponent(slug)}/experiments/${experimentId}/predictions/${encodeURIComponent(filename)}`,
    { method: 'POST' },
  )
  if (!r.ok) throw new Error(`runExperimentPrediction ${r.status}`)
  return r.json()
}

// ── Bench (project-level prompt × model leaderboard) ──────────────────────
import type { BenchResponse } from '../types/bench'

/** Project-level bench aggregator. Pulls every non-archived experiment +
 *  the synthetic baseline (active prompt × active model anchored to the
 *  most recent `experiment_id is None` eval) and the per-(row, field)
 *  cells used by the matrix UI. Throws on non-2xx — bench is mounted from
 *  a modal, so a fetch failure should surface as an error banner rather
 *  than degrading silently to an empty matrix. */
export async function getBench(slug: string): Promise<BenchResponse> {
  const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/bench`)
  if (!r.ok) throw new Error(`getBench ${r.status}`)
  return r.json()
}

// ── Stage 2: project tree (for `@` mention) ────────────────────────────────
export interface TreeEntry {
  name: string
  kind: 'file' | 'dir'
  /** Project-root-relative POSIX path, no leading slash. */
  path: string
}

/** Browse the project workspace as a filtered file tree. `dir` is a
 *  project-relative POSIX path; `""` is the project root. Filters hide the
 *  internal-only stuff (chats, prompts, models, predictions, jobs, metrics,
 *  experiments, project.json, dotfiles, versions/_candidate).
 *
 *  When `recursive` is true, returns a flat list of every visible descendant
 *  under `dir` sorted by path (used by the `@` mention picker for Claude
 *  Code-style fuzzy matching across the whole project). */
export async function listProjectTree(slug: string, dir: string = '', recursive: boolean = false): Promise<TreeEntry[]> {
  const params: string[] = []
  if (dir) params.push(`dir=${encodeURIComponent(dir)}`)
  if (recursive) params.push('recursive=true')
  const q = params.length ? '?' + params.join('&') : ''
  const r = await fetch(`/lab/projects/${encodeURIComponent(slug)}/tree${q}`)
  if (!r.ok) throw new Error(`listProjectTree ${r.status}`)
  return r.json()
}

// ── Workspace-level API key meta (post-slug refactor) ──────────────────────
// Keys are bound to users (default user_id="default" in this stage), not to
// projects — so meta lives at the workspace root. One call is enough to know
// "is there a key, when was it minted, when was it last used".
export interface KeyMetaPayload {
  user_id: string
  key_hash_short: string | null
  key_prefix: string | null
  created_at: string | null
  last_used: string | null
}

export async function getKeysMeta(): Promise<KeyMetaPayload | null> {
  try {
    const r = await fetch('/lab/keys/meta')
    if (r.status === 404) return null
    if (!r.ok) return null
    return await r.json() as KeyMetaPayload
  } catch {
    return null
  }
}

// ── Public /v1/extract curl example ─────────────────────────────────────────
// The published endpoint is stable URL + `published_id` parameter (the
// production-deploy / lab-staging symmetry contract from the slug-transparency
// plan). A given API key works for any `pub_xxx` minted by its user.
export function sampleCurl(publishedId: string): string {
  return `# call your new endpoint
curl https://api.emerge.run/v1/extract \\
  -H "X-API-Key: $EMERGE_API_KEY" \\
  -F "published_id=${publishedId}" \\
  -F "file=@example.pdf"`
}
