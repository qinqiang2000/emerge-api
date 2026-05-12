# Plan-input prompt — Chat History & New-Chat (M8 candidate)

> **What this file is.** This is a **briefing prompt** to be fed to
> `superpowers:writing-plans` (in a fresh session) to produce the actual
> milestone plan (`docs/superpowers/plans/2026-05-12-m8-chat-history.md`
> or whatever the next milestone number is — check `ROADMAP.md`).
>
> **Do not implement directly from this file.** First produce a plan, get
> user sign-off, then execute via `superpowers:subagent-driven-development`
> (the user's default — see auto-memory `feedback_default_execution_mode.md`).

---

## 1. Goal (one paragraph)

Replace the current **single-chat-per-project** model with **multiple chats
per project**, surfaced as a Claude-style **Chat history + New chat**
control pair at the **top-right** of the middle conversation column. Also
ship the two left-rail slimming tweaks the design adopts alongside (drop
per-row doc-count meta; show a status dot on the active project; collapse
all FS-tree directories except `docs/` by default). Implementation must
preserve M7.1's reload-restore behavior (chat events hydrate from the
server log on project entry) — the new flow simply lets the user switch
*which* chat is the active one within a project.

The design intent is captured verbatim in
`docs/design/emerge-api/chats/chat2.md` (a real designer↔designer-agent
transcript). Read it end-to-end before planning; the final user-confirmed
scope is the last two `## User` turns:

- **Issue 1 (chat history):** Two floating icon buttons at top-right of
  conv. ⏱ history opens a 280 px-wide popover listing the **active
  project's** sessions, **one line per row**: 54 px-wide mono kind tag
  (uppercase) / serif label / tabular-nums timestamp. Current chat
  highlighted with `--ochre-soft` background; on the active row the
  kind text shifts to `--ochre-2`. Header is just `history` (mono
  uppercase) on the left and the project name on the right — **no
  "N runs" count**. Switching project auto-closes the popover. Hidden
  in Review mode. `+ New chat` jumps to EmptyHero.
- **Issue 2 (left rail slim, options 1+2 only):** Strip `42 docs` meta
  from project rows; on the active row show a 6 px status dot
  (`live=--moss / draft=--ochre / empty=--ink-5`). FS tree opens only
  `docs/` by default; `reviewed/`, `versions/`, `metrics/` collapse to one
  line with their count and toggle on click.
- **Issue 3 (multi-document-type / "not just invoices") is out of scope
  for this milestone** — the design conversation discussed it but the
  user chose to do only Issues 1 & 2.
- **Revision 2 (2026-05-12 09:08, latest):** popover content was further
  slimmed and **vocabulary made task-type-agnostic** — see §1a below.

## 1a. Task-type-agnostic design (durable constraint, not milestone-local)

The most recent user turn in `chat2.md`:

> 历史记录 弹框 内容有点多。后续希望本设计能复用到其他非文档提取类
> 任务，比如文档匹配等等，但API发布是通用。所以希望少一点文档提取
> 专用的设计，多一点通用的

What this means for **this milestone**:

- **Kind taxonomy is now generic verbs**: `init | run | tune | review | publish | ingest` (was `init | extract | improve | review | publish | ingest`).
  - `run` covers any task execution (extract today; match / classify / score tomorrow).
  - `tune` covers any optimization loop (`/improve` today; future tunable pipelines).
  - `init / review / publish / ingest` were already generic and stay.
- **Row schema**: drop `summary` entirely. A row is `{id, kind, label, ts}` — that's it. The backend metadata sidecar (`{chat_id}.meta.json`) drops the `summary` field too; only `{label, kind, created_at, sdk_session_id}` is persisted. This sidesteps the redactor question for summaries (no summary is generated, so nothing to redact in that path).
- **Labels are short, present-tense verb phrases** without doc-type nouns ("tune weak fields", "run batch", "draft v3"). The data fixture in `data.jsx` is the worked example.
- **Empty state** is the bare `No sessions yet.` (was a 2-line invoice-flavored hint with `/init` callout).
- **Header copy** is `history` (mono uppercase) instead of italic-serif `chat history` — sectiony, not chatty.

What this means **beyond this milestone** (informs all future UI plans):

