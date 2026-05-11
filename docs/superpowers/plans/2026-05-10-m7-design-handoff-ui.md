# M7 — Design Handoff UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (default per user memory) or `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current frontend with the Claude-Design handoff at `docs/design/emerge-api/`, scene-by-scene, while keeping every backend API and store intact.

**Architecture:**
- Token system rewritten end-to-end: `paper / paper-2 / paper-3 / rule / rule-soft / ink / ink-2..5 / ochre / moss / rose` plus `serif / mono / sans` font triad. No legacy aliases.
- Three-column resizable + collapsible shell with `solo` mode and `localStorage` persistence (`emerge.leftW / emerge.rightW`).
- Conversation, FS spine, context surface, review overlay, empty hero, eval card, publish check, publish key, improve banner — each maps 1:1 to a component pulled from the design prototype (`pieces.jsx`, `app.jsx`, `review.jsx`).
- Light-only for now (dark mode toggle dropped per user decision; logged in `docs/design-decisions.md` as Needs design review).
- No new backend endpoints in M7. Section grouping in review is rendered with a synthetic single-section fallback when schema has no sections; tree view consumes existing `/lab/projects/:id/docs` + `/schema` + `/reviewed` endpoints (no new tree endpoint).

**Tech Stack:** Vite + React 19 + TypeScript + Zustand + Tailwind v3 (CSS-var tokens) + Radix + shadcn-style + Lucide. Existing stores (`useChat`, `useProjects`, `useDocs`, `useSchema`, `useReview`, `useApiKey`, `useJob`) stay; only their consumers (components) get rewritten.

**Source of truth references throughout the plan:**
- HTML/CSS — `docs/design/emerge-api/project/index.html` (lines cited per task)
- Default scenes — `docs/design/emerge-api/project/app.jsx`
- Building blocks — `docs/design/emerge-api/project/pieces.jsx`
- Review overlay — `docs/design/emerge-api/project/review.jsx`
- Fixture data shapes — `docs/design/emerge-api/project/data.jsx`
- Handoff rules — `docs/design/emerge-api/project/handoff/CLAUDE.md` (the doc that *governs* this plan, copied to `docs/design/handoff-CLAUDE.md` in T0)

---

## Pre-flight (T0): contract setup & decision log

**Files:**
- Create: `docs/design-decisions.md`
- Create: `docs/screenshots/.gitkeep`
- Modify: `CLAUDE.md` — add a `Design source of truth` section pointing at the handoff and the decisions log

- [ ] **T0.1 — bootstrap `docs/design-decisions.md`**

Use the template in `docs/design/emerge-api/project/handoff/design-decisions.md`. Open with three pre-existing decision entries:

  1. **2026-05-10 — drop dark-mode toggle in M7** · Status 🚨 Needs design review · Type: interaction · *What changed*: light-only during M7; dark palette to land in a follow-up. *Why*: handoff has no dark spec. *Open*: should dark be derived (ink↔paper invert) or hand-designed?
  2. **2026-05-10 — synthetic single section in review when schema has no `sections`** · Status 🟡 Pending · Type: new-state · *What changed*: schema fields without `section` group under one collapsible "fields" section. *Why*: backend schema is flat; design shows grouped sections only.
  3. **2026-05-10 — improve banner pin position** · Status 🟡 Pending · Type: layout · *What changed*: banner pinned at top-center 14px down (`.improvebar` from CSS). *Why*: handoff places it absolutely over the conv column.

- [ ] **T0.2 — link the contract from `CLAUDE.md`**

Add this block at the top of `CLAUDE.md` (after the slogan, before "Collaboration"):

```md
## Design source of truth

- Handoff bundle: `docs/design/emerge-api/`
- Decisions log: `docs/design-decisions.md` — read before changing UI; append after every UI-shaped change
- The handoff's `CLAUDE.md` (rules for this repo's design contract) is at `docs/design/emerge-api/project/handoff/CLAUDE.md` — read it once, then follow `docs/design-decisions.md` going forward
```

- [ ] **T0.3 — commit**

```bash
git add CLAUDE.md docs/design-decisions.md docs/screenshots/.gitkeep
git commit -m "docs(m7): wire design handoff contract + decisions log"
```

---

## Phase A — Foundation: tokens, fonts, shell skeleton

### T1: Token rewrite

**Files:**
- Modify: `frontend/src/theme/tokens.css`
- Modify: `frontend/tailwind.config.js`
- Modify: `frontend/src/theme/fonts.ts` — load Lora / IBM Plex Mono / Inter (matches `index.html:9`)

- [ ] **T1.1 — replace `tokens.css` body**

Source: `docs/design/emerge-api/project/index.html:11-33`. New file content:

```css
:root {
  --paper:      #FAFAF7;
  --paper-2:    #F2F1EC;
  --paper-3:    #E8E5DC;
  --rule:       #DCD8CD;
  --rule-soft:  #ECE9E0;
  --ink:        #1B1A16;
  --ink-2:      #37352E;
  --ink-3:      #5C5A52;
  --ink-4:      #8A877D;
  --ink-5:      #B3B0A5;
  --ochre:      #B5642C;
  --ochre-2:    #8E4A1E;
  --ochre-soft: #EFD9C4;
  --moss:       #5C6B3A;
  --moss-soft:  #D7DBC2;
  --rose:       #A6453F;
  --rose-soft:  #EAC9C5;
  --serif: 'Lora', 'Iowan Old Style', 'Apple Garamond', Georgia, serif;
  --mono:  'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  --sans:  'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
}
html, body { background: #FDFDFC; color: var(--ink); font-family: var(--serif); -webkit-font-smoothing: antialiased; }
::selection { background: rgba(181,100,44,.22); }
```

