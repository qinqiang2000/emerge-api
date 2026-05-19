# Conversations as first-class; projects as emergent

## Context

Today every chat in emerge is forced into a project folder. The flow:

1. User lands on `/` (empty hero) and types a message or drops a file.
2. Backend mints a placeholder project `Chat-YYMMDD-HHMMSS` (chat/service.py:498-548) so events have somewhere to land.
3. The placeholder project shows up in `~/PROJECTS` sidebar from the first turn forward.

Two pains observed live:

- **Casual chats pollute the project list.** Any "what does emerge do?" or "read this screenshot for me" creates a phantom project the user must garbage-collect. M9.5 acknowledged this in its "Phase-2 candidates" punt list (Chat-* draft grouping, stale-Chat cleanup).
- **Rename mid-conversation is fragile.** When the agent decides to bind a chat to a real project name (`Chat-260519-071155` → `荣耀_欧洲1`), it has to navigate three things at once: rename slug, sync display name, keep pid_index consistent. The 2026-05-19 dogfood incident — agent used `Bash mv` → pid_index lagged → tombstone gate silently dropped half the conversation — is the direct symptom of this conflation.

The deeper issue: **a chat with an agent is a first-class thing, not always bound to a project.** Karpathy software-3.0: the agent is a colleague you can just talk to. A "project" is what a conversation crystallises into when there's enough material (docs, schema, extractions) that long-term organisation matters. Most conversations never reach that bar.

**Rule we want to enforce:** chats live in their own first-class storage. Promotion to a project is one explicit operation (user `/init` or agent `create_project` with intent), and that operation atomically relocates the chat's history + attachments into the project folder. The chat-history popover becomes scope-aware (project chats vs. unbound chats); the sidebar stays project-only.

Outcome: `~/PROJECTS` is curated. The agent-as-colleague space lives behind the existing chat-history popover + empty-hero recent strip — no new permanent sidebar surface. The `Chat-260519-071155`-style pollution stops at the source.

---

## Storage model

Two storage roots; same chat-log + attachment shape under each. Both already use the `_`-prefixed convention that `list_projects` filters out (projects.py:317).

| Layer | Path | Lifetime | Project anchor |
|---|---|---|---|
| **Unbound chat** (NEW) | `workspace/_chats/<chat_id>.jsonl` + `<chat_id>.meta.json` + `<chat_id>/attachments/` | Until user deletes or promotes | None |
| **Project chat** (UNCHANGED) | `workspace/<slug>/chats/<chat_id>.jsonl` + `<chat_id>.meta.json` + `<chat_id>/attachments/` | Project lifetime | `<slug>` |

`_chats/` is parallel to `_staging/` — system dir, naturally excluded from project enumeration. Same `safe_slug`/`safe_chat_id` validation rules apply.

Promotion is a single `os.rename` of the chat's per-conversation dir tree from `_chats/<cid>*` to `<slug>/chats/<cid>*`, executed inside the new project's lock. The chat's session-id sidecar (used for SDK resume) follows.

---

## Promote-on-intent (the key rule)

Promotion happens when — and only when — one of these fires:

| Trigger | Source |
|---|---|
| User types `/init` in composer | frontend → `POST /lab/chats/{cid}/promote` |
| User clicks "Promote to project" affordance on a conversation | frontend → same |
| Agent calls `create_project` from within an unbound chat | tool body detects parent chat is unbound; promotion runs as part of the create |

The first two are user-explicit. The third is the agent doing exactly what the user asked, e.g. "好的，开个项目叫 荣耀_欧洲1" → agent calls `create_project(name="荣耀_欧洲1")` → promote runs as a side effect of project creation.

**Hard rule (red line):** no other path promotes. `derive_schema`, `write_schema`, `extract_batch`, `promote_attachment_to_docs` all require an existing project; if invoked from an unbound chat they raise a structured error and the agent is told to ask the user before creating a project. This matches the existing AutoResearch red line ("never auto-promote") — the same SSU instinct: irreversible binds need explicit consent.

---

## Backend changes

Path-by-path, mostly additive. The biggest behaviour change is at `chat/service.py:498-548`: the empty-hero mint block becomes a no-op for the text-only path and a chat-attachment claim for the drop path.

### 1. New path helpers — `app/workspace/paths.py`
- `unbound_chats_root(workspace) → Path` (`workspace/_chats`)
- `unbound_chat_log_path(workspace, chat_id) → Path`
- `unbound_chat_meta_path(workspace, chat_id) → Path`
- `unbound_chat_attachments_dir(workspace, chat_id) → Path`

Existing project-chat path helpers untouched.

