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
