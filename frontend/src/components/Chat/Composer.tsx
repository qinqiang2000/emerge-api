import { useState, type DragEvent, type KeyboardEvent } from 'react'

import SlashMenu from './SlashMenu'

interface Props {
  disabled: boolean
  pending: { filename: string }[]
  onAttach: (files: File[]) => void
  onSubmit: (text: string) => void
}

export default function Composer({ disabled, pending, onAttach, onSubmit }: Props) {
  const [text, setText] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const showSlash = text.startsWith('/')

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (text.trim().length === 0) return
      onSubmit(text.trim())
      setText('')
    }
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    onAttach(Array.from(e.dataTransfer.files))
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={
        'relative border-t border-subtle p-3 ' +
        (dragOver ? 'bg-subtle' : 'bg-canvas')
      }
    >
      {showSlash && (
        <SlashMenu query={text} onPick={(c) => { setText(c + ' '); }} />
      )}
      {pending.length > 0 && (
        <ul className="flex flex-wrap gap-1 mb-2">
          {pending.map((a, i) => (
            <li key={i} className="text-xs px-2 py-1 bg-surface border border-subtle rounded">
              {a.filename}
            </li>
          ))}
        </ul>
      )}
      <textarea
        rows={2}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKey}
        placeholder="Drop docs here, or / for commands"
        className="w-full bg-surface text-fg-primary p-2 font-body resize-none focus:outline-none focus:ring-1 focus:ring-accent-primary"
      />
    </div>
  )
}