### 2. New `_chats_alive` check — `app/chat/log.py`
- Add `_unbound_chat_alive(workspace, chat_id) → bool` — returns True iff `_chats/<cid>.jsonl` exists or `_chats/<cid>/` exists. Used as the tombstone gate for unbound writes.
- Extend `append_event(workspace, slug, chat_id, event)` with a new behaviour: when `slug == _UNBOUND_SLUG` (a sentinel, e.g. `"_chats"`), route writes to `unbound_chat_log_path(...)` and use `_unbound_chat_alive` as the tombstone.
- Same dispatch for `read_chat_events`, `rewind_to_user`, `read_chat_session_id`, `write_chat_session_id`, `ensure_chat_meta`, `read_chat_meta`.

### 3. Sentinel slug — `app/chat/service.py`
- Add `_UNBOUND_SLUG = "_chats"` alongside the existing `_UNSET_SLUG = "p_unset"`. The two sentinels coexist during Phase 1:
  - `slug == "p_unset"` → **legacy** path. Keeps minting a placeholder project exactly as today. The existing frontend continues to work with zero changes.
  - `slug == "_chats"` → **new** unbound path. No project minted; events land in `_chats/<cid>.jsonl`. Used by the new Phase-1 HTTP routes (§8).
- Phase 2 frontend cutover migrates the empty-hero entry to use `_chats`; once no traffic uses `p_unset`, it (and the mint block keyed on it) can be retired in a follow-up.

### 4. Add unbound-slug branch — `app/chat/service.py:498-548`
- Leave the existing `slug == "p_unset"` mint block untouched (legacy behaviour stays alive for Phase-1 backward compat).
- Add a sibling `slug == _UNBOUND_SLUG` branch BEFORE it:
  - **Do not mint a project.** Write user event + every subsequent SDK event to `_chats/<chat_id>.jsonl` via `append_event(workspace, _UNBOUND_SLUG, chat_id, ...)`.
  - For staged attachments: claim into `_chats/<chat_id>/attachments/` via a new `claim_staged_to_unbound_chat(workspace, token, chat_id)` helper (parallels existing `claim_staged_to_chat`).
  - `attachments` items get `source="chat"` as before; the resolver dispatches on slug == `_UNBOUND_SLUG`.
  - Drop the `project_minted` SSE event in this path — there's no project to mint.

### 5. Image-block resolver — `app/chat/service.py:53-87 _load_image_blocks`
- When `slug == _UNBOUND_SLUG`, read attachment bytes from `unbound_chat_attachments_dir(workspace, chat_id) / filename`. Otherwise existing project-attachment path.

### 6. New tool — `app/tools/promote.py` + register in `tools/__init__.py`
- `promote_chat_to_project(workspace, chat_id, *, name, slug=None) → {slug, project_id}`
  - Derives slug from name (via `derive_slug`) unless explicit `slug` passed.
  - Calls `create_project(workspace, name=name, slug=slug)` to mint the project folder.
  - Inside the new project's `project_lock`:
    - `os.rename(_chats/<cid>.jsonl, <slug>/chats/<cid>.jsonl)`
    - `os.rename(_chats/<cid>.meta.json, <slug>/chats/<cid>.meta.json)` (if exists)
    - `os.rename(_chats/<cid>/, <slug>/chats/<cid>/)` (attachments dir; if exists)
  - Returns the new project's slug + pid.
  - Idempotent on partial state: if any of the source paths don't exist, skip silently.

### 7. `create_project` integration — `app/tools/projects.py`
- Add optional `from_unbound_chat_id: str | None = None` param. When set, after the project folder is created, run the same relocation as `promote_chat_to_project` (factor out a `_relocate_unbound_chat` helper). This is what an agent inside an unbound chat calls when the user says "OK, make it a project."
- The MCP `@tool` registration exposes the new arg so the agent can invoke it.

### 8. New HTTP routes — `app/api/routes/chat.py` (or a new `routes/unbound.py`)
- `POST /lab/chats` → `{chat_id}` — mint a fresh unbound chat id (no storage created yet; first event creates the jsonl).
- `GET /lab/chats` → list unbound chats: `[{chat_id, first_user_message, ts, attachment_count}]`. Reads `_chats/<cid>.meta.json` for titles.
- `GET /lab/chats/{cid}/events` → replay log (mirrors existing `GET /lab/chats/{pid}/{cid}`).
- `POST /lab/chats/{cid}/turn` → run a chat turn against the unbound chat. Same SSE shape as existing per-project turn; backend dispatches `slug=_UNBOUND_SLUG`.
- `POST /lab/chats/{cid}/promote` → body `{name, slug?}` → calls `promote_chat_to_project`. Returns `{slug, project_id}`.
- `DELETE /lab/chats/{cid}` → tombstone (unlink jsonl + remove attachments dir).

