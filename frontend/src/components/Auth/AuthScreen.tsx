import { useState } from 'react'

import { useAuth } from '../../stores/auth'
import { useT } from '../../i18n'
import './auth.css'

/** Read the invite token from `?invite=` (set by a shared invite link). */
function readInvite(): string {
  try {
    return new URLSearchParams(window.location.search).get('invite')?.trim() ?? ''
  } catch {
    return ''
  }
}

/**
 * Full-screen login / signup gate (tenant mode, unauthenticated). Signup is
 * only reachable with an invite token in the URL — superuser curates teams and
 * members join via the shared link (no open self-serve registration).
 */
export default function AuthScreen() {
  const t = useT()
  const login = useAuth(s => s.login)
  const signup = useAuth(s => s.signup)

  const invite = readInvite()
  const [mode, setMode] = useState<'login' | 'signup'>(invite ? 'signup' : 'login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signup') {
        await signup(email, password, fullName, invite)
      } else {
        await login(email, password)
      }
    } catch (err) {
      setError(t(`auth.err.${(err as Error).message}`) || t('auth.err.generic'))
      setBusy(false)
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-brand">emerge</div>
        <div className="auth-tagline">{t('auth.tagline')}</div>

        <h1 className="auth-title">
          {mode === 'signup' ? t('auth.signup.title') : t('auth.login.title')}
        </h1>

        {mode === 'signup' && invite && (
          <div className="auth-invite-note">{t('auth.signup.invited')}</div>
        )}

        <form className="auth-form" onSubmit={onSubmit}>
          {mode === 'signup' && (
            <label className="auth-field">
              <span>{t('auth.field.name')}</span>
              <input
                value={fullName}
                onChange={e => setFullName(e.target.value)}
                autoComplete="name"
                required
              />
            </label>
          )}
          <label className="auth-field">
            <span>{t('auth.field.email')}</span>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              autoComplete="email"
              required
              autoFocus
            />
          </label>
          <label className="auth-field">
            <span>{t('auth.field.password')}</span>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
              required
            />
          </label>

          {error && <div className="auth-error">{error}</div>}

          <button type="submit" className="auth-submit" disabled={busy}>
            {busy
              ? t('auth.submitting')
              : mode === 'signup' ? t('auth.signup.cta') : t('auth.login.cta')}
          </button>
        </form>

        <div className="auth-switch">
          {mode === 'login' ? (
            invite ? (
              <button type="button" onClick={() => setMode('signup')}>
                {t('auth.toSignup')}
              </button>
            ) : (
              <span className="auth-hint">{t('auth.needInvite')}</span>
            )
          ) : (
            <button type="button" onClick={() => setMode('login')}>
              {t('auth.toLogin')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
