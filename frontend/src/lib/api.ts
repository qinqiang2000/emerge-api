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
