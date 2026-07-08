// frontend/src/components/Empty/EmptyHero.tsx
//
// 主页只留"拖拽区"这一个核心动作。原先的 /help nudge、引导卡片、starter 列表
// 已收敛进 composer 上方的动态 tip（见 Chat/composerTips.ts）——主页不再堆提示。
//
// 唯一的例外是下面这行命令 token：一个高度灵活、没有固定菜单的产品仍然需要
// 一眼看完"我能做什么"的入口，而 slash menu 本身要求先敲 `/` 才存在——鼠标
// 用户永远发现不了。这行 token 按 pipeline 顺序排（起草→抽取→评审→发布），
// 本身就是产品心智模型，比任何一段说明文字都省地方。只在本会话还没暴露出
// 熟练度时显示（见 stores/onboarding）；点一次任意 token 就退场，不会跟老手
// 唠叨。
import { useRef, useState } from 'react'

import { useT } from '../../i18n'
import { useOnboarding } from '../../stores/onboarding'
import { COMMANDS } from '../Chat/SlashMenu'

// Curated subset, not the full SlashMenu list — five is scannable at a
// glance; eight starts to feel like a menu bar again. /help leads (it's the
// "explain everything" escape hatch), the rest follow pipeline order.
const HERO_COMMANDS = ['/help', '/init', '/extract', '/review', '/publish'] as const

function runCommand(cmd: string) {
  window.dispatchEvent(new CustomEvent('emerge:composer-command', {
    detail: { cmd, autoSubmit: cmd === '/help' },
  }))
}

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
  const fileRef = useRef<HTMLInputElement>(null)
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
      <input
        ref={fileRef}
        type="file"
        accept="application/pdf,.pdf,image/*"
        multiple
        hidden
        onChange={e => {
          const files = Array.from(e.target.files ?? [])
          if (files.length > 0) onAttach(files)
          e.target.value = ''
        }}
      />
      <div
        className="drop"
        style={dragOver ? { borderColor: 'var(--ochre-2)', background: 'var(--ochre-soft)', cursor: 'copy' } : { cursor: 'pointer' }}
        onClick={() => fileRef.current?.click()}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <b>{t('empty.drop.headline')}</b>
        <span>{t('empty.drop.orClick')}</span>
      </div>
      {!competent && (
        <div className="cmd-row">
          {HERO_COMMANDS.map(cmd => (
            <button
              key={cmd}
              type="button"
              className="cmd-token"
              title={COMMANDS.find(c => c.cmd === cmd)?.desc}
              onClick={() => runCommand(cmd)}
            >
              {cmd}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
