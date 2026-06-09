// frontend/src/components/Empty/EmptyHero.tsx
//
// 主页只留"拖拽区"这一个核心动作。原先的 /help nudge、引导卡片、starter 列表
// 已收敛进 composer 上方的动态 tip（见 Chat/composerTips.ts）——主页不再堆提示。
import { useState } from 'react'

import { useT } from '../../i18n'

interface Props {
  projectName?: string
  /** Entered via the spine "新建项目" row — read the canvas as a fresh project
   *  (slot + naming note) rather than a generic unbound scratch chat. */
  newProject?: boolean
  onAttach: (files: File[]) => void
}

export default function EmptyHero({
  projectName = '',
  newProject = false,
  onAttach,
}: Props) {
  const t = useT()
  const [dragOver, setDragOver] = useState(false)

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
    </div>
  )
}
