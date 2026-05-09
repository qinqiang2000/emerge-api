import type { DocSummary, PredictionPayload, ReviewedPayload } from '../types/review'

export interface Project {
  project_id: string
  name: string
  project_type: string
  active_version_id: string | null
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
