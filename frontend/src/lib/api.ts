import type {
  DocSummary,
  Experiment,
  ExperimentExtractPayload,
  ExperimentSummary,
  PredictionPayload,
  ReviewedPayload,
} from '../types/review'

export interface Project {
  project_id: string
  name: string
  project_type: string
  active_version_id: string | null
  status?: 'live' | 'draft' | 'empty'
}

const API = '' // same origin via vite proxy

export async function listProjects(): Promise<Project[]> {
  const r = await fetch(`${API}/lab/projects`)
  if (!r.ok) throw new Error(`listProjects ${r.status}`)
  return r.json()
}

export async function uploadDoc(projectId: string, file: File): Promise<{ doc_id: string }> {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${API}/lab/projects/${projectId}/upload`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error(`upload ${r.status}`)
  return r.json()
}

export async function listProjectDocs(projectId: string): Promise<DocSummary[]> {
  const r = await fetch(`/lab/projects/${projectId}/docs`)
  if (!r.ok) throw new Error(`listProjectDocs ${r.status}`)
  return r.json()
}

export async function getPrediction(projectId: string, docId: string): Promise<PredictionPayload | null> {
  const r = await fetch(`/lab/projects/${projectId}/predictions/${docId}`)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getPrediction ${r.status}`)
  return r.json()
}

export async function getReviewed(projectId: string, docId: string): Promise<ReviewedPayload | null> {
  const r = await fetch(`/lab/projects/${projectId}/reviewed/${docId}`)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getReviewed ${r.status}`)
  return r.json()
}

export async function saveReviewed(
  projectId: string,
  docId: string,
  payload: ReviewedPayload,
): Promise<void> {
  const r = await fetch(`/lab/projects/${projectId}/reviewed/${docId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(`saveReviewed ${r.status}`)
}

export function pdfPageUrl(projectId: string, docId: string, page: number): string {
  return `/lab/projects/${projectId}/docs/${docId}/pages/${page}`
}

export async function startJob(projectId: string, params: Record<string, unknown> = {}): Promise<{ job_id: string }> {
  const r = await fetch('/lab/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skill: 'autoresearch', project_id: projectId, params }),
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

export async function acceptCandidate(projectId: string, jobId: string, turn: number): Promise<{ ok: boolean }> {
  const r = await fetch(`/lab/projects/${projectId}/schema/accept-candidate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, turn }),
  })
  if (!r.ok) throw new Error(`acceptCandidate ${r.status}`)
  return r.json()
}

export function jobEventsUrl(projectId: string, jobId: string): string {
  return `/lab/jobs/${jobId}/events?project_id=${encodeURIComponent(projectId)}`
}

export function exportBundleUrl(projectId: string, version?: number): string {
  const base = `/lab/projects/${encodeURIComponent(projectId)}/export`
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

export async function getLatestEval(projectId: string): Promise<EvalSnapshot | null> {
  const r = await fetch(`/lab/projects/${projectId}/evals/latest`)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getLatestEval ${r.status}`)
  return r.json()
}

// Raw chat JSONL log for hydration on project entry. Permissive by design —
// any failure (bad ids, network, parse) degrades to "empty chat", never throws
// into a render.
export async function getChatEvents(projectId: string, chatId: string): Promise<unknown[]> {
  try {
    const r = await fetch(`/lab/chats/${projectId}/${chatId}`)
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

export interface ChatSummary {
  chat_id: string
  label: string
  kind: string
  ts_iso: string
  n_events: number
}

// Chat list for the conv-header history popover. Permissive — any failure
// degrades to an empty list, never throws into a render.
export async function getChatList(projectId: string): Promise<ChatSummary[]> {
  try {
    const r = await fetch(`/lab/chats/${projectId}`)
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
  projectId: string,
  opts?: { includeArchived?: boolean },
): Promise<ExperimentSummary[]> {
  const q = opts?.includeArchived ? '?include_archived=true' : ''
  const r = await fetch(`/lab/projects/${projectId}/experiments${q}`, {})
  if (!r.ok) throw new Error(`listExperiments ${r.status}`)
  return r.json()
}

export async function getExperiment(
  projectId: string,
  experimentId: string,
): Promise<Experiment> {
  const r = await fetch(`/lab/projects/${projectId}/experiments/${experimentId}`)
  if (!r.ok) throw new Error(`getExperiment ${r.status}`)
  return r.json()
}

export async function getExperimentExtract(
  projectId: string,
  experimentId: string,
  docId: string,
): Promise<ExperimentExtractPayload | null> {
  const r = await fetch(
    `/lab/projects/${projectId}/experiments/${experimentId}/extracts/${docId}`,
  )
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getExperimentExtract ${r.status}`)
  return r.json()
}

export async function runExperimentExtract(
  projectId: string,
  experimentId: string,
  docId: string,
): Promise<ExperimentExtractPayload> {
  const r = await fetch(
    `/lab/projects/${projectId}/experiments/${experimentId}/extracts/${docId}`,
    { method: 'POST' },
  )
  if (!r.ok) throw new Error(`runExperimentExtract ${r.status}`)
  return r.json()
}