Existing per-project chat routes untouched. Authorization unchanged (none — this is single-tenant lab; same as today).

### 9. Skill update — `app/skills/emerge_extractor.md`
Add a new "Unbound chat" section near the top, before "Workspace layout":

> You are sometimes invoked from an **unbound chat** — a conversation without a project yet. You can tell by `CURRENT_PROJECT_DIR` being empty (or the system context saying "unbound chat, no project"). In unbound chats:
>
> - You CAN: answer questions, read images the user attached (via image blocks), look at the user's `_staging/` if they reference it, run `WebFetch` / `WebSearch` if approved.
> - You CANNOT: call `derive_schema`, `write_schema`, `extract_batch`, `promote_attachment_to_docs`, `pre_label`, or any tool that requires a project context. They'll raise `chat_not_bound`.
>
> When a user expresses project intent — e.g. "let's build a schema for these," "extract this batch," "make this a project" — first **ask** which name to use, then call `create_project(name=..., from_unbound_chat_id=<your chat_id>)`. The chat history + attachments move with the project. You then own a normal project context and can use the full tool kit.

### 10. Workspace-safety-gate scope — `app/chat/permissions.py`
- Allow Read/Write/Edit/Glob/Grep/Bash under `_chats/` (already covered by "inside workspace = allow", but confirm `_chats/` doesn't accidentally fall under `_is_project_root` for the new `mv` deny added in commit `fbfea62`).
- The `mv` deny treats `_`-prefixed dirs as non-projects, so this is already correct; add explicit test.

---

## Frontend changes

### 1. Routing — `App.tsx` + `lib/slugUrl.ts`
- New path: `/c/<chat_id>` for unbound chats. Parser: `readChatIdFromPathname`.
- Existing `/p/<slug>` path unchanged.
- Empty hero: `/` (no slug, no chat-id) is the landing. First user message:
  - With staged files OR without — mint a new unbound chat via `POST /lab/chats`, navigate to `/c/<cid>`, then send the first turn.
  - **No project minted.** The previous mint-on-first-message behaviour goes away.

### 2. Sidebar — `LeftSpine.tsx`
- **No new section.** Sidebar stays project-only. (We considered a `~/CONVERSATIONS` section here; it conflicted with the chat-history popover — same content, two surfaces. The popover is the chat-switcher; the sidebar is the project navigator. One affordance per concept.)

### 3. ContextSurface / chrome — main pane in `/c/<cid>` mode
- Hide `FSSpine` (no project = no filesystem to show). Or render a stub: "No project. Type `/init` to bind this conversation to a project."
- Chat panel + composer otherwise identical to `/p/<slug>` mode.
- Hero buttons (`/init`, "Build me a schema...", etc.) still render — `/init` now binds the existing chat instead of minting a fresh project on send.

### 4. `/init` slash command — `Chat/Composer.tsx`
- Existing `/init` keystroke already exists for project bootstrap. In unbound-chat mode it sends `POST /lab/chats/{cid}/promote` with the typed name (or asks for one inline). On success, navigate to `/p/<slug>`.

### 5. API client — `lib/api.ts`
- `createUnboundChat() → {chat_id}`
- `listUnboundChats() → ChatMeta[]`
- `getUnboundChatEvents(cid) → Event[]`
- `runUnboundChatTurn(cid, body) → SSE stream` (mirrors existing per-project)
- `promoteChat(cid, {name, slug?}) → {slug, project_id}`
- `deleteUnboundChat(cid) → void`

### 6. Chat-history popover — `Chat/ChatHistoryActions.tsx` (scope-aware)
The popover is the **only** chat-switcher surface. Its contents track the current route:

| Route | Popover lists | "New chat" creates |
|---|---|---|
| `/p/<slug>` | chats inside `<slug>` (existing behaviour, unchanged) | new chat in `<slug>` |
| `/c/<cid>` | other unbound chats | new unbound chat |
| `/` (empty hero) | recent unbound chats | new unbound chat (lazy — created on first send, not on button click) |

Implementation: extract the listing source into a small `useChatPopoverContents(route)` hook so the popover component itself doesn't branch. "New chat" CTA dispatches based on the same route bit.

### 7. Empty-hero "Recent conversations" strip — `EmptyHero.tsx`
- Above the tagline / example chips, render a single-row strip listing up to 5 most-recent unbound chats: `· <title> · <timeago> · ⌘1..5`. Click → `/c/<cid>`. "See all" link → opens the popover with the full list.
- Hidden entirely when there are no unbound chats yet (don't show empty state — the example chips already serve that purpose).
- Update tagline / examples to reflect that messages here start a conversation, not a project. Examples can still say "Extract invoices from these PDFs…" — that intent naturally leads to a `/init` later.

---

## Migration / cleanup

Existing `Chat-YYMMDD-HHMMSS` placeholder projects in user workspaces are real project folders today. Two options:

**Default — leave them.** They stay listed in `~/PROJECTS`; user can rename or delete via the existing tools. The new flow only governs net-new chats. No retroactive demotion.

**Optional one-shot script** — `scripts/demote_empty_chat_projects.py`:
- Walks `workspace/<slug>/project.json`.
- For each project where `name` matches `^Chat-\d{6}-\d{6}$` AND `docs/` is empty AND `predictions/` is empty AND no prompt edits beyond `pr_baseline` defaults AND no `versions/`:
  - Move chat history into `_chats/<cid>.*`.
  - Remove the project folder.
- Dry-run mode by default; user opts in to actually run it.

Per the project's `test_data_deletable` memory (pre-production), I lean towards skipping the migration script entirely — users can clean up manually if they want. The script is only worth writing if more than a handful of legacy `Chat-*` placeholders accumulate.

---

## Tests

### Update existing
- `tests/integration/test_chat_mint_from_staging.py` — split into two suites:
  - `test_p_unset_text_only_does_not_mint_project_anymore` (NEW: assert no project folder created, jsonl lives at `_chats/<cid>.jsonl`)
  - `test_p_unset_with_stage_token_lands_in_unbound_chat_attachments` (REPLACED: was-mint-project-and-claim-to-docs; now claims to `_chats/<cid>/attachments/`)
- `tests/unit/test_chat_log.py` — extend `append_event` test matrix with the unbound-slug branch.

### New
- `tests/unit/test_paths_unbound.py` — `unbound_chat_*` path helpers.
- `tests/unit/test_workspace_staging.py` — `test_claim_staged_to_unbound_chat_moves_and_dedupes`.
- `tests/unit/test_tool_promote.py` — `test_promote_chat_to_project_relocates_jsonl_meta_and_attachments`, `test_promote_chat_partial_state_idempotent`, `test_promote_chat_creates_project_with_given_name`.
- `tests/unit/test_tool_projects.py` — `test_create_project_with_from_unbound_chat_id_relocates_chat`.
- `tests/integration/test_chat_unbound_lifecycle.py` — create unbound → send turn → promote → assert `_chats/` empty + project has full history.
- `tests/integration/test_chat_routes_unbound.py` — full HTTP-level coverage of the new `/lab/chats` family.
- `tests/unit/test_emerge_only_permission.py` — `test_bash_mv_inside_unbound_chat_allows` (regression for the `_`-prefix not being a project root).

---

## Phasing

**Phase 1 — backend (one PR)**
- Sections 1–10 of "Backend changes" above. All tests landed.
- Old `p_unset` path normalises to `_chats` server-side; existing frontend keeps working with no visible change yet (because the empty-hero will still mint a project at the frontend layer until Phase 2). Internal sentinel rename only.

**Phase 2 — frontend (one PR, depends on Phase 1)**
- New `/c/<cid>` route, scope-aware chat-history popover, empty-hero "Recent conversations" strip, `/init` rebinding.
- Cuts over the empty-hero mint at the frontend; backend Phase 1 already supports both paths.
- Sidebar stays project-only — no new section.

**Phase 3 (optional)** — legacy cleanup script + INSIGHTS notes. Probably skip until users ask.

---

## Out of scope

- **Multi-conversation merge.** No "merge these two chats into one project."
- **Cross-project chat references.** A chat lives under one project (or none); no @-mentioning chats from a different project's chat panel.
- **Conversation sharing / export.** Out of band — handled by existing chat-log redactor + future export tooling.
- **Search across conversations.** `~/CONVERSATIONS` lists by recency; no full-text search of chat bodies in this milestone.

---

## Open questions

- **Naming.** "Unbound chat" is the working term in code. Alternatives considered: "scratch chat", "free chat", "conversation". UI surface text uses "conversation"; wire-level term (`_chats`, `_UNBOUND_SLUG`) stays as-is.
- **Should `/c/<cid>` show the project sidebar at all?** Probably yes — keeps "switch to a project" reachable in one click — but FSSpine pane (the project filesystem view) is hidden because there's no filesystem to show.
- **Auto-prune.** Should unbound chats older than N days auto-delete? Skip for now — workspace is per-user and small; nag-free is better.