Delete the old `--bg-canvas / --bg-surface / --bg-bubble-user / --accent-primary` block and the `[data-theme='dark']` block.

- [ ] **T1.2 — rewrite `tailwind.config.js` color map**

```js
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // darkMode dropped for M7
  theme: {
    extend: {
      colors: {
        paper: 'var(--paper)',
        'paper-2': 'var(--paper-2)',
        'paper-3': 'var(--paper-3)',
        rule: 'var(--rule)',
        'rule-soft': 'var(--rule-soft)',
        ink: 'var(--ink)',
        'ink-2': 'var(--ink-2)',
        'ink-3': 'var(--ink-3)',
        'ink-4': 'var(--ink-4)',
        'ink-5': 'var(--ink-5)',
        ochre: 'var(--ochre)',
        'ochre-2': 'var(--ochre-2)',
        'ochre-soft': 'var(--ochre-soft)',
        moss: 'var(--moss)',
        'moss-soft': 'var(--moss-soft)',
        rose: 'var(--rose)',
        'rose-soft': 'var(--rose-soft)',
      },
      fontFamily: {
        serif: 'var(--serif)',
        mono:  'var(--mono)',
        sans:  'var(--sans)',
      },
    },
  },
  plugins: [],
}
```

- [ ] **T1.3 — update `frontend/src/theme/fonts.ts` to load Inter + IBM Plex Mono**

Replace existing googleapis link with:

```ts
const HREF =
  'https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap'
```

- [ ] **T1.4 — kill the old `useTheme` toggle wiring**

Modify `frontend/src/App.tsx`: remove `import ThemeToggle`, the `<ThemeToggle />` block, and the `useTheme(...).hydrate` effect. Don't delete `frontend/src/stores/theme.ts` and `frontend/src/components/Theme/ThemeToggle.tsx` yet — they get removed in T1.5 to keep diff legible.

- [ ] **T1.5 — delete dead theme files**

```bash
rm frontend/src/stores/theme.ts
rm -rf frontend/src/components/Theme
```

Then grep + remove any remaining `useTheme` imports:

```bash
cd frontend && grep -rln "useTheme\|ThemeToggle\|data-theme" src
```

Expected: empty (after fixing any callers).

- [ ] **T1.6 — verify build passes**

```bash
cd frontend && npm run build
```

Expected: green build, no `Module not found` for theme/canvas/surface tokens.

- [ ] **T1.7 — commit**

```bash
git add frontend/src/theme frontend/tailwind.config.js frontend/src/App.tsx
git rm -r frontend/src/components/Theme frontend/src/stores/theme.ts
git commit -m "feat(m7): swap to design handoff token system; drop dark mode toggle (logged)"
```

---

### T2: Shell layout — 3-column grid + topbar slot

**Files:**
- Create: `frontend/src/components/Shell/Shell.tsx`
- Create: `frontend/src/components/Shell/Topbar.tsx`
- Create: `frontend/src/components/Shell/shell.css` (raw CSS for grid + resizers; Tailwind alone gets gnarly here — match `index.html:42-82`)
- Modify: `frontend/src/App.tsx`

- [ ] **T2.1 — `Shell.tsx` skeleton**

Mirror `app.jsx:88-127`. Key responsibilities:
- 3-column `.shell` grid with CSS vars `--left-w` (default 248px, min 180, max 460), `--right-w` (default 360, min 260, max 600)
- `.shell.no-left | .no-right | .solo | .dragging` state classes
- 8px `.resizer.left` and `.resizer.right` drag handles (mouse + touch)
- `localStorage.getItem/setItem('emerge.leftW' | 'emerge.rightW')` for width persistence

Component shape:

```tsx
type ShellProps = {
  topbar: ReactNode
  left: ReactNode
  center: ReactNode
  right: ReactNode
  leftHidden?: boolean
  rightHidden?: boolean
  // when scene === 'review' the parent passes leftHidden=!leftPeek, rightHidden=!rightPeek
}
export default function Shell(props: ShellProps) { /* ... */ }
```

Implement drag the same way as `app.jsx:36-62`:
- `useState` for `drag: 'left' | 'right' | null`
- `useEffect` attaches `mousemove + mouseup + touchmove + touchend` while dragging
- clamp + persist on every `setLeftW / setRightW`

- [ ] **T2.2 — `Topbar.tsx`**

Match `pieces.jsx:32-91`. Required slots:
- Brand (`emerge` + ochre dot)
- Crumbs: `~/projects/<projectName>/schema · v<n> · draft|frozen`
- Status pills: optional `/improve · 2 of 4 fields` (from `useJob`), `watching docs/ · N files` (from `useDocs`), `⌘K · ask agent`
- `?` help button (HelpPopover lands in T15)
- Left/right side toggles (icons from `pieces.jsx:42-52` + `pieces.jsx:84-87`)

Inputs:

```tsx
type TopbarProps = {
  projectName: string
  schemaVersion: string  // "v3"
  schemaState: 'draft' | 'frozen'
  watchingCount: number
  improveJob?: { progressLabel: string }   // "/improve · 2 of 4 fields"
  leftHidden: boolean
  rightHidden: boolean
  onToggleLeft: () => void
  onToggleRight: () => void
}
```

- [ ] **T2.3 — `shell.css`** — copy these CSS blocks verbatim from `index.html`, adapted as a single `frontend/src/components/Shell/shell.css` imported by `Shell.tsx`:

