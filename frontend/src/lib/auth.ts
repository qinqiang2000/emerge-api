// frontend/src/lib/auth.ts
//
// Auth control-plane API. Same-origin via the vite proxy, so the signed session
// cookie rides along automatically (`credentials: 'same-origin'` default). The
// headless bearer-PAT channel is backend-only; the browser always uses cookies.

export interface AuthUser {
  id: string
  email: string
  full_name: string
  display_name: string
  team_ids: string[]
  active_team_id: string | null
  is_superuser: boolean
  created_at: string
}

export interface AuthTeam {
  id: string
  name: string
  invite_token: string
  created_by: string
  member_ids: string[]
  created_at: string
}

export interface Me {
  authenticated: boolean
  open_mode: boolean
  user: AuthUser | null
  active_team: AuthTeam | null
  teams: AuthTeam[]
}

export interface Pat {
  pat_id: string
  label: string
  created_at: string | null
  last_used: string | null
}

export interface TeamMember {
  id: string
  email: string
  full_name: string
  display_name: string
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!r.ok) {
    let code = `http_${r.status}`
    try {
      const body = await r.json()
      code = body?.detail?.error_code ?? body?.error_code ?? code
    } catch { /* non-json */ }
    throw new Error(code)
  }
  if (r.status === 204) return undefined as T
  return r.json() as Promise<T>
}

export const fetchMe = () => req<Me>('/auth/me')

export const login = (email: string, password: string) =>
  req<{ user: AuthUser }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })

export const signup = (email: string, password: string, full_name: string, token: string) =>
  req<{ user: AuthUser; active_team: AuthTeam }>('/auth/signup', {
    method: 'POST',
    body: JSON.stringify({ email, password, full_name, token }),
  })

export const logout = () => req<{ ok: boolean }>('/auth/logout', { method: 'POST' })

export const updateMe = (patch: { full_name?: string; display_name?: string; new_password?: string }) =>
  req<{ user: AuthUser }>('/auth/me', { method: 'PATCH', body: JSON.stringify(patch) })

export const switchTeam = (team_id: string) =>
  req<{ user: AuthUser }>('/auth/teams/switch', { method: 'POST', body: JSON.stringify({ team_id }) })

export const getTeam = (teamId: string) =>
  req<{ team: AuthTeam; members: TeamMember[] }>(`/auth/teams/${encodeURIComponent(teamId)}`)

export const renameTeam = (teamId: string, name: string) =>
  req<{ team: AuthTeam }>(`/auth/teams/${encodeURIComponent(teamId)}`, {
    method: 'PATCH', body: JSON.stringify({ name }),
  })

// --- personal access tokens (headless / cowork) ---
export const mintToken = (label: string) =>
  req<{ token: string; pat_id: string; label: string }>('/auth/me/tokens', {
    method: 'POST', body: JSON.stringify({ label }),
  })

export const listTokens = () => req<Pat[]>('/auth/me/tokens')

export const revokeToken = (patId: string) =>
  req<{ ok: boolean }>(`/auth/me/tokens/${encodeURIComponent(patId)}`, { method: 'DELETE' })

// --- superuser admin ---
export const adminCreateTeam = (name: string) =>
  req<{ team: AuthTeam }>('/auth/admin/teams', { method: 'POST', body: JSON.stringify({ name }) })

export const adminListTeams = () => req<AuthTeam[]>('/auth/admin/teams')

export const adminListUsers = () => req<AuthUser[]>('/auth/admin/users')

/** The shareable signup link for a team's invite token. */
export function inviteLink(token: string): string {
  return `${window.location.origin}/?invite=${encodeURIComponent(token)}`
}
