import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, Copy, Trash2, Plus } from 'lucide-react'

import * as api from '../../lib/auth'
import type { AuthTeam, AuthUser, Pat, TeamMember } from '../../lib/auth'
import { useAuth } from '../../stores/auth'
import { useSettings, type SettingsSection } from '../../stores/settings'
import { useT } from '../../i18n'
import './settings.css'

function copy(text: string) {
  navigator.clipboard?.writeText(text).catch(() => {})
}

/** claude.ai-style settings sheet: left section nav + right content panel.
 *  Opened from the account menu; Esc / scrim / ✕ close. */
export default function SettingsModal() {
  const t = useT()
  const open = useSettings(s => s.open)
  const section = useSettings(s => s.section)
  const show = useSettings(s => s.show)
  const hide = useSettings(s => s.hide)
  const me = useAuth(s => s.me)
  const user = me?.user ?? null

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') hide() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, hide])

  if (!open || !user) return null

  const sections: { key: SettingsSection; label: string; show: boolean }[] = [
    { key: 'general', label: t('settings.nav.general'), show: true },
    { key: 'account', label: t('settings.nav.account'), show: true },
    { key: 'developer', label: t('settings.nav.developer'), show: true },
    { key: 'team', label: t('settings.nav.team'), show: !!me?.active_team },
    { key: 'admin', label: t('settings.nav.admin'), show: user.is_superuser },
  ]

  const body = (
    <div className="settings-scrim" onMouseDown={hide}>
      <div className="settings-sheet" onMouseDown={e => e.stopPropagation()}>
        <aside className="settings-nav">
          <div className="settings-nav-title">{t('settings.title')}</div>
          {sections.filter(s => s.show).map(s => (
            <button
              key={s.key}
              className={'settings-nav-item' + (section === s.key ? ' on' : '')}
              onClick={() => show(s.key)}
            >
              {s.label}
            </button>
          ))}
        </aside>
        <div className="settings-content">
          <button className="settings-close" onClick={hide} aria-label={t('settings.close')}>
            <X size={18} />
          </button>
          {section === 'general' && <GeneralSection user={user} />}
          {section === 'account' && <AccountSection user={user} />}
          {section === 'developer' && <DeveloperSection />}
          {section === 'team' && me?.active_team && <TeamSection team={me.active_team} />}
          {section === 'admin' && user.is_superuser && <AdminSection />}
        </div>
      </div>
    </div>
  )
  return createPortal(body, document.body)
}

