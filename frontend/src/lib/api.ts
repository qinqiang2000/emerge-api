import type {
  DocSummary,
  Experiment,
  ExperimentPredictionPayload,
  ExperimentSummary,
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

export interface ChatAttachmentResponse {
  /** Final on-disk filename inside `chats/<chat_id>/attachments/` after
   *  dedupe. The frontend stores this on the user-bubble attachment record. */
  filename: string
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

export async function acceptCandidate(slug: string, jobId: string, turn: number): Promise<{ ok: boolean }> {
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

export interface FieldScore {
  field: string
  tp: number
  fp: number
  fn: number
  support: number
  precision: number
  recall: number
  f1: number
}

export interface EvalSnapshot {
  n_docs: number
  n_reviewed: number
  macro_f1: number
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
 *  experiments, project.json, dotfiles, versions/_candidate). */
export async function listProjectTree(slug: string, dir: string = ''): Promise<TreeEntry[]> {
  const q = dir ? `?dir=${encodeURIComponent(dir)}` : ''
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
