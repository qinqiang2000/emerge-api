// frontend/src/components/Chat/SlashMenu.tsx
interface Item { command: string; hint: string }

const ITEMS: Item[] = [
  { command: '/new', hint: 'create a new project' },
  { command: '/extract', hint: 'run extraction over project docs' },
  { command: '/eval', hint: 'score against reviewed examples' },
  { command: '/review', hint: 'review predictions' },
  { command: '/improve', hint: 'autoresearch loop (>=5 reviewed)' },
  { command: '/publish', hint: 'freeze version + issue API key' },
  { command: '/feedback', hint: 'address client feedback' },
]

interface Props { query: string; onPick: (cmd: string) => void }

export default function SlashMenu({ query, onPick }: Props) {
  const filtered = ITEMS.filter(i => i.command.startsWith(query))
  if (filtered.length === 0) return null
  return (
    <ul className="absolute bottom-full mb-2 left-0 right-0 max-h-60 overflow-auto bg-surface border border-subtle rounded shadow font-mono text-sm">
      {filtered.map(i => (
        <li key={i.command}>
          <button
            type="button"
            onClick={() => onPick(i.command)}
            className="w-full text-left px-3 py-2 hover:bg-subtle"
          >
            <span className="text-accent-primary">{i.command}</span>{' '}
            <span className="text-fg-muted">{i.hint}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