| from index.html | what |
|---|---|
| `:42-65` | `.shell`, `.shell.no-left`, `.shell.no-right`, `.shell.solo`, transitions |
| `:55-65` | `.resizer.left`, `.resizer.right`, `:hover` indicator |
| `:67-82` | `.top` topbar incl. `.brand`, `.crumbs`, `.pill`, `.side-toggle`, pulse keyframe |

Don't reinvent in Tailwind — these rules use CSS vars, transitions, and keyframes that are cleaner as plain CSS. Keep tokens via `var(--paper)` etc.

- [ ] **T2.4 — wire `App.tsx` into Shell**

```tsx
import Shell from './components/Shell/Shell'
import Topbar from './components/Shell/Topbar'

export default function App() {
  const { activeDocId } = useReview()
  const project = useProjects(s => s.selected())
  // …
  return (
    <Shell
      topbar={<Topbar projectName={project?.name ?? ''} schemaVersion={'v' + (project?.activeVersion ?? 0)} schemaState={project?.activeVersion ? 'frozen' : 'draft'} watchingCount={…} leftHidden={leftHidden} rightHidden={rightHidden} onToggleLeft={…} onToggleRight={…} />}
      left={<ProjectList />}
      center={activeDocId ? <ReviewMode /> : <ChatPanel />}
      right={<DocList />}
      leftHidden={leftHidden}
      rightHidden={rightHidden}
    />
  )
}
```

(Wiring is intentionally minimal — components in left/center/right are still old; they get replaced in later phases.)

