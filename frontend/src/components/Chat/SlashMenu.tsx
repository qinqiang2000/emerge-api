// frontend/src/components/Chat/SlashMenu.tsx

interface Item { cmd: string; desc: string }

// Command name + i18n key for its one-line description. The description is
// resolved through the active-locale dict (see `localizedCommands`) so the
// menu + EmptyHero token tooltips read in the user's language — English on the
// en build, Chinese on the zh build. The `cmd` itself is never translated (it
// is what gets typed / matched against the CLI dispatcher).
interface CommandDef { cmd: string; descKey: string }

const COMMAND_DEFS: CommandDef[] = [
  { cmd: '/help',    descKey: 'slash.help.desc' },
  { cmd: '/config',  descKey: 'slash.config.desc' },
  { cmd: '/init',    descKey: 'slash.init.desc' },
  { cmd: '/extract', descKey: 'slash.extract.desc' },
  { cmd: '/review',  descKey: 'slash.review.desc' },
  { cmd: '/eval',    descKey: 'slash.eval.desc' },
  { cmd: '/improve', descKey: 'slash.improve.desc' },
  { cmd: '/publish', descKey: 'slash.publish.desc' },
]

/** Resolve every command's description through the caller's `t` so the list is
 *  locale-correct. Callers hold this and pass slices to `filterSlashCommands`
 *  / render — keeping the fixed `COMMAND_DEFS` order (which doubles as the
 *  pipeline mental model). */
function localizedCommands(t: (key: string) => string): Item[] {
  return COMMAND_DEFS.map(c => ({ cmd: c.cmd, desc: t(c.descKey) }))
}

// Rank cmd-prefix > cmd-contains > desc-contains so users who half-remember the
// name still see direct hits at the top, while typing a word from the description
// (Claude Code CLI behavior — `/auditing` surfaces `/a11y-debugging`) still works.
// Desc matching is gated by q.length >= 2: single letters would otherwise match
// almost every command (think `i` in "init", "fix", "extraction"…) and bury the
// real intent. Operates over a caller-supplied (already localized) command list
// so the desc-contains rank respects the active language.
function filterSlashCommands(commands: Item[], query: string): Item[] {
  const trimmed = query.trim().toLowerCase()
  if (!trimmed) return commands
  const q = trimmed.replace(/^\/+/, '')
  if (!q) return commands
  const cmdPrefix: Item[] = []
  const cmdContains: Item[] = []
  const descContains: Item[] = []
  for (const c of commands) {
    const cmdBody = c.cmd.toLowerCase().replace(/^\/+/, '')
    if (cmdBody.startsWith(q)) cmdPrefix.push(c)
    else if (cmdBody.includes(q)) cmdContains.push(c)
    else if (q.length >= 2 && c.desc.toLowerCase().includes(q)) descContains.push(c)
  }
  return [...cmdPrefix, ...cmdContains, ...descContains]
}

interface Props {
  /** Already-filtered, already-localized rows to render. The Composer owns the
   *  filtering (so its keyboard-nav index and this menu never disagree) and
   *  hands the result straight in. */
  items: Item[]
  activeIdx: number
  onPick: (cmd: string) => void
  onHover: (idx: number) => void
}

export default function SlashMenu({ items, activeIdx, onPick, onHover }: Props) {
  return (
    <div className="slashmenu">
      <div className="inner">
        {items.map((s, i) => (
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

export { COMMAND_DEFS, localizedCommands, filterSlashCommands }
export type { Item as SlashItem }
