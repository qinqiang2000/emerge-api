// frontend/src/components/Chat/SlashMenu.tsx

interface Item { cmd: string; desc: string }

const COMMANDS: Item[] = [
  { cmd: '/init',    desc: 'derive a schema from the documents in this folder' },
  { cmd: '/extract', desc: 'run extraction on every doc, or a subset' },
  { cmd: '/review',  desc: 'open the next pending document for review' },
  { cmd: '/eval',    desc: 'score current schema against reviewed/' },
  { cmd: '/improve', desc: 'long-running: refine field descriptions to lift F1' },
  { cmd: '/publish', desc: 'freeze a version and mint an API key' },
]

interface Props {
  query: string
  activeIdx: number
  onPick: (cmd: string) => void
  onHover: (idx: number) => void
}

export default function SlashMenu({ query, activeIdx, onPick, onHover }: Props) {
  const filtered = query.trim().length > 1
    ? COMMANDS.filter(s => s.cmd.toLowerCase().startsWith(query.trim().toLowerCase()))
    : COMMANDS
  const list = filtered.length ? filtered : COMMANDS

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

export { COMMANDS }