- [ ] **T2.5 — manual verify**

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173`. Drag both resizers. Toggle hide-left and hide-right. Reload — widths persist. Take screenshot, save to `docs/screenshots/2026-05-10-m7-shell.png`.

- [ ] **T2.6 — commit**

```bash
git add frontend/src/components/Shell frontend/src/App.tsx docs/screenshots/2026-05-10-m7-shell.png
git commit -m "feat(m7): resizable 3-column shell + topbar (no-left/no-right/solo modes)"
```

---

## Phase B — Default chat scene

### T3: `Turn` + conversation column styling

**Files:**
- Create: `frontend/src/components/Chat/Turn.tsx`
- Modify: `frontend/src/components/Chat/MessageList.tsx`
- Modify: `frontend/src/index.css` — add `.conv` + `.conv-scroll` + `.conv-inner` blocks from `index.html:107-122`

- [ ] **T3.1 — `Turn.tsx`** — port from `pieces.jsx:165-177`:

```tsx
type Props = { who: 'you' | 'agent'; ts: string; children: ReactNode }
export default function Turn({ who, ts, children }: Props) {
  const isAgent = who === 'agent'
  return (
    <div className="turn">
      <div className="turn-meta">
        <span className={`who ${isAgent ? 'agent' : ''}`}>{isAgent ? 'agent' : 'you'}</span>
        <span className="ts">{ts}</span>
        <span className="rule" />
      </div>
      {children}
    </div>
  )
}
```

- [ ] **T3.2 — port `.turn`, `.turn-meta`, `.msg`, `.msg.user`, `.msg code`**

Source: `index.html:110-122`. Add to `frontend/src/index.css`. The `.msg.user::before/after` curly quotes are load-bearing — verify they render.

- [ ] **T3.3 — `MessageList` consumes `Turn`**

Replace the existing `UserBubble` + `AgentMessage` flat layout. Group consecutive same-`role` events under a single `<Turn>`. Map `useChat.events` items: `user_text` → `<div className="msg user">{text}</div>`, `agent_text` → `<AgentMessage text>`, `tool_use`/`tool_result` → `<ToolCall …>` (T4 below), `job_progress` → `<JobProgressCard>` (existing).

- [ ] **T3.4 — adapt `AgentMessage` Markdown styles to new tokens**

In `AgentMessage.tsx` swap `bg-subtle` → `bg-paper-2`, `border-subtle` → `border-rule`, `text-fg-primary` → `text-ink`, `text-accent-primary` → `text-ochre-2`. Code-pill `bg-paper-2 border-rule-soft text-ochre-2`.

- [ ] **T3.5 — verify & commit**

Manual check: a chat with mixed user / agent / tool-use renders inside paper-white center column with serif messages, italic user quotes, ochre code pills.

```bash
git add frontend/src/components/Chat/Turn.tsx frontend/src/components/Chat/MessageList.tsx frontend/src/components/Chat/AgentMessage.tsx frontend/src/index.css
git commit -m "feat(m7): editorial Turn + paper-white conv column"
```

---

### T4: `ToolCall` + `ToolRow` (replaces `ToolCallPill` + `ToolCallGroup`)

**Files:**
- Create: `frontend/src/components/Chat/ToolCall.tsx`
- Create: `frontend/src/components/Chat/ToolRow.tsx`
- Delete: `frontend/src/components/Chat/ToolCallPill.tsx`
- Delete: `frontend/src/components/Chat/ToolCallGroup.tsx`
- Modify: `frontend/src/components/Chat/MessageList.tsx` (uses ToolCall)
- Modify: `frontend/src/index.css` — add `.tool` block from `index.html:124-156`

- [ ] **T4.1 — `ToolCall.tsx`**

Port `pieces.jsx:133-151`. API:

```tsx
type Status = 'done' | 'run' | 'err' | 'cand'
type Props = {
  name: string
  args?: string                  // human-readable args summary
  status: Status
  durationMs?: number            // formatted as 2.1s / 11.4s / 3m 12s
  defaultOpen?: boolean
  footer?: ReactNode             // e.g. accept / reject / cancel + delta label
  children?: ReactNode           // ToolRow[] or diff
}
```

Render:
- `.t-head` collapsible (chevron + name + greyed args + spinner if `run` + `.t-status.<status>` chip + duration)
- `.t-body` shows children when open
- footer slot below body when open

- [ ] **T4.2 — `ToolRow.tsx`**

Port `pieces.jsx:153-162`:

```tsx
type Props = {
  glyph?: string                 // "·" "↳" "✓" "↻" — defaults "·"
  label: ReactNode
  value?: ReactNode
  mini?: ReactNode               // pill on the right ("done", "running", "low conf")
  nest?: 0 | 1 | 2
}
```

- [ ] **T4.3 — port `.tool` CSS** from `index.html:124-156` to `index.css`. Includes `.t-head / .t-arrow / .t-name / .t-args / .t-status.{done,run,err,cand} / .t-dur / .t-body / .t-row / .t-bar / .t-foot / .t-btn / .spin / @keyframes indet`.

- [ ] **T4.4 — adapter from `useChat` events to `ToolCall` props**

The chat store currently emits `tool_use { name, args, … }` and `tool_result { ok, payload, … }`. In `MessageList.tsx`, group adjacent `tool_use` + matching `tool_result` into one `<ToolCall>`. Status mapping:
- `tool_result.ok=true` → `'done'`
- `tool_result.ok=false` → `'err'`
- no result yet → `'run'`
- proposed candidate (autoresearch) → `'cand'` (already encoded as `tool_result.payload.kind === 'candidate'`)

Children: render up to N (5) bullet rows from `tool_result.payload.summary` (or whatever the existing summary shape is — replicate what `ToolCallPill.tsx` did, just inside `<ToolRow />`).

- [ ] **T4.5 — port the candidate diff renderer (used in `/improve`)**

Add `frontend/src/components/Chat/ProposalDiff.tsx`. Mirrors the diff block from `app.jsx:305-313`:

```tsx
function ProposalDiff({ field, oldDesc, newDesc }: Props) {
  return (
    <div className="diff">
      <div className="row">
        <span className="field">description</span>
        <span className="col">
          <span className="old">{oldDesc}</span>
          <span className="new">{newDesc}</span>
        </span>
      </div>
    </div>
  )
}
```

Also port `.diff` CSS from `index.html:158-164`.

- [ ] **T4.6 — verify with playwright**

```bash
cd frontend && npx playwright test tests/chat.spec.ts
```

Expected: existing assertions for tool-call rendering keep passing. Update test selectors if they hard-code `ToolCallPill` (`grep -rn "ToolCallPill" tests`).

- [ ] **T4.7 — commit**

```bash
git add frontend/src/components/Chat
git rm frontend/src/components/Chat/ToolCallPill.tsx frontend/src/components/Chat/ToolCallGroup.tsx
git commit -m "feat(m7): collapsible ToolCall card with status chip + indeterminate progress"
```

---

### T5: New `Composer` (slash menu above, italic placeholder)

**Files:**
- Modify: `frontend/src/components/Chat/Composer.tsx`
- Modify: `frontend/src/components/Chat/SlashMenu.tsx`
- Modify: `frontend/src/index.css` — add `.composer-wrap`, `.composer`, `.slashmenu` blocks from `index.html:166-196`

- [ ] **T5.1 — port `Composer` shape from `pieces.jsx:180-275`**

Critical features the new design adds:
- `.composer-wrap` is `position:absolute` over conv column, with linear-gradient fade above it (so messages scroll under it). The `position:absolute` requires `.conv` to be `position:relative` — we already added that in T3.
- `▸` ochre caret column inside row1
- `<textarea>` with italic serif placeholder `say something to the agent, or type / for a command…`, auto-grow up to 220px then internal scroll (`pieces.jsx:193-199`)
- row2: slash chips (`/init /extract /review /improve /publish`) + `⌘↵ send` hint
- typing `/` opens `.slashmenu` *above* the composer (`bottom:100%; margin-bottom:8px`)
- ↑/↓ navigation, ↵ to insert command + space, Esc clears

- [ ] **T5.2 — `SlashMenu.tsx`** — render `pieces.jsx:231-246` shape:

```tsx
const COMMANDS = [
  { cmd:'/init',     desc:'derive a schema from the documents in this folder' },
  { cmd:'/extract',  desc:'run extraction on every doc, or a subset' },
  { cmd:'/review',   desc:'open the next pending document for review' },
  { cmd:'/eval',     desc:'score current schema against reviewed/' },
  { cmd:'/improve',  desc:'long-running: refine field descriptions to lift F1' },
  { cmd:'/publish',  desc:'freeze a version and mint an API key' },
]
```

Don't lose existing `Composer` features: file-drop attach (`onAttach`), `pending` chips above the textarea, disabled state during `busy`, retry-last-message bridge.

- [ ] **T5.3 — port CSS** from `index.html:166-196`. Verify the `bottom:100%; position:absolute` slashmenu doesn't get clipped by `.composer` overflow.

- [ ] **T5.4 — verify & commit**

Manual: type `/`, see menu pop above composer, navigate with arrows, hit ↵, command lands in textarea with trailing space. Drop a PDF, see chip + filename.

```bash
git add frontend/src/components/Chat/Composer.tsx frontend/src/components/Chat/SlashMenu.tsx frontend/src/index.css
git commit -m "feat(m7): editorial composer with slash menu popover"
```

---

## Phase C — FS Spine + Context Surface

### T6: `FSSpine` — project list + tree view

**Files:**
- Create: `frontend/src/components/Spine/FSSpine.tsx`
- Create: `frontend/src/components/Spine/spine.css` (port from `index.html:84-103`)
- Delete: `frontend/src/components/ProjectList/ProjectList.tsx` (replaced)
- Delete: `frontend/src/components/ProjectList/ProjectItem.tsx`
- Modify: `frontend/src/App.tsx` — pass `<FSSpine />` to `<Shell left={…}>`

- [ ] **T6.1 — `FSSpine.tsx` shape** — port `pieces.jsx:94-130`:

Sections (top to bottom):
1. `~/projects` header + count from `useProjects.list().length`
2. Project rows — clickable, active gets `.active` (ochre left-bar inset). Each row shows `name/`, doc count.
3. `<hr/>`
4. `<active-project>/` header + `ls` muted label
5. Tree of the active project. Tree nodes:
   - `dir` — `▾` arrow + name + count meta (e.g. `42`)
   - `file` — `·` glyph + filename + stamp (e.g. `reviewed`, `pending`, `new`, `frozen`, `F1 .91`)
   - `ghost` — italic muted `… 37 more`

- [ ] **T6.2 — wire tree from existing stores (no new endpoint)**

Tree composition for active project:
- `docs/` — `useDocs.list(pid)`; stamp = `reviewed | pending | new | error` from `has_reviewed`/`has_prediction` (existing fields in `/lab/projects/:id/docs`); compress past 5 rows to a `ghost`
- `reviewed/` — derived from `useReview.reviewedList(pid)` (already populated by chat events)
- `versions/` — `useProjects.selected()?.versions` (already on the project blob via `/lab/projects/:id`); stamps `frozen | draft`
- `metrics/` — `useEval.history(pid)` if it exists; otherwise omit the section in M7 and log to `design-decisions.md` as 🟡 Pending — "metrics tree section deferred until eval history is exposed via API"
- `schema.json` — file row with field count from `useSchema.fields(pid).length`
- `README.md` — file row, no stamp

Don't add a new backend endpoint. The tree is a virtual projection of state we already fetch.

- [ ] **T6.3 — port CSS** `index.html:84-103`. Notably `.fs .proj.active` left ochre bar (`box-shadow:inset 2px 0 0 var(--ochre)`).

- [ ] **T6.4 — verify**

Open dev server, switch projects in left rail, see tree update. Active project gets ochre side-bar. Hover rows highlight on `paper-2`.

- [ ] **T6.5 — commit**

```bash
git add frontend/src/components/Spine frontend/src/App.tsx
git rm -r frontend/src/components/ProjectList
git commit -m "feat(m7): FS spine — projects + per-project tree (no new API)"
```

---

### T7: `ContextSurface` — schema preview / docs / metrics

**Files:**
- Create: `frontend/src/components/Context/ContextSurface.tsx`
- Modify: `frontend/src/index.css` — port `.ctx` block `index.html:198-223`
- Delete: `frontend/src/components/DocList/DocList.tsx` + `DocItem.tsx`
- Modify: `frontend/src/App.tsx` — `<ContextSurface />` in `right` slot

- [ ] **T7.1 — port `pieces.jsx:278-322`**

Three sections (top to bottom):
1. `schema.json` — header `14 fields · v3 draft`, list of first 7 `(name, type)` rows from `useSchema.fields(pid)`, ghost row `+ N more`. Footer micro: *"The schema becomes the agent's prompt at publish time. Edit through conversation."*
2. `docs/` — header `9 of 42 shown`, scrollable card. Each row: filename + status pill (`reviewed`/`pending`/`new`/`error`).
3. `metrics/` — header `latest eval`. Rows for each metric. Tones: `ok` (moss) / `bad` (rose) / default ink. Pull from `useEval.latest(pid)` if exposed; otherwise hard-code 4 placeholder metrics in M7 and log it.

- [ ] **T7.2 — close button** at top-right (`.ctx-close`, `index.html:201-202`). Calls `onToggleRight` via prop.

- [ ] **T7.3 — verify & commit**

Hover docs row, see border highlight. Click close, right panel collapses (handled by Shell from T2).

```bash
git add frontend/src/components/Context frontend/src/index.css frontend/src/App.tsx
git rm -r frontend/src/components/DocList
git commit -m "feat(m7): context surface — schema/docs/metrics tri-section"
```

---

## Phase D — Empty hero + Help popover

### T8: `EmptyHero`

**Files:**
- Create: `frontend/src/components/Empty/EmptyHero.tsx`
- Modify: `frontend/src/components/Chat/ChatPanel.tsx` — render `<EmptyHero />` when project has 0 docs *and* no schema, else `<MessageList />`
- Modify: `frontend/src/index.css` — port `.empty-hero` block `index.html:447-469`

- [ ] **T8.1 — port `app.jsx:155-187`**

Slots:
- Eyebrow: `~/projects/<active-project-name>/`
- Headline serif w/ italic em on second line
- Para in italic Lora
- `/init` invite chip
- Drop zone (real `onDrop` wired to existing `uploadDoc`)
- Three starter prompts; clicking inserts text into `Composer` and submits

- [ ] **T8.2 — branching logic in `ChatPanel.tsx`**

```tsx
const hasContent = useChat.events.length > 0 || (project?.docCount ?? 0) > 0
return hasContent ? <MessageList … /> : <EmptyHero onStarter={(text) => send(pid, text)} />
```

- [ ] **T8.3 — verify**

Switch to a fresh project (`tax-forms/` is the empty fixture seed). Hero appears, drop zone accepts a PDF, starter prompt sends a message.

- [ ] **T8.4 — commit**

```bash
git add frontend/src/components/Empty frontend/src/components/Chat/ChatPanel.tsx frontend/src/index.css
git commit -m "feat(m7): empty-project hero with /init invite + starter prompts"
```

---

### T9: `HelpPopover` (`?` in topbar)

**Files:**
- Create: `frontend/src/components/Shell/HelpPopover.tsx`
- Modify: `frontend/src/components/Shell/Topbar.tsx`
- Modify: `frontend/src/index.css` — port `.help-btn` + `.help-pop` `index.html:475-491`

- [ ] **T9.1 — port `pieces.jsx:6-29`**

4-step explainer with `<code>/init</code>` etc. Closes on Esc or outside click.

- [ ] **T9.2 — wire button in Topbar** with `useState` + render `<HelpPopover onClose={…} />` when open.

- [ ] **T9.3 — verify & commit**

```bash
git add frontend/src/components/Shell/HelpPopover.tsx frontend/src/components/Shell/Topbar.tsx frontend/src/index.css
git commit -m "feat(m7): topbar help popover"
```

---

## Phase E — Review overlay

### T10: Review shell — `ReviewOverlay` rev-bar + 2-column body

**Files:**
- Modify: `frontend/src/components/ReviewMode/ReviewMode.tsx` (becomes `ReviewOverlay`)
- Create: `frontend/src/components/ReviewMode/ReviewBar.tsx`
- Modify: `frontend/src/index.css` — port `.rev-overlay`, `.rev-bar`, `.rev-body`, `.rev-pdf` `index.html:225-269`

- [ ] **T10.1 — outer overlay**

```tsx
export default function ReviewOverlay({ onBack, leftPeek, setLeftPeek, rightPeek, setRightPeek }: Props) {
  return (
    <div className="rev-overlay">
      <ReviewBar onBack={onBack} … />
      <div className="rev-body">
        <PdfViewer … />
        <ReviewFields … />
      </div>
    </div>
  )
}
```

The overlay is rendered inside Shell's `center` slot — `App.tsx` returns ReviewOverlay when `useReview.activeDocId` is set, exactly like today.

- [ ] **T10.2 — `ReviewBar.tsx`** — port `app.jsx`/`review.jsx` rev-bar markup (cf. `index.html:228-269`):

Slots:
- `← back`
- Title: italic *Reviewing* + mono pill with doc filename + page-of-pages
- Spine peek toggle (`spinepeek` button → `setLeftPeek(v=>!v)`)
- Right peek toggle (same for right)
- Form/JSON segmented (`seg`) + Expand-all ghost button
- Prev/next nav arrows (mono `‹ doc 3 / 7 ›`)
- Save button (ink-filled, mono)

State held by ReviewOverlay: `view: 'form' | 'json'`, `forceOpen: null | true | false` (drives Section/Object/Array `forceOpen` — see review.jsx:51-90).

- [ ] **T10.3 — verify & commit**

Open review on any pending doc, see new bar. Save button still calls `useReview.save()`. Nav arrows still call `useReview.prev/next()`.

```bash
git add frontend/src/components/ReviewMode/ReviewMode.tsx frontend/src/components/ReviewMode/ReviewBar.tsx frontend/src/index.css
git commit -m "feat(m7): review overlay shell + rev-bar"
```

---

### T11: Review fields — sections, object, array

**Files:**
- Create: `frontend/src/components/ReviewMode/Section.tsx`
- Create: `frontend/src/components/ReviewMode/FieldRow.tsx`
- Create: `frontend/src/components/ReviewMode/ObjectField.tsx`
- Create: `frontend/src/components/ReviewMode/ArrayField.tsx`
- Modify: `frontend/src/components/ReviewMode/FieldEditor.tsx` (becomes the section-iterating wrapper)
- Modify: `frontend/src/index.css` — port `.rev-fields`, `.rev-sect`, `.rev-fld`, `.rev-obj`, `.rev-arr`, `.ctag`, `.cdot` from `index.html:271-369`

- [ ] **T11.1 — synthetic single-section fallback**

Backend schema has no `section` grouping. In `FieldEditor`:

```tsx
const sections = useMemo(() => {
  const fields = useSchema(s => s.fields(pid))
  // If/when backend grows section support, read from it; for now, one section.
  return [{ id: 'fields', label: 'fields', fields: fieldsToDisplayShape(fields, prediction) }]
}, [pid])
```

Logged in `design-decisions.md` already (T0.1 entry #2).

- [ ] **T11.2 — `FieldRow.tsx`** — port `review.jsx:14-46`. Confidence dot (`cdot.high|mid|low`), monospaced field name, contentEditable serif `.val`, contentEditable italic `.notes`. The notes only show when there's a note OR the row is active.

- [ ] **T11.3 — `ObjectField.tsx`** — port `review.jsx:48-76`. Collapsible card, header has dot+name+`object · N keys`+summary+caret. Body is a stack of nested `<FieldRow nested />`.

- [ ] **T11.4 — `ArrayField.tsx`** — port `review.jsx:78-137`. Each row is `.rcard` with index, summary, optional warn pill, amount, caret. Body has nested fields + `duplicate / delete row` footer.

- [ ] **T11.5 — `Section.tsx`** — port `review.jsx:140-183`. Sticky section header, count chip, optional `flag` pill. Iterates fields and dispatches to FieldRow/ObjectField/ArrayField based on type.

- [ ] **T11.6 — JSON view** — port `review.jsx:185-end` (`buildJsonFromSections` + `<JsonView />` with line numbers and per-key highlighting on `activeField`). CSS `.rev-json` `index.html:371-382`.

- [ ] **T11.7 — wire active-field two-way binding to PdfViewer**

Existing M5 click-to-page still works via `useReview.activeField + page`. Just make sure `setActiveField(path)` flows from FieldRow `onClick` → `useReview.setActiveField(path)`.

- [ ] **T11.8 — verify with playwright**

```bash
cd frontend && npx playwright test tests/review.spec.ts
```

Update assertions to match new DOM structure if they used old `.field-editor` selectors. Confidence dots should appear, edits should mark `.val.edited`, and clicking a `pN` evidence link should jump page (existing M5 behavior).

- [ ] **T11.9 — commit**

```bash
git add frontend/src/components/ReviewMode frontend/src/index.css
git commit -m "feat(m7): review fields — section/object/array nesting + JSON view"
```

---

## Phase F — Eval, Publish, Improve

### T12: `EvalCard` — score table

**Files:**
- Create: `frontend/src/components/Chat/EvalCard.tsx`
- Modify: `frontend/src/index.css` — port `.eval-card`, `.eval-row` `index.html:384-405`

- [ ] **T12.1 — port `app.jsx:343` + `pieces.jsx` (the EvalCard isn't standalone in the prototype, it's inlined in `EvalConversation` — see `app.jsx:323-356`)**

Component shape:

```tsx
type EvalRow = { f: string; p: number; r: number; f1: number; n: number; tone: 'ok'|'mid'|'bad'; err?: string }
type Props = {
  rows: EvalRow[]
  scoredAt: string                // "2 hours ago" or ISO
  overall: number                 // 0.914
}
```

Render: header row (`fields | precision | recall | f1 | nbar`) + each row + expandable error explanation row.

- [ ] **T12.2 — adapter from existing `useEval` store**

If `useEval` returns `EvalReport { fields: [{ name, precision, recall, f1, n, error_explanation? }], overall_f1 }` — map directly. Otherwise call out the gap and stub from `tool_result.payload.eval`.

- [ ] **T12.3 — render in chat**

When a `run_eval` tool result arrives, inline `<EvalCard …/>` after the `<ToolCall>` summary — same place `app.jsx:343` puts it.

- [ ] **T12.4 — verify & commit**

```bash
git add frontend/src/components/Chat/EvalCard.tsx frontend/src/index.css
git commit -m "feat(m7): eval card — per-field precision/recall/f1 table"
```

---

### T13: Publish — readiness check + key reveal

**Files:**
- Create: `frontend/src/components/Publish/PublishStage.tsx` (replaces both `KeyTrailCard.tsx` and `ApiKeyRevealModal.tsx`)
- Delete: `frontend/src/components/Publish/KeyTrailCard.tsx`
- Delete: `frontend/src/components/Publish/ApiKeyRevealModal.tsx`
- Modify: `frontend/src/index.css` — port `.pub-stage`, `.pub-card`, `.pub-eyebrow`, `.pub-h`, `.pub-sub`, `.pub-checks`, `.pub-key`, `.pub-snip` `index.html:407-435`

- [ ] **T13.1 — `PublishStage.tsx` with two stages**

Drives by prop `stage: 'check' | 'key'`. Replaces the conv-column content (overlay-style, `.pub-stage` is `position:absolute; inset:0`).

```tsx
type Props =
  | { stage: 'check'; checklist: Array<{ key:string; label:string; ok:boolean; detail?:string }>; onAdvance:()=>void; onClose:()=>void }
  | { stage: 'key';   keyPreview:string; oneTimeReveal:string; sampleSnippet:string; onClose:()=>void }
