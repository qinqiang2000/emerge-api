// frontend/src/components/Empty/EmptyHero.tsx
//
// 主页只留"拖拽区"这一个核心动作。原先的 /help nudge、引导卡片、starter 列表
// 已收敛进 composer 上方的动态 tip（见 Chat/composerTips.ts）——主页不再堆提示。
//
// 唯一的例外是下面这行命令 token：一个高度灵活、没有固定菜单的产品仍然需要
// 一眼看完"我能做什么"的入口，而 slash menu 本身要求先敲 `/` 才存在——鼠标
// 用户永远发现不了。这行 token 按 pipeline 顺序排（起草→抽取→评审→发布），
// 本身就是产品心智模型，比任何一段说明文字都省地方。
//
// 常驻（不再按 competent 收起）：token 行是可点的快捷入口，老手同样偏好点击
// 胜过反复敲键盘——一行浅色 token 不构成打扰，等价于一条工具条。每个 token
// hover 即浮出该命令的本地化说明（data-tip → CSS 气泡），新用户不必猜 `/init`
// 是什么意思。
import { useRef, useState } from 'react'

import { useT } from '../../i18n'
import { localizedCommands } from '../Chat/SlashMenu'

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
  const cmdDesc = new Map(localizedCommands(t).map(c => [c.cmd, c.desc]))

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
      <div className="cmd-row">
        {HERO_COMMANDS.map(cmd => (
          <button
            key={cmd}
            type="button"
            className="cmd-token"
            data-tip={cmdDesc.get(cmd)}
            onClick={() => runCommand(cmd)}
          >
            {cmd}
          </button>
        ))}
      </div>
    </div>
  )
}
