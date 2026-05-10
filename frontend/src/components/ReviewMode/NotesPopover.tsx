import { useState } from 'react'

interface Props {
  fieldName: string
  initial: string
  onSave: (text: string) => void
  onClose: () => void
}

export default function NotesPopover({ fieldName, initial, onSave, onClose }: Props) {
  const [text, setText] = useState(initial)
  return (
    <div className="absolute right-0 top-full z-10 mt-1 w-72 bg-paper border border-rule p-2 shadow-md">
      <div className="text-xs text-ink-4 font-mono mb-1">note · {fieldName}</div>
      <textarea
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        className="w-full bg-paper-2 border border-rule px-2 py-1 text-sm resize-none"
      />
      <div className="flex justify-end gap-2 mt-1">
        <button type="button" onClick={onClose} className="px-2 py-1 text-xs hover:bg-paper-2">cancel</button>
        <button
          type="button"
          onClick={() => { onSave(text); onClose() }}
          className="px-2 py-1 text-xs bg-ochre text-paper"
        >
          save
        </button>
      </div>
    </div>
  )
}
