import type { ReactNode } from 'react'
import './Reminder.css'

export type ReminderIntent = 'note' | 'tip' | 'caution' | 'warning'
export type ReminderForm = 'block' | 'inline'

const GLYPH: Record<ReminderIntent, string> = {
  note: 'i',
  tip: '✓',
  caution: '!',
  warning: '×',
}

interface ReminderProps {
  intent: ReminderIntent
  form?: ReminderForm
  /** Block form only — italic one-liner above the body. */
  title?: string
  children?: ReactNode
  className?: string
}

export default function Reminder({
  intent,
  form = 'block',
  title,
  children,
  className,
}: ReminderProps) {
  const glyph = GLYPH[intent]

  if (form === 'inline') {
    const cls = ['rm-inline', intent, className].filter(Boolean).join(' ')
    return (
      <span className={cls} role="status">
        <span className="rm-glyph" aria-hidden="true">{glyph}</span>
        {children}
      </span>
    )
  }

  const cls = ['rm', intent, className].filter(Boolean).join(' ')
  return (
    <div className={cls} role="note">
      <div className="rm-icon" aria-hidden="true">{glyph}</div>
      <div className="rm-body">
        {title && <div className="rm-title">{title}</div>}
        {children && <div className="rm-text">{children}</div>}
      </div>
    </div>
  )
}
