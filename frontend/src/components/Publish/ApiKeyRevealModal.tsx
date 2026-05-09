import * as Dialog from '@radix-ui/react-dialog'
import { Check, Copy, KeyRound } from 'lucide-react'
import { useState } from 'react'

import { useApiKey } from '../../stores/apiKey'

export default function ApiKeyRevealModal() {
  const { current, clear } = useApiKey()
  const [copied, setCopied] = useState(false)

  if (!current) return null

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(current.key_plaintext)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) clear() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 w-[min(480px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 bg-surface text-fg-primary p-6 rounded border border-subtle shadow-lg space-y-4"
          onEscapeKeyDown={(e) => e.preventDefault()}
          onPointerDownOutside={(e) => e.preventDefault()}
        >
          <div className="flex items-center gap-2 text-accent-primary">
            <KeyRound size={18} />
            <Dialog.Title className="font-mono text-sm">
              API key for {current.project_id}{current.version_id ? ` · ${current.version_id}` : ''}
            </Dialog.Title>
          </div>
          <Dialog.Description className="text-sm text-fg-secondary">
            这是这把 key 的唯一可见时刻。复制并保存到安全位置，关闭后只剩 hash。
          </Dialog.Description>
          <div className="bg-subtle px-3 py-2 font-mono text-xs break-all select-all">
            {current.key_plaintext}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label="copy"
              onClick={handleCopy}
              className="px-3 py-1.5 text-sm bg-accent-info text-canvas inline-flex items-center gap-1 hover:opacity-90"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
              {copied ? '已复制' : '复制'}
            </button>
            <span className="text-xs text-fg-muted ml-auto">created {current.created_at}</span>
          </div>
          <div className="border-t border-subtle pt-3">
            <button
              type="button"
              aria-label="我已保存 - 关闭"
              onClick={clear}
              className="w-full px-3 py-2 text-sm bg-accent-primary text-canvas hover:opacity-90"
            >
              我已保存到安全位置 - 关闭
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
