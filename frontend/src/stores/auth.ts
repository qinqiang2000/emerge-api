// frontend/src/stores/auth.ts
//
// Auth/session state. On mount, App calls `bootstrap()` once:
//   - open_mode (no users configured) → render the app as before, no login.
//   - authenticated → render the app, real identity flows into UserMenu.
//   - tenant mode + not authenticated → App renders <AuthScreen/>.
import { create } from 'zustand'

import * as api from '../lib/auth'
import type { AuthTeam, AuthUser, Me } from '../lib/auth'

interface State {
  me: Me | null
  loaded: boolean
  bootstrap: () => Promise<void>
  refresh: () => Promise<void>
  login: (email: string, password: string) => Promise<void>
  signup: (email: string, password: string, fullName: string, token: string) => Promise<void>
  logout: () => Promise<void>
  switchTeam: (teamId: string) => Promise<void>
  applyUser: (user: AuthUser) => void
}

export const useAuth = create<State>((set, get) => ({
  me: null,
  loaded: false,
  bootstrap: async () => {
    try {
      const me = await api.fetchMe()
      set({ me, loaded: true })
    } catch {
      // 401 in tenant mode → unauthenticated; signal "needs login".
      set({ me: { authenticated: false, open_mode: false, user: null, active_team: null, teams: [] }, loaded: true })
    }
  },
  refresh: async () => {
    const me = await api.fetchMe()
    set({ me })
  },
  login: async (email, password) => {
    await api.login(email, password)
    await get().refresh()
  },
  signup: async (email, password, fullName, token) => {
    await api.signup(email, password, fullName, token)
    await get().refresh()
  },
  logout: async () => {
    await api.logout()
    set({ me: { authenticated: false, open_mode: false, user: null, active_team: null, teams: [] } })
  },
  switchTeam: async (teamId) => {
    await api.switchTeam(teamId)
    await get().refresh()
    // a different team = a different workspace; reload so every store re-fetches
    // against the new tenant (projects, docs, chats…).
    window.location.assign('/')
  },
  applyUser: (user: AuthUser) => {
    const me = get().me
    if (me) set({ me: { ...me, user } })
  },
}))

export type { AuthUser, AuthTeam, Me }