```

Stage `check` (port from prototype's check stage CSS lines):
- Eyebrow `READINESS · invoices/`
- Headline `Ready to mint a key?` italic em
- Sub-copy
- `pub-checks` list — green ✓ for ok, ochre ! for warn, with detail text
- Button row: `mint key →` + `cancel`

Stage `key`:
- Eyebrow `KEY MINTED · invoices/v1`
- Headline `Your API is live.` italic em
- `.pub-key` dark card: label "API key (one-time reveal)" + masked key + copy button (existing M6 inline button design — already shipped, keep that pattern)
- One-time copy hint italic
- `.pub-snip` curl snippet

**Critical** (per CLAUDE.md hard rule): the plaintext key only renders inside the `pub-key` card from M3's one-shot SSE; never persisted to JSONL. The existing `useApiKey` store already does this — don't change it.

- [ ] **T13.2 — wire stage transitions**

When user types `/publish`:
- agent runs `readiness_check` → tool_result drives stage `'check'` render
- user clicks `mint key →` → `useApiKey.mintAndReveal()` → on success render stage `'key'`
- close button returns to default conversation

- [ ] **T13.3 — verify & commit**

```bash
git add frontend/src/components/Publish/PublishStage.tsx frontend/src/index.css
git rm frontend/src/components/Publish/KeyTrailCard.tsx frontend/src/components/Publish/ApiKeyRevealModal.tsx
git commit -m "feat(m7): two-stage publish — readiness check then key reveal"
```

---

### T14: Improve scene + banner

**Files:**
- Create: `frontend/src/components/Improve/ImproveBanner.tsx`
- Modify: `frontend/src/components/Chat/MessageList.tsx` — render proposal cards inline
- Modify: `frontend/src/index.css` — port `.improvebar` `index.html:436-446`

- [ ] **T14.1 — `ImproveBanner.tsx`** — port `pieces.jsx:325-337`. Pill banner pinned top-center while a `/improve` job is running (`useJob.byId(jobId).status === 'running'`). Click `open` to scroll the conversation to the autoresearch tool call.

- [ ] **T14.2 — proposal candidate card**

Each `propose_description` tool result already shows up in chat as a `cand` ToolCall (T4 handles status). Use `<ProposalDiff>` (T4.5) as the body and the footer:

```tsx
<ToolCall name="propose_description" args={`field=${field}, delta=${delta}`} status="cand" defaultOpen
  footer={<>
    <button className="t-btn primary" onClick={accept}>{accepted ? 'accepted ✓' : 'accept'}</button>
    <button className="t-btn">edit</button>
    <button className="t-btn danger" onClick={reject}>reject</button>
    <span className="moss-delta">{delta}</span>
  </>}>
  <ProposalDiff field={field} oldDesc={oldDesc} newDesc={newDesc} />