- Avoid surfacing the word "extract" / "extraction" / "invoice" / "document" in chrome that the user sees outside of doc-specific scenes (FS spine `docs/` folder is fine — that's a real path; popovers, buttons, empty states, slash-menu copy is not).
- When introducing a new task type later (e.g. **matching**), the chrome should accommodate it by reusing the same kind chips, the same chat shell, the same publish/key flow — only the *content* changes.
- Per `CLAUDE.md` (Engineering, just added): "UI vocabulary is task-type-agnostic; reserve doc-extraction-specific terms for content/help text, not chrome."

## 2. Design source-of-truth (read these first)

| Path | Why |
|---|---|
| `docs/design/emerge-api/chats/chat2.md` | Full design intent + user's final scope cut |
| `docs/design/emerge-api/project/pieces.jsx` lines 91–207 (`FSSpine` + `ConvHeader`) | Reference React for the new pieces — mirror props and class names, don't import |
| `docs/design/emerge-api/project/data.jsx` lines 239–266 (`SESSIONS`) | Per-project sessions data shape — informs the *display* model only (the backend may store more or less) |
| `docs/design/emerge-api/project/index.html` lines 108–138 (`.conv-hd`, `.hist-pop`) | All the new CSS — copy verbatim into the appropriate frontend CSS file, do **not** translate to Tailwind utility classes (CLAUDE.md: no Tailwind color classes; tokens already used here) |
| `docs/design/emerge-api/project/app.jsx` line 121–123 | `<ConvHeader>` mount point: only when `scene !== 'review'` |

The handoff's own rules of engagement:
`docs/design/emerge-api/project/handoff/CLAUDE.md` (kept locally, not in
the latest design tarball — still the operative contract).

## 3. Current state (what already exists — do NOT rebuild)

### Backend
- `backend/app/api/routes/chat.py:67-72` — `GET /lab/chats/{project_id}/{chat_id}` returns `{events: [...]}` for **one** chat.
- `backend/app/chat/log.py` — append-only JSONL writer, replay reader, SDK-session-id sidecar (`{chat_id}.meta.json`).
- `backend/app/workspace/paths.py:40-45` — `chats_dir(workspace, pid)` → `workspace/p_*/chats/`; meta path → `{chat_id}.meta.json`.
- `backend/app/api/routes/_safety.py` — `safe_chat_id`, `safe_project_id` validators (already imported by the chat route).

### Frontend
- `frontend/src/stores/chat.ts:13-41` — `localStorage` key `emerge.chatId.<pid>` holds the **single** persisted chatId per project; `chatIdFor(pid)` mints + persists on first access.
- `frontend/src/stores/chat.ts:59-94` — `enterProject` (binds chatId, hydrates events, handles in-flight tail race — keep this race-safety pattern intact when extending).
- `frontend/src/components/Chat/ChatPanel.tsx:87` — `<div className="conv-scroll">` is the column the new `ConvHeader` floats above.
- `frontend/src/components/Spine/FSSpine.tsx:117-126` — current project row renders `meta` (the `42 docs` text to remove); also the place to add the status dot and the dir-collapse logic.

## 4. Gap analysis — what the plan must add

Use this as a **scope checklist**, not a step ordering. The planner
should sequence and split into Tasks; numbers below are coverage, not
phase boundaries.

### 4.1 Backend
- **List chats**: `GET /lab/chats/{project_id}` → `[{chat_id, label, kind, ts_iso, n_events}]` sorted desc by `ts_iso`. Source of truth = directory scan of `chats/c_*.jsonl` (plus meta sidecar). 404 only on bad project id; empty project returns `[]`. **No `summary` field** — design dropped it in revision 2 (see §1a).
- **Chat metadata storage**: extend `{chat_id}.meta.json` (currently only `sdk_session_id`) with `{label, kind, created_at}` — **no `summary`**. Decide:
  - **Recommended default**: derive `kind` from the **first user message** using a slash-command map keyed on the **generic verb taxonomy**: `/init → init`, `/extract → run`, `/improve → tune`, `/eval → run`, `/publish → publish`, `/review → review`, otherwise `chat`. Note the mapping is **slash-cmd → generic-kind**, not 1:1 — `extract` and `eval` both produce a "run" because in a non-extraction future they will be the same task-execution semantics; the planner should resist the temptation to add a `kind:'extract'` just because the slash-cmd is named that. Derive `label` from the first user message (truncate to ~40 chars, strip leading `/cmd`, prefer present-tense verb phrase). Persist on chat creation; do not rewrite on every append.
  - Alternative (simpler): list endpoint just returns chat_id + first/last event timestamps and lets the frontend derive labels from the event stream — but this means listing N chats triggers N reads. Reject unless N is bounded.
- **Delete chat (optional, ask user first)**: not in the design but a natural follow-up. The plan should **defer** unless the user asks during planning.
- **No new safety surface** beyond reusing `safe_chat_id` / `safe_project_id`. Since no summary is generated/stored, no new path through `chat/redactor.py` is required for the chat-list endpoint (the per-chat replay endpoint already redacts).

### 4.2 Frontend store (`stores/chat.ts`)
- Replace the single-chatId-per-project localStorage scheme with **(activeChatId per project, plus the list of known chatIds)**. Keys:
  - `emerge.activeChatId.<pid>` (string — replaces `emerge.chatId.<pid>`; **migrate on read**: if old key exists and new doesn't, copy then remove).
  - Chat list itself is **server-authoritative** — fetched, not cached in localStorage. The store may cache the most recent list in memory for the popover.
- New actions:
  - `listChats(pid) → Promise<ChatSummary[]>` (fetches and stores in `chatsByProject[pid]`).
  - `switchChat(pid, chatId)` — set `activeChatId`, clear `events`, hydrate from server. Reuse the existing in-flight-tail race-safety pattern from `enterProject` (`prefixLen` snapshot + dispatch-vs-apply check).
  - `newChat(pid)` — mint a fresh `chatId`, persist as active, **do not** write anything server-side yet (server side comes into being on first `/lab/chat` POST, same as today). UI flips to EmptyHero.
- `enterProject` keeps the same shape but reads `emerge.activeChatId.<pid>` (with the migration).
- Preserve **M7.1 invariants** (see `docs/design-decisions.md` 2026-05-11 entry): create-project-from-EmptyHero adoption logic; in-flight tail preservation; pure `reduceEvents`.

### 4.3 Frontend UI
- **New `ConvHeader` component** (`frontend/src/components/Chat/ConvHeader.tsx`): the two icon buttons + popover. Port the JSX/markup verbatim from `pieces.jsx` lines 109–207, converted from JS → TSX:
  - Props: `{ activeProject: string; onNew: () => void; onSwitch: (chatId: string) => void; currentChatId: string }`.
  - Close on outside-click and `Escape` (already coded in the reference).
  - Auto-close on `activeProject` change (`useEffect` on the prop).
  - Hidden when `scene === 'review'` — gate at the parent (`ChatPanel.tsx`), not inside `ConvHeader`.
- **CSS port**: copy `.conv-hd`, `.hist-pop`, `.hist-pop .h-*`, and the `.conv > .conv-scroll { padding-top: 54px }` rule into `frontend/src/index.css` (or wherever conv styles live — confirm during planning). All tokens (`--ink`, `--paper`, `--ochre-soft`, etc.) already exist; do not introduce new ones.
- **`FSSpine` updates** (`frontend/src/components/Spine/FSSpine.tsx`):
  - Remove the `<span className="meta">{meta}</span>` on each project row.
  - On the active project row, render the status dot — color from a `STATUS_DOT` map (live/draft/empty). **Open question for the planner**: where does `status` come from? Backend `GET /lab/projects` currently does not return one. Recommended derivation: `live` if the project has any `versions/v*.json` with an `active` marker (or `active_version_id` set); `draft` if `schema.json` exists; `empty` otherwise. Plan a backend additive field rather than computing in the FE.
  - Group the flat `TREE` array by directory and gate non-`docs/` directories on a `useState`-managed `openDirs` map (`{ 'docs/': true }` default). The grouping logic in `pieces.jsx:97-107` is the reference.

### 4.4 Tests
- Unit (backend): list endpoint returns chats sorted desc; empty list for project with no chats; safety check rejects traversal in `project_id`.
- Unit (frontend): `listChats` reducer; `switchChat` race safety (extend the existing `chat-hydrate.test.ts` pattern); `newChat` doesn't touch server before first send.
- e2e: open Chat history popover; switch chats; create new chat from popover button; status dot color matches project status; FS-tree collapse default.

## 5. Constraints (CLAUDE.md hard rules)

Quoted because the planner is in a fresh session and will not have read CLAUDE.md yet:

- **No image few-shot**, no bbox / region info, **no Tailwind color classes** — use semantic CSS-var tokens only (palette already in `index.css`).
- **`schema.json` only via `write_schema` tool** — irrelevant to this milestone but a red line.
- **Agent brain (SDK) vs Extract LLM are separate** — also irrelevant here; the chat-log surface is the SDK-brain side.
- **Public API path is `versions/v{active_version_id}.json`** — also irrelevant; this milestone is lab-side only.
- **Secrets hygiene**: chat logs already pass through `chat/redactor.py` on append (`scrub_chat_logs.py` exists for backfill). Confirm at plan time that no new write paths bypass the redactor. If a new write path is added (e.g. label/summary derived from user messages), it must reuse `chat/redactor.py` or document why it doesn't need it.
- **Single schema truth**: `backend/app/schemas/schema_field.py` — not touched here.

## 6. Recommended defaults the planner should propose (then ask the user)

These are decisions the planner should **make a call on with rationale**,
not enumerate as a menu (per CLAUDE.md collab principle):

1. **Where chat metadata is stored**: extend the existing `{chat_id}.meta.json` sidecar with `{label, kind, created_at}` alongside `sdk_session_id`. Set once on chat creation (first POST to `/lab/chat`); no rolling-summary regeneration.
2. **Kind taxonomy (generic verbs, locked)**: `init | run | tune | review | publish | ingest | chat`. *Do not* add `extract` or `improve` even though slash-commands of those names exist — the mapping is intentionally many-to-one so non-extraction task types (matching, classification, scoring) reuse the same chip set. See §1a.
3. **Project status field**: add `status: 'live' | 'draft' | 'empty'` to the `GET /lab/projects` response (additive, no FE breakage). Derive on the backend from `versions/`+`schema.json` presence.
4. **localStorage migration**: read-on-init, copy `emerge.chatId.<pid>` → `emerge.activeChatId.<pid>`, leave the old key in place for one session, no UI for clearing. Pure additive — old build keeps working if rolled back.
5. **Empty-state copy**: literal `No sessions yet.` (was changed in revision 2 from a multi-line `/init`-flavored hint; the new short form is task-type-agnostic).
6. **Active-chat detection in popover**: the chat whose id matches `useChat.getState().chatId` gets `.active` styling. No server flag needed.

## 7. Out of scope (do NOT plan these here)

- Issue 3 from `chat2.md` — document-type generalization at the **data-fixture / sample-project level** (multi-type sample data). Track separately. **Note**: the *chrome-level* genericization (kind taxonomy, copy) is **in scope** for this milestone — see §1a; only the sample-data-side generalization is deferred.
- Chat **deletion** / rename — not in the design. If raised during plan review, add as a follow-up entry to `ROADMAP.md` cross-cutting follow-ups, not a Task.
- Chat **search** — not in the design.
- Chat **export** — out.
- Anything about Tailwind dark-mode tokens for the new popover beyond what `--ink/--paper/--ochre-soft` already cover in both themes (verify token values during planning).
- The current `2026-05-12-e2e-suite-repair.md` plan — independent track.

## 8. Verification protocol (template for the plan to fill in)

Same shape as M7.2 (`docs/superpowers/plans/2026-05-11-m7-2-metrics-panel.md`, §"Live verification protocol"). Reminders:

- `cd backend && uv run pytest -v` (backend unit) and `cd frontend && npx vitest run` (frontend unit) MUST pass before each commit.
- `cd frontend && npm run build` MUST pass on the last commit.
- **chrome-devtools-mcp live check** against `:5173` for: history popover open/close (outside-click, Escape, project-switch auto-close), new-chat → EmptyHero, status dot color on `live`/`draft`/`empty` projects (seed states explicitly), FS-tree directory toggle.
- **e2e** (`cd frontend && npm run e2e`) — add a `chat-history.spec.ts` covering the popover + switch-chat happy path. e2e currently uses test-mode backend stubs; if the chat-list endpoint isn't in the stub, plan a small harness extension.
- Screenshots: `docs/screenshots/2026-05-12-m8-chat-history-{empty,multi,switch}.png` (paths the plan should pre-name).

## 9. After the plan is written

The planner must, as the final step of `superpowers:writing-plans`:

1. Add a milestone row to `docs/superpowers/plans/ROADMAP.md` (Status table + "What each milestone delivers" section).
2. Append a 🟡 Pending entry to `docs/design-decisions.md` describing the new ConvHeader + chat-list shape and citing this prompt file.
3. Resolve (mark ✅ or 🔄) the 2026-05-11 "Chat history survives page reload" entry — it's the predecessor and is superseded in spirit by multi-chat, even though the per-project chatId persistence still applies.

---

## Appendix A — Verbatim user scope statement (from chat2.md)

> 好。只实现
> - 问题1
> 方案：中栏顶部增加claude design的 两个图标，Chat History和New 插图，如图。 只显示当前 active 项目有关的history
> - 问题2
> 左侧栏信息瘦身，取你上面该问题方案的 1，2

And the follow-up correction:

> 中栏顶部图标 + 历史：这个放到右上角，而不是左上角

(The CSS in `index.html` reflects this: `.conv-hd { position:absolute; top:10px; right:14px; }`.)

## Appendix B — Revision 2 user statement (from chat2.md, latest turn)

> 历史记录 弹框 内容有点多。后续希望本设计能复用到其他非文档提取类
> 任务，比如文档匹配等等，但API发布是通用。所以希望少一点文档提取
> 专用的设计，多一点通用的

Translation for the planner: the history popover was too dense, and more
importantly **this whole UI shell needs to host non-extraction task types
later (e.g. document matching)**. API publish stays universal. Favor
generic UI vocab over extraction-specific. The kind taxonomy shift
(`extract→run`, `improve→tune`) is one concrete consequence; see §1a for
the full implications.
