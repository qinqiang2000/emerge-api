// frontend/src/components/Chat/SlashMenu.tsx

interface Item { cmd: string; desc: string }

const COMMANDS: Item[] = [
  { cmd: '/init',    desc: 'derive a prompt from the documents in this folder' },
  { cmd: '/extract', desc: 'run extraction on every doc, or a subset' },
  { cmd: '/review',  desc: 'open the next pending document for review' },
  { cmd: '/eval',    desc: 'score current prompt against reviewed/' },
  { cmd: '/improve', desc: 'long-running: refine field descriptions to lift F1' },
  { cmd: '/publish', desc: 'freeze a version and mint an API key' },
]

// Rank cmd-prefix > cmd-contains > desc-contains so users who half-remember the
// name still see direct hits at the top, while typing a word from the description
// (Claude Code CLI behavior — `/auditing` surfaces `/a11y-debugging`) still works.
// Desc matching is gated by q.length >= 2: single letters would otherwise match
// almost every command (think `i` in "init", "fix", "extraction"…) and bury the
// real intent.
function filterSlashCommands(query: string): Item[] {
  const trimmed = query.trim().toLowerCase()
  if (!trimmed) return COMMANDS
  const q = trimmed.replace(/^\/+/, '')
  if (!q) return COMMANDS
  const cmdPrefix: Item[] = []
  const cmdContains: Item[] = []
  const descContains: Item[] = []
  for (const c of COMMANDS) {
    const cmdBody = c.cmd.toLowerCase().replace(/^\/+/, '')
    if (cmdBody.startsWith(q)) cmdPrefix.push(c)
    else if (cmdBody.includes(q)) cmdContains.push(c)
    else if (q.length >= 2 && c.desc.toLowerCase().includes(q)) descContains.push(c)
  }
  return [...cmdPrefix, ...cmdContains, ...descContains]
}

interface Props {
  query: string
  activeIdx: number
  onPick: (cmd: string) => void
  onHover: (idx: number) => void
}

export default function SlashMenu({ query, activeIdx, onPick, onHover }: Props) {
  // Composer already gates rendering on `slashMatches.length > 0`, so a zero-match
  // case shouldn't reach here. Filter (no fallback) as defense in depth.
  const list = filterSlashCommands(query)

  return (
    <div className="slashmenu">
      <div className="inner">
        {list.map((s, i) => (
          <div
            key={s.cmd}
            className={'item ' + (i === activeIdx ? 'active' : '')}
            onMouseEnter={() => onHover(i)}
            onMouseDown={(e) => { e.preventDefault(); onPick(s.cmd) }}
          >
            <span className="cmd">{s.cmd}</span>
            <span className="desc">{s.desc}</span>
            <span className="hint">{i === activeIdx ? '↵' : ''}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export { COMMANDS, filterSlashCommands }