</ToolCall>
```

`accept` calls existing `useJob.acceptCandidate(jobId, fieldName)` — unchanged from M2C.

- [ ] **T14.3 — wire banner from App**

```tsx
const improveJob = useJob.runningImprove()
return (
  <Shell topbar={…} left={…} center={
    <>
      {/* normal chat */}
      <ChatPanel />
      {improveJob && <ImproveBanner job={improveJob} onOpen={() => scrollToToolCall(improveJob.toolCallId)} />}
    </>
  } right={…} />
)
```

- [ ] **T14.4 — verify & commit**

Trigger `/improve`. Banner pulses. Candidate cards render with diff strikethrough/highlight. Accept persists.

```bash
git add frontend/src/components/Improve frontend/src/components/Chat/MessageList.tsx frontend/src/index.css
git commit -m "feat(m7): improve banner + accept/reject candidate cards"
```

---

## Phase G — wrap

### T15: Final regression + roadmap update

- [ ] **T15.1 — run full test suite**

```bash
cd backend && uv run pytest -v
cd ../frontend && npx playwright test
cd .. && npm run -w frontend build
```

Expected: green on all three.

- [ ] **T15.2 — full-app screenshot for each scene**

Live-app capture flow against a real project (`invoices/` from existing dogfood data is fine):

| scene | how to reach |
|---|---|
| `default`        | open any project that already has chat history |
| `empty`          | create a fresh project (or switch to the empty `tax-forms/`) — should land on `<EmptyHero />` |
| `improve` run    | type `/improve` in default project; capture while banner is pulsing |
| `review`         | click any pending doc in tree → `<ReviewOverlay>` mounts |
| `eval`           | type `/eval`; capture after `<EvalCard>` renders |
| `publish_check`  | type `/publish`; capture stage `'check'` |
| `publish_key`    | click `mint key →`; capture stage `'key'` (key reveal) |

Save each as `docs/screenshots/2026-05-10-m7-<scene>.png`.

- [ ] **T15.3 — design-decisions.md sweep**

Walk through every entry from T0.1 + any new ones added during T1–T14. Each must be either ✅ Accepted (resolved with current implementation) or 🚨 Needs design review (waiting on next handoff). No 🟡 left dangling without rationale.

- [ ] **T15.4 — update `docs/superpowers/plans/ROADMAP.md`**

Add row:

```md
| **M7** — design handoff UI replacement | `2026-05-10-m7-design-handoff-ui.md` | ✅ shipped | `<commit-range>` (~14 task commits) |
```

Add a `### M7` section under "What each milestone delivers" mirroring the M6 entry style. Mention the dropped dark-mode toggle as an open follow-up.

