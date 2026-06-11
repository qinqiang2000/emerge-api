import { useEffect, lazy, Suspense } from 'react'

import AuthScreen from './components/Auth/AuthScreen'
import { useAuth } from './stores/auth'

// The auth gate is the app's natural code-split boundary: the login screen is
// tiny, so the authenticated app (chat shell, review, CodeMirror, eval/bench —
// the bulk of the bundle) is deferred behind these dynamic imports. An
// unauthenticated visitor never downloads the app chunk.
const AppShell = lazy(() => import('./AppShell'))
const SettingsModal = lazy(() => import('./components/Settings/SettingsModal'))
// SPIKE (dev-only, pre-auth, static assets only — see plans/2026-06-11-audit-board-seed.md)
const BoardSpike = lazy(() => import('./spike/BoardSpike'))

/**
 * Auth gate. Bootstraps `/auth/me` once:
 *   - open_mode (no users) → render the app as before (no login).
 *   - authenticated → render the app + Settings overlay.
 *   - tenant mode + unauthenticated → render <AuthScreen/>.
 */
export default function App() {
  const me = useAuth(s => s.me)
  const loaded = useAuth(s => s.loaded)
  const bootstrap = useAuth(s => s.bootstrap)

  useEffect(() => { bootstrap() }, [bootstrap])

  if (import.meta.env.DEV && new URLSearchParams(window.location.search).has('boardspike')) {
    return <Suspense fallback={null}><BoardSpike /></Suspense>
  }

  if (!loaded) return null
  const authed = me?.open_mode || me?.authenticated
  if (!authed) return <AuthScreen />
  return (
    <Suspense fallback={null}>
      <AppShell />
      <SettingsModal />
    </Suspense>
  )
}