function GeneralSection({ user }: { user: AuthUser }) {
  const t = useT()
  const applyUser = useAuth(s => s.applyUser)
  const [name, setName] = useState(user.display_name || user.full_name)
  const [saved, setSaved] = useState(false)

  const save = async () => {
    const { user: u } = await api.updateMe({ display_name: name, full_name: name })
    applyUser(u)
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  return (
    <section className="settings-section">
      <h2>{t('settings.general.profile')}</h2>
      <div className="settings-row">
        <label>{t('settings.general.avatar')}</label>
        <span className="settings-avatar">{(name || user.email)[0]?.toUpperCase()}</span>
      </div>
      <div className="settings-row">
        <label>{t('settings.general.name')}</label>
        <input value={name} onChange={e => setName(e.target.value)} />
      </div>
      <button className="settings-btn" onClick={save}>
        {saved ? t('settings.saved') : t('settings.save')}
      </button>
    </section>
  )
}

function AccountSection({ user }: { user: AuthUser }) {
  const t = useT()
  const [pw, setPw] = useState('')
  const [msg, setMsg] = useState<string | null>(null)

  const change = async () => {
    if (!pw) return
    await api.updateMe({ new_password: pw })
    setPw('')
    setMsg(t('settings.account.pwChanged'))
    setTimeout(() => setMsg(null), 1800)
  }

  return (
    <section className="settings-section">
      <h2>{t('settings.nav.account')}</h2>
      <div className="settings-row">
        <label>{t('auth.field.email')}</label>
        <span className="settings-static">{user.email}</span>
      </div>
      <div className="settings-row">
        <label>{t('settings.account.newPassword')}</label>
        <input type="password" value={pw} onChange={e => setPw(e.target.value)} autoComplete="new-password" />
      </div>
      <button className="settings-btn" onClick={change} disabled={!pw}>{t('settings.account.changePw')}</button>
      {msg && <div className="settings-ok">{msg}</div>}
    </section>
  )
}

function DeveloperSection() {
  const t = useT()
  const [pats, setPats] = useState<Pat[]>([])
  const [label, setLabel] = useState('')
  const [fresh, setFresh] = useState<string | null>(null)

  const reload = useCallback(() => { api.listTokens().then(setPats).catch(() => {}) }, [])
  useEffect(() => { reload() }, [reload])

  const mint = async () => {
    const { token } = await api.mintToken(label)
    setFresh(token)
    setLabel('')
    reload()
  }
  const revoke = async (id: string) => { await api.revokeToken(id); reload() }

  return (
    <section className="settings-section">
      <h2>{t('settings.dev.title')}</h2>
      <p className="settings-help">{t('settings.dev.help')}</p>

      {fresh && (
        <div className="settings-token-reveal">
          <div className="settings-token-warn">{t('settings.dev.revealOnce')}</div>
          <div className="settings-token-row">
            <code>{fresh}</code>
            <button onClick={() => copy(fresh)} title={t('settings.copy')}><Copy size={14} /></button>
          </div>
          <pre className="settings-token-usage">{`curl -H "Authorization: Bearer ${fresh}" \\
     -H "X-Emerge-Team: <team>" $API/lab/projects`}</pre>
        </div>
      )}

      <div className="settings-inline">
        <input
          placeholder={t('settings.dev.labelPlaceholder')}
          value={label}
          onChange={e => setLabel(e.target.value)}
        />
        <button className="settings-btn" onClick={mint}><Plus size={14} /> {t('settings.dev.mint')}</button>
      </div>

      <ul className="settings-list">
        {pats.map(p => (
          <li key={p.pat_id}>
            <div>
              <span className="settings-list-label">{p.label || p.pat_id}</span>
              <span className="settings-list-meta">
                {t('settings.dev.lastUsed')}: {p.last_used ? p.last_used.slice(0, 10) : t('settings.dev.never')}
              </span>
            </div>
            <button className="settings-icon-btn" onClick={() => revoke(p.pat_id)} title={t('settings.dev.revoke')}>
              <Trash2 size={14} />
            </button>
          </li>
        ))}
        {pats.length === 0 && <li className="settings-empty">{t('settings.dev.none')}</li>}
      </ul>
    </section>
  )
}

function TeamSection({ team }: { team: AuthTeam }) {
  const t = useT()
  const [name, setName] = useState(team.name)
  const [members, setMembers] = useState<TeamMember[]>([])
  const link = api.inviteLink(team.invite_token)

  useEffect(() => {
    api.getTeam(team.id).then(r => { setMembers(r.members); setName(r.team.name) }).catch(() => {})
  }, [team.id])

  const save = async () => { await api.renameTeam(team.id, name) }

  return (
    <section className="settings-section">
      <h2>{t('settings.team.title')}</h2>
      <div className="settings-row">
        <label>{t('settings.team.name')}</label>
        <input value={name} onChange={e => setName(e.target.value)} onBlur={save} />
      </div>
      <div className="settings-row">
        <label>{t('settings.team.invite')}</label>
        <div className="settings-copy-row">
          <code className="settings-link">{link}</code>
          <button className="settings-icon-btn" onClick={() => copy(link)} title={t('settings.copy')}><Copy size={14} /></button>
        </div>
      </div>
      <p className="settings-help">{t('settings.team.inviteHelp')}</p>
      <h3 className="settings-subhead">{t('settings.team.members')} ({members.length})</h3>
      <ul className="settings-list">
        {members.map(m => (
          <li key={m.id}>
            <div>
              <span className="settings-list-label">{m.display_name || m.full_name || m.email}</span>
              <span className="settings-list-meta">{m.email}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function AdminSection() {
  const t = useT()
  const [teams, setTeams] = useState<AuthTeam[]>([])
  const [users, setUsers] = useState<AuthUser[]>([])
  const [newTeam, setNewTeam] = useState('')
  const [created, setCreated] = useState<AuthTeam | null>(null)

  const reload = useCallback(() => {
    api.adminListTeams().then(setTeams).catch(() => {})
    api.adminListUsers().then(setUsers).catch(() => {})
  }, [])
  useEffect(() => { reload() }, [reload])

  const create = async () => {
    if (!newTeam.trim()) return
    const { team } = await api.adminCreateTeam(newTeam.trim())
    setCreated(team)
    setNewTeam('')
    reload()
  }

  return (
    <section className="settings-section">
      <h2>{t('settings.admin.title')}</h2>
      <p className="settings-help">{t('settings.admin.help')}</p>

      <div className="settings-inline">
        <input placeholder={t('settings.admin.teamNamePlaceholder')} value={newTeam} onChange={e => setNewTeam(e.target.value)} />
        <button className="settings-btn" onClick={create}><Plus size={14} /> {t('settings.admin.createTeam')}</button>
      </div>

      {created && (
        <div className="settings-token-reveal">
          <div className="settings-token-warn">{t('settings.admin.inviteReady', { name: created.name })}</div>
          <div className="settings-token-row">
            <code>{api.inviteLink(created.invite_token)}</code>
            <button onClick={() => copy(api.inviteLink(created.invite_token))}><Copy size={14} /></button>
          </div>
        </div>
      )}

      <h3 className="settings-subhead">{t('settings.admin.teams')} ({teams.length})</h3>
      <ul className="settings-list">
        {teams.map(tm => (
          <li key={tm.id}>
            <div>
              <span className="settings-list-label">{tm.name}</span>
              <span className="settings-list-meta">{tm.member_ids.length} {t('settings.admin.membersWord')}</span>
            </div>
            <button className="settings-icon-btn" onClick={() => copy(api.inviteLink(tm.invite_token))} title={t('settings.admin.copyInvite')}>
              <Copy size={14} />
            </button>
          </li>
        ))}
      </ul>

      <h3 className="settings-subhead">{t('settings.admin.users')} ({users.length})</h3>
      <ul className="settings-list">
        {users.map(u => (
          <li key={u.id}>
            <div>
              <span className="settings-list-label">{u.display_name || u.full_name || u.email}{u.is_superuser ? ' ★' : ''}</span>
              <span className="settings-list-meta">{u.email}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