Add follow-up rows under "Open cross-cutting follow-ups":
- **dark-mode revival** — currently light-only; design needs a dark palette pass before re-enabling toggle
- **schema sections** — review currently renders one synthetic section because backend schema has no `section` grouping; design shows multi-section. If we want sectioned review, schema model needs an optional `section` field
- **metrics tree section** — FS spine `metrics/` row deferred until eval history is exposed via `/lab/projects/:id/evals`

- [ ] **T15.5 — commit**

```bash
git add docs/superpowers/plans/ROADMAP.md docs/design-decisions.md docs/screenshots/
git commit -m "docs(m7): roadmap + decisions log + scene screenshots"
```

---

## Self-review checklist (run before handing off)

- [ ] Every CSS block from `index.html` between lines 11-503 has been ported into either `tokens.css`, `index.css`, or a component-scoped CSS file. Spot-check by `grep -c "^\\s*\\." docs/design/emerge-api/project/index.html` vs total selectors in `frontend/src` after T15.
- [ ] No `bg-canvas / bg-surface / bg-subtle / accent-primary` references remain (`grep -rln "bg-canvas\\|bg-subtle\\|accent-primary" frontend/src` → empty).
- [ ] No `useTheme / ThemeToggle / data-theme` references remain.
- [ ] All 7 design scenes render. The `twk-quick` scene switcher is for the prototype only; we don't ship it.
- [ ] `useChat / useDocs / useProjects / useSchema / useReview / useApiKey / useJob` stores were not modified beyond consumer updates. M7 is component-only.
- [ ] No new backend endpoints. Tree view, schema preview, metrics — all derived from existing `/lab/projects/:id` family.
- [ ] `docs/design-decisions.md` has an entry for every code-side deviation from the handoff (dark mode, synthetic sections, deferred metrics tree).

---

## Execution

Per user memory (`feedback_default_execution_mode.md`): default to subagent-driven execution after writing-plans. Spawning a fresh subagent per task with two-stage review.
