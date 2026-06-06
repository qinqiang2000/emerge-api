// frontend/src/components/Empty/EmptyHero.tsx
import { useState } from 'react'

import { useT } from '../../i18n'
import { useOnboarding } from '../../stores/onboarding'

const STARTER_KEYS = [
  'empty.starter.fork',
  'empty.starter.invoices',
  'empty.starter.schemaThenEdit',
] as const

interface Props {
  projectName?: string
  /** Entered via the spine "新建项目" row — read the canvas as a fresh project
   *  (slot + naming note) rather than a generic unbound scratch chat. */
  newProject?: boolean
  onAttach: (files: File[]) => void
  onStarter: (text: string) => void
}

export default function EmptyHero({
  projectName = '',
  newProject = false,
  onAttach,
  onStarter,
}: Props) {
  const t = useT()
  const [dragOver, setDragOver] = useState(false)
  // 只对"本会话还没暴露熟练度"的人显示新手 nudge——一旦敲过 `/`/`@` 或提交过
  // 一次 turn(见 stores/onboarding),它就该淡出,不再挡着老手。
  const competent = useOnboarding(s => s.competent)

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(true)
  }

  function handleDragLeave() {
    setDragOver(false)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) onAttach(files)
  }

  const eyebrow = projectName
    ? `~/projects/${projectName}/`
    : newProject
      ? t('empty.eyebrow.newProject')
      : '~/projects/'

  return (
    <div className="empty-hero">
      <div className="ey">{eyebrow}</div>
      {newProject && <div className="new-note">{t('empty.newproject.note')}</div>}
      {!competent && (
        <div
          className="help-nudge"
          onClick={() => onStarter('/help')}
          role="button"
          tabIndex={0}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onStarter('/help') }}
          style={{ color: 'var(--ink-4)', cursor: 'pointer', fontSize: '0.85em', marginBottom: 8 }}
        >
          {t('empty.help.nudge')}
        </div>
      )}
      {/* <h1>
        {t('empty.headline.before')} <em>{t('empty.headline.em')}</em>
      </h1> */}
<div
        className="invite"
        onClick={() => onStarter(t('empty.guide.prompt'))}
        role="button"
        tabIndex={0}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onStarter(t('empty.guide.prompt')) }}
      >
        <span className="cmd">{t('empty.guide.title')}</span>
        <span style={{ color: 'var(--ink-3)' }}>{t('empty.guide.hint')}</span>
        <span style={{ color: 'var(--ink-5)', marginLeft: 'auto' }}>↵</span>
      </div>
      <div
        className="drop"
        style={dragOver ? { borderColor: 'var(--ochre-2)', background: 'var(--ochre-soft)' } : undefined}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <b>{t('empty.drop.headline')}</b>
        <span>{t('empty.drop.orRun')}</span>
      </div>
      <div className="starters">
        <div className="lbl">{t('empty.starters.label')}</div>
        {STARTER_KEYS.map((k, i) => {
          const s = t(k)
          return (
            <button key={i} className="starter" onClick={() => onStarter(s)}>
              <span className="quote">&quot;</span>
              <span>{s}</span>
              <span className="arr">↵</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
