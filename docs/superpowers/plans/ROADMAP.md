# emerge implementation roadmap

> The chain of milestones. Spec for the design is `../specs/2026-05-08-agent-native-design.md`.
> Each milestone is a self-contained plan that produces working software.
>
> **Always read this file before starting a plan** so you know what comes after.

## Status

| Milestone | Plan file | Status | Range |
|---|---|---|---|
| **M1** — walking skeleton (chat → derive_schema → extract) | `2026-05-08-m1-walking-skeleton.md` | ✅ shipped | `27bd99f..7a86489` (40 tasks) + `6979163` (path traversal fix) |
| **M1 polish** — OAuth/proxy + Gemini + security allowlist + UX | (no plan; in-session fixes) | ✅ shipped | `fb14031..ecb955f` (8 commits) |
| **M2A** — reviewed examples + review mode UI | `2026-05-09-m2a-reviewed-examples.md` | ✅ shipped + dogfooded | `f85e929..8bc8b70` (24 commits) |
| **M2B** — eval (score + /eval) | `2026-05-09-m2b-eval-score.md` | ✅ shipped | `bad20f5..b8b0811` (23 commits) |
| **M2C** — autoresearch + /improve | `2026-05-09-m2c-autoresearch.md` | ✅ shipped | `361f30f..e87b0df` (23 commits, incl. T21 smoke fixes) |
| **M3** — publish + prod fast-path + API key | `2026-05-09-m3-publish.md` | ✅ shipped + dogfooded | `adf7ef9..e03b5b2` (16 commits, T17 smoke ran live `/publish v1`+`v2` on `us-invoice`, no commits) |
| **M4** — polish + dark mode + export bundle | `2026-05-09-m4-polish.md` | ✅ shipped | `1d95e5f..1e48a3b` (21 commits) |
| **M5** — UX papercut bundle (useJob isolate + schema invalidate + multi-entity + click-to-page) | `2026-05-09-m5-ux-papercut.md` | ✅ shipped | `d244f12..eb978b8` (17 commits, T9 scope-reduced, T14 also fixed pre-existing ReviewMode infinite-rerender) |
| **M6** — agent sandbox + secret hygiene (allowlist enforce + API key redaction) | `2026-05-10-m6-agent-sandbox-secret-hygiene.md` | ✅ shipped | `4f3c40f..d9c6452` (11 commits, history scrubber cleaned 2 leaked entries from M3 dogfood jsonl; 2 real-LLM tests skip-by-default behind `EMERGE_REAL_LLM=1`) |
| **M7** — design handoff UI replacement | `2026-05-10-m7-design-handoff-ui.md` | ✅ shipped | `5080ff0..fcf9369` (~14 task commits) |
| **M7.1** — design-handoff wiring & polish (post-M7 verification fixes) | `2026-05-11-m7-1-handoff-wiring-fixes.md` | ✅ shipped | `576089f..81bd62d` (9 task commits) |
| **M7.2** — metrics panel (`/eval` → right-rail `metrics/`) | `2026-05-11-m7-2-metrics-panel.md` | ✅ shipped | `2c9b798..eb2fc61` (6 task commits) |
| **M8** — chat history + new-chat + left-rail slim | `2026-05-12-m8-chat-history.md` | ✅ shipped | `113f792..2fb545d` (12 commits; T2 also relaxed 2 chat-session-continuity assertions, T10 also unblocked `GET /lab/chats/{pid}` under `EMERGE_TEST_MODE=1`) |
| **M9.0** — schema quick-look (read-only sheet from FSSpine + ContextSurface) | `2026-05-12-m9-0-schema-quicklook.md` | ✅ shipped | `848cb8f..65dd377` (15 commits; T4 widened frontend `SchemaField` to match backend pydantic; T13 live-verify caught + fixed `schema`→`fields` remap in `?shape=fields`; Gemini schema-alignment filed under M9a follow-up) |
| **M9a** — schema first-class (workspace-global `schemas/<sid>/`, project references `sid`) | TBD | 🔮 proposed | — |
| **M9b** — schema fork (clone-at-fork-time + lineage row in Quick-look) | TBD; blocked by M9a | 🔮 proposed | — |
| **M9c** — schema A/B compare (multi-schema per project, per-schema eval columns) | TBD; blocked by M9a | 🔮 proposed | — |
| **M9d** — autoresearch UI (review notes → proposed description tweaks; closes description-vs-notes confusion) | TBD | 🔮 proposed | — |

## What each milestone delivers

### M2C — autoresearch + /improve

**Goal:** the user types `/improve`, the agent loops `max_turn` times proposing schema description tweaks, scoring against reviewed, picking the best candidate. Output is a candidate ProjectVersion under `versions/_candidate/{job_id}/`; user must explicitly accept (no auto-promote, per spec red line).

**Scope:**
- `emerge-autoresearch` SKILL.md (loaded on `/improve`)
- JobRunner: asyncio queue + JSONL event stream + pause/resume/cancel
- Background tool calls: `start_job(skill, params) → job_id`, `tail_job(job_id)` (SSE), `pause_job/resume_job/cancel_job`
- Counterexample regression set (from `_notes` in reviewed) feeds proposer LLM
- Frontend: streaming progress UI in chat (per-turn F1 update), pause button while job running
- Spec deferred items to fold in: type-derived field controls (FieldEditor), `_source_page` evidence trace, inline `_notes` UI, multi-page PDF probe (already done in M2B), `_evidence` round-trip on review save

**Tech notes:** proposer LLM uses provider adapter (separate from agent SDK). Default proposer model = same as extract_model. Bound by `max_turn` (e.g. 30) and `early_stop_no_improvement` (e.g. 5). No token / $ budget — lab side per spec §4.4.

### M3 — publish + prod fast-path + API key

**Goal:** `/publish` freezes a `versions/v{n}.json`, issues an API key, and serves `POST /v1/{pid}/extract` as a deterministic fast-path (no agent loop, just provider call).

**Scope:**
- `emerge-publish` SKILL.md (loaded on `/publish`)
- Tools: `freeze_version`, `readiness_check`, `contract_diff`, `issue_api_key`
- Prod fast-path FastAPI router on `/v1/{pid}/extract` — auth via per-project API key from `workspace/_keys.json` (hashed)
- One-time API key reveal modal in chat
- case2 entry: client feedback adds field → propose schema diff → user accepts → re-extract → save_reviewed → /eval → /publish v2 (additive contract diff passes)
- Backward-compat contract diff: added fields ok; removed/type-changed/enum-narrowed → reject

### M4 — polish

**Goal:** what's left before merge.

**Scope:**
- Dark mode aligned with Anthropic palette
- Real-LLM smoke CI (cheap model, warn-only)
- Tool-failure UX (red card, retry, error_code copy)
- Export bundle: `schema.json` + `curl` example + `readme.md`
- Verify inline comments → autoresearch hint loop end-to-end
- Address remaining minors from M2A/M2B reviewer reports

### M5 — UX papercut bundle

**Goal:** absorb four follow-ups deferred from M4 — `useJob` per-`jobId` isolation, ReviewMode schema cache invalidated by chat events, multi-entity `score()` / `readiness` / `FieldEditor`, and click-a-field-to-jump-to-page in ReviewMode.

**Scope:** see `2026-05-09-m5-ux-papercut.md`. No new spec scope; closes follow-ups #1, #2, #3, #8 from "Open cross-cutting follow-ups".

### M6 — agent sandbox + secret hygiene

**Goal:** close two hosted-readiness blockers from M5 dogfood — SDK built-in tools escaping the `mcp__emerge_tools__*` allowlist and plaintext API keys leaking into `chats/*.jsonl`.

**Scope:** see `2026-05-10-m6-agent-sandbox-secret-hygiene.md`. Closes the 🚨 critical follow-up filed 2026-05-10 plus the M3-era plaintext API key follow-up.

### M7 — design handoff UI replacement

**Goal:** replace the ad-hoc Tailwind palette with the full Anthropic design-handoff token system and rebuild every screen to spec — new CSS token layer, semantic ink/paper/ochre/moss/rose palette, editorial typography (serif body + mono chrome labels), new 3-col shell, all ReviewMode / Chat / Publish / Improve components rebuilt or migrated.

**Scope:**
- T0: contract setup — `docs/design-decisions.md`, `docs/superpowers/plans/2026-05-10-m7-design-handoff-ui.md`
- T1: token rewrite — `frontend/src/theme/tokens.css`, `tailwind.config.js`; dark-mode toggle dropped (no dark palette in handoff)
- T2: Shell layout — 3-col `AppShell`, `Topbar`, `ErrorBoundary`
- T3: Turn + conv — `AgentMessage`, `UserBubble`, `MessageList`, `ConvColumn` conv-column scroll
- T4: ToolCall + ToolRow + ProposalDiff — new pill/inline rendering for tool calls and schema-diff proposals
- T5: Composer + SlashMenu — new composer bar with slash-command popover
- T6: FSSpine — filesystem spine with docs/versions/metrics tree (metrics deferred)
- T7: ContextSurface — right column context card (schema / eval metrics / docs tabs)
- T8: EmptyHero — landing hero for empty project state
- T9: HelpPopover — keyboard shortcuts popover
- T10: Review overlay shell + ReviewBar — full-screen review overlay triggered from topbar
- T11: Review fields — `Section`, `FieldRow`, `ObjectField`, `ArrayField`, `JsonView`, `FieldEditor` multi-entity nav
- T12: EvalCard — inline eval result card in chat thread
- T13: Publish stage — readiness check + API key reveal inline chat cards
- T14: Improve banner + candidate cards — running banner + `ProposalCandidateCard` turn-level accept
- T15: legacy-token sweep + ROADMAP closeout (this commit)

**Design decisions deferred:** dark palette revival, schema section grouping, metrics tree API, per-field accept in /improve, publish stage overlay, object/array sub-shape, per-field confidence, PDF↔field bidirectional binding.

### M7.1 — design-handoff wiring & polish (post-M7 verification fixes)

**Goal:** close the gaps surfaced when the M7 scenes were verified live on 2026-05-11 — structured result cards (`EvalCard`, `PublishStage` checklist) silently fall back to plain tool pills because their adapters don't match the real tool output; the publish panel labels a raw `project_id`; the key-reveal card has stray Chinese labels; the improve job card under-communicates; the `/publish` agent hits a `Skill` tool error.

**Scope (see `2026-05-11-m7-1-handoff-wiring-fixes.md`):**
- T1: backend `t_score` must emit `json.dumps(...)` not `str(dict)` — the Python repr breaks the frontend `JSON.parse` so `EvalCard` never renders (root cause of the missing eval card)
- T2: `adaptReadiness` / `adaptScoreResult` robust to string `tool_result`; humanize readiness `key`→`label`
- T3: `PublishStage` eyebrow shows project *name* not `project_id`
- T4: english-only labels in the key-reveal card
- T5: `JobProgressCard` shows baseline + delta; allow accept-best-turn after cancel; never offers a regression
- **T6: retire `ProposalCandidateCard` — autoresearch accept is turn-level, not per-field** (the per-turn macro F1 is the unit of "did this help"; a turn-N description was scored in turn N's full-schema context). Closes the "per-field accept in /improve" follow-up by deciding *against* it.
- T7: stop the agent re-emitting eval / readiness results as markdown tables — the UI cards are canonical
- T8: diagnose & fix the `Skill ERR` on `/publish` (investigation task)
- T9: design-decisions log + this roadmap closeout

**Decisions affirmed (no change):** publish stage stays inline (not the full-conv-column overlay) — keeping conversation context visible wins; `mint key →` stays agent-mediated; `new project…` deselecting to the empty hero is the intended create flow.

**Spun out to M7.2 (not in M7.1):** `/eval` result → right-panel `metrics/` section (needs a tiny read endpoint + `useEval` store); "preview what turn N changed before you accept it" diff on the job-card accept affordance (needs the autoresearch turn event to carry the per-turn schema delta; reuses the retained `ProposalDiff.tsx`).

### M7.2 — metrics panel (`/eval` → right-rail `metrics/`)

**Goal:** wire the placeholder `metrics/` section in `ContextSurface`'s right rail to real eval data. The `score` tool was already persisting `metrics/eval_*.json` snapshots; this milestone added the read path.

**Scope (see `2026-05-11-m7-2-metrics-panel.md`):**
- T1: backend `GET /lab/projects/:id/evals/latest` reads the lex-last `metrics/eval_*.json`, round-tripped through `ScoreResult` for shape enforcement. 404 with `eval_not_found` when no snapshot on disk.
- T2: `useEval` Zustand store mirrors `useSchema` (cache-first `load`, force `refresh`, `invalidate`, `reset`). `projectId in byProject` cache check so a 404→null result is "cached, do not re-fetch".
- T3: `ContextSurface` derives macro precision/recall as means of `per_field`, reads `macro_f1` directly, `coverage = n_reviewed / n_docs`. Empty state "no eval yet — type /eval in the chat". Removed `PLACEHOLDER_METRICS` and the `metrics … placeholder` console log.
- T4: `useChat.handleToolResult` calls `useEval.refresh(pid)` after a successful `mcp__emerge_tools__score`, so the rail updates in the same SSE turn as `<EvalCard>`.
- T5: live-verified on `us-invoice` via chrome-devtools-mcp (rail's macro F1 = inline `<EvalCard>`'s overall F1, no placeholder log).
- T6: design-decisions ✅ entry resolving the 2026-05-10 placeholder-data 🟡, this roadmap closeout.

**Spun out / still open:** FSSpine `metrics/` tree row (different surface), per-turn-diff preview on `accept turn N` (the original M7.1 → M7.2 candidate that the metrics panel work crowded out — still in the open follow-ups list).

### M8 — chat history + new-chat + left-rail slim

**Goal:** replace the single-chat-per-project model with multiple chats per project, surfaced as a Claude-style "Chat history + New chat" chip pair at the top-right of the conversation column; ship the two adopted left-rail tweaks (drop per-row doc-count meta + status dot on the active project; collapse all FS-tree directories except `docs/`).

**Scope (see `2026-05-12-m8-chat-history.md`):**
- T1-T2: backend — `{chat_id}.meta.json` sidecar extended with `{label, kind, created_at}` (merge-aware writes; set once on the first turn); `GET /lab/chats/{project_id}` chat-list endpoint (directory scan, newest-first, legacy-log fallback). Kind taxonomy is the locked generic-verb set `init | run | tune | review | publish | ingest | chat` (slash-cmd → kind is many-to-one: `/extract` and `/eval` both → `run`; attachments on turn 1 → `ingest`).
- T3: backend — additive `status: live | draft | empty` on `GET /lab/projects`.
- T4-T5: frontend store — `chatsByProject` (server-authoritative, in-memory) + `listChats / switchChat / newChat`; localStorage key migration `emerge.chatId.<pid>` → `emerge.activeChatId.<pid>` (copy-forward, old key left for one session); chat list refreshed after every completed send.
- T6-T8: frontend UI — conv-header / history-popover CSS ported verbatim from the design handoff; `ConvHeader.tsx` (floating chips + popover, outside-click/Escape/project-switch close); mounted in `ChatPanel` (real project selected; auto-hidden in review mode since `ChatPanel` isn't rendered there).
- T9: `FSSpine` — drop the `meta` doc-count span; 6 px status dot on the active project row; FS tree grouped by directory with only `docs/` open by default (`reviewed/` / `versions/` collapse to one line + count, toggle on click); trailing root files (`schema.json`, `README.md`) stay visible.
- T10: e2e — seeded chat log + `chat-history.spec.ts` (popover lists sessions, switch round-trips, new-chat → events cleared, status dot, FS-collapse). Also unblocks `GET /lab/chats/{pid}` under `EMERGE_TEST_MODE=1` by registering the real chat router alongside the stub (registration order keeps the stub on `POST /lab/chat`).

**Decisions affirmed / out of scope:** no chat deletion, rename, search, or export (not in the design — if raised, add as a cross-cutting follow-up). The chrome-level genericization (kind taxonomy, popover copy) is in scope; the sample-data-level document-type generalization (chat2.md "Issue 3") stays deferred. No `summary` field anywhere (design revision 2 dropped it) — so no new redactor path.

### M9.0 — schema quick-look

**Goal:** the user clicks `schema.json` or `versions/v{N}` in FSSpine, or the `schema.json` card title / `+ N more` row in the right rail, and a read-only modal sheet opens showing the full schema as field cards (default tab) or pretty-printed raw JSON (second tab). Esc / scrim / ✕ closes it.

**Scope (see `2026-05-12-m9-0-schema-quicklook.md`):**
- T1-T2: backend — `GET /lab/projects/{pid}/schema/raw` (pretty-printed text/plain) and `GET /lab/projects/{pid}/versions/{vid}/raw[?shape=fields]`. The `?shape=fields` route normalises `publish.py`'s frozen-blob `schema` key to the spec-§3.3 `fields` key (live-verify discovery; backend is the wire-format adapter so `publish.py` and existing version files are untouched).
- T3: `useQuickLook` Zustand store with `{ kind, pid, versionId? }` target + lazy `loadRaw()` + stale-target guard.
- T4-T7: `FieldCard` (recursive, examples/enum/required pill/notes-hint slot), `FieldsTab`, `RawJsonTab`, `QuickLookHeader` (active/frozen/draft badge + lineage placeholder). T4 also widened `frontend/src/stores/schema.ts` `SchemaField` to match the backend pydantic model (added optional `required` / `examples` / `children`).
- T8: `SchemaQuickLook` portal wrapper — esc / scrim / ✕ close, project-switch auto-close (via Zustand `subscribe` for sync close), tab switch.
- T9-T10: entry-point wiring in `ContextSurface` (card title + `+ N more`) and `FSSpine` (`schema.json` + `versions/v{N}` leaves). Other FSSpine rows stay inert.
- T11: mounted at `App.tsx` root.
- T12: e2e covers both schema-side entry surfaces, tab switch, and both close affordances; the version entry point is covered by unit (FSSpine-quicklook + SchemaQuickLook tests) since the shared e2e seed has no frozen version.
- T13: live-verified on us-invoice (8-field schema + v6 frozen with 7 fields, both surfaces, both tabs, both close paths). Screenshots at `docs/screenshots/2026-05-12-m9-0-quicklook-{schema,rawjson,v6-frozen}.png`.

**Sheet is schema-shaped, not project-shaped:** header takes a synthesised `schemaId`, reserves a `derived from: —` lineage row, and each field card reserves a `review-notes` hint slot — so M9b/M9d wiring is a data swap, not a redesign. Bottom hint explains the difference between `description` (prompt) and `reviewed.notes` (AutoResearch input, never prompt) — closes the per-doc-vs-schema confusion at the UX layer until M9d closes it at the data layer.

**Hard rules respected:** no edit affordance in the sheet (red line: schema mutations go through chat / `write_schema`); raw-json tab has `copy` (read-out, not mutation); no version diff (defer); no schema fork / multi-schema picker (M9a-c).

**Decisions affirmed / out of scope:** drift detection (`schema.json` ≠ active version hash) folds into M9a; per-field copy button waits for user demand; ordinal field numbers wait for M9c. Gemini-aligned schema representation (`required` as parent-level array, `items` vs `properties`, constraint fields) deliberately deferred to M9a — viewer renders whatever the resolver returns, no contract change needed.

### M9a — schema first-class (proposed)

**Goal:** lift schema from a project-local file (`workspace/{pid}/schema.json`) to a workspace-global object (`workspace/schemas/{sid}/v{N}.json`) referenced by `project.json.active_schema_id` (and frozen `versions/v{N}.json` references too). Unblocks M9b (fork) and M9c (compare).

**Scope:** schema-object filesystem layout; project migration tool (existing projects → fresh sid, schema content moves, frozen `versions/` rewritten to point at sid); `write_schema` / `freeze_version` / Quick-look / Review / publish fast-path all read through a single `SchemaResolver`; `_keys.json` and audit log untouched.

**Out of scope:** live-link / transclusion semantics (red line — fork is clone-at-time per user's UK/US example, not a reactive reference); cross-tenant schemas (single-workspace only).

### M9b — schema fork (proposed, blocked by M9a)

**Goal:** user can fork another project's schema into a new project. `/fork us-invoice@v6 as uk-invoice` (slash form TBD) clones the schema content into a new `sid`, records `lineage = { from: "us-invoice", version: "v6", forked_at }` on the new schema object, and creates / attaches a project. Quick-look's lineage row renders the recorded lineage.

**Scope:** `fork_schema` tool (deterministic clone + lineage write); slash-command surface; Quick-look lineage row consumer.

**Out of scope:** importing schemas from external sources (URL / file upload); rebase against upstream changes (forks are independent per user's stated model).

### M9c — schema A/B compare (proposed, blocked by M9a)

**Goal:** a single project can hold multiple candidate schemas (e.g. `sid_concise` and `sid_verbose`); each runs eval independently against the same `reviewed/` corpus; metrics panel grows per-schema columns; Quick-look gains a schema-picker chip.

**Scope:** `project.json.candidate_schema_ids: [sid]`; `score` runs per-schema, persists `metrics/eval_{sid}_*.json`; ContextSurface metrics card shows side-by-side; Quick-look chip switches the displayed schema.

**Out of scope:** automatic schema-recommendation across the candidates (defer until empirical signal needed).

### M9d — autoresearch UI (proposed)

**Goal:** close the description-vs-review-notes confusion at the data layer (M9.0's bottom-hint is a stopgap). Review notes (`reviewed.notes[field]`) are aggregated per-field, surfaced as "N notes propose updates on `<field>`" cards in a dedicated AutoResearch panel; clicking opens an autoresearch flow that proposes specific `description` tweaks. Quick-look field cards' notes-hint slot becomes `N notes · open`.

**Scope:** review notes aggregator endpoint; autoresearch panel UI; Quick-look notes-slot data wiring; `/improve` integration so proposals draw on the aggregated counterexamples.

**Hard rules respected:** counterexamples (review notes) still **never enter runtime prompt**; AutoResearch still never auto-promotes — user must explicitly accept any description tweak.

## Open cross-cutting follow-ups

These don't fit a milestone but should be tracked:

- ~~**Multi-entity docs**~~ — closed by M5 (`score()` walks all entities; `FieldEditor` renders per-entity row groups; `useReview` holds `entities: dict[]`). `readiness_check` was already multi-entity-correct via score-delegation; M5 added a discriminating regression test.
- ~~**`_evidence` round-trip on review save**~~ — closed by M5: backend round-trip was already wire-correct; M5 added the click-to-page UX (a `pN` badge per evidenced field jumps `PdfViewer.goPage`).
- ~~**`fetchSchema` in ReviewMode is a one-shot fetch**~~ — closed by M5: ReviewMode reads from a `useSchema` Zustand store with `invalidate(pid)`.
- ~~**Cross-store refresh on agent tool events**~~ — closed by M5: `useChat.handleToolResult` invalidates `useSchema` / refreshes `useDocs` / `useProjects` on relevant tool completions; `ChatPanel.onSubmit`'s manual refresh hack is gone. Post-M5 dogfood (multi_entity_2.pdf, 2026-05-10) extended the trigger list to also cover `extract_batch` / `extract_one` (PENDING → DRAFT) and `freeze_version` (active version bump).
- ~~**🚨 Critical: agent allowlist not enforcing on SDK built-in tools**~~ — closed by M6: `disallowed_tools=_SDK_BUILT_IN_TOOLS` is the load-bearing knob (16 SDK built-ins explicitly listed in `chat/service.py`); `can_use_tool` retained as backstop. Confirmed empirical hypothesis — `permission_mode='default'` does NOT consult the callback for built-ins; explicit denial is the only reliable knob.
- **Audit log for `/v1/{pid}/extract` calls** — M3 only updates `last_used` per row. Deferred: per-call JSONL under `audit/{date}.jsonl` with hash prefix + ts + outcome. Useful once a project has multiple consumers.
- ~~**Plaintext API key leaks into `chats/{chat_id}.jsonl`**~~ — closed by M6: `EventRedactor` (in `chat/redactor.py`) provides asymmetric scrubbing — persist-side replaces `key_plaintext` with `[REDACTED]` for `issue_api_key` tool_result and regex-scrubs `ek_[A-Za-z0-9_-]{32}` from `agent_text`; SSE-side keeps the freshly minted key plaintext only for `tool_result` (modal reveal) but still scrubs `agent_text`. One-shot `app.scripts.scrub_chat_logs` CLI cleaned 2 leaked entries from the M3 dogfood `c_63121a1cd823.jsonl`.
- **Workspace-wide flock for `_keys.json`** — M3 `issue_api_key` locks per-pid only; concurrent issuance for *different* pids races on the shared file. Single-user lab is fine; defer fix until multi-tenant.
- ~~**`useJob` is a single global Zustand store**~~ — closed by M5: `useJob.byId[jobId]` per-slice state with `AbortController` abort-on-resubscribe; `JobProgressCard` reads the slice via selector.
- **Per-tool retry endpoint** — M4 ships chat-level "重试上一条" only. Per-tool re-run needs `/lab/chat/retry-tool` keyed by prior `tool_use_id`, plus frontend splice semantics for replacing the failed pill result without replaying the full user turn.
- **Export bundle filename for non-ASCII project names** — M4 `_safe_filename` strips non-ASCII, so a Chinese project name falls back toward `project-vN.zip`. Decide whether to preserve RFC 5987 `filename*=` UTF-8 names or use a deterministic ASCII slug with project id suffix.
- **dark-mode revival** — M7 ships light-only; design needs a dark palette pass before re-enabling the theme toggle.
- **schema sections** — review renders one synthetic section because `SchemaField` has no `section` attribute; design shows multi-section grouping. Needs optional `section` field in backend schema model.
- ~~**metrics tree section / `/eval` → right-panel metrics**~~ — right-panel half closed by **M7.2** (`2026-05-11-m7-2-metrics-panel.md`, commits `2c9b798..eb2fc61`): `GET /lab/projects/:id/evals/latest` endpoint + `useEval` store + `ContextSurface` rewrite + `useChat → useEval.refresh` cross-store hook. The FSSpine `metrics/` tree row is still open — different surface, different design question (one file per run vs. rolling history); keep deferred until design weighs in.
- **per-turn-diff preview on accept** — when the user is about to `accept turn N` on the `JobProgressCard`, show the field-description diffs that turn introduced (old → new), reusing `ProposalDiff.tsx`. Needs the autoresearch turn event (or the `versions/_candidate/` blob) to carry the per-turn schema delta. **M7.2 candidate** (carried forward from M7.1's "Spun out to M7.2"). This is the proper home for the diff UI now that `ProposalCandidateCard` is retired (M7.1 T6).
- ~~**`issue_api_key` agent re-renders a key-info markdown table**~~ — resolved inline during the 2026-05-11 post-M7.1 verify (same anti-pattern as T7, same shape of fix). Added a "Rendering contract" block to `emerge_publish.md` step 7. Verified: agent's post-key narrative no longer prints a `Detail | Value` table. See the 2026-05-11 ✅ entry in `docs/design-decisions.md`.
- ~~**publish flow's multi-turn skill loading is fragile**~~ — patched the one exercised path (`/publish` → `mint key →`) by option (b): `handleAdvance` now sends `"/publish yes, mint the key now"` so `_select_system_prompt` re-loads the publish skill on the mint-confirmation turn. Verified single-click end-to-end on us-invoice (chat `c_180d92d64057.jsonl`, 2026-05-11). The underlying per-turn keyword-prefix skill loading is still architecturally fragile; defer the broader fix until a second auto-injected-mid-flow message materializes (e.g. an `/improve` or `/extract` button).
- ~~**per-field accept in /improve**~~ — **resolved by decision (M7.1 T6, 2026-05-11): retired.** Autoresearch accept is turn-level — a turn-N field description was scored in turn N's full-schema context, so cross-turn per-field accept is incoherent. `ProposalCandidateCard` deleted; `JobProgressCard`'s "accept turn N" button is the committed model. A "preview what turn N changed" diff (reusing `ProposalDiff.tsx`) is the M7.2 follow-up for the diff UI.
- ~~**publish stage overlay vs inline**~~ — **resolved by decision (M7.1, 2026-05-11): stays inline.** Inline chat cards keep the conversation context visible; the full-conv-column overlay (`.pub-stage` position:absolute inset:0) is not pursued.
- **review object/array sub-shape** — object/array fields render as editable JSON `<pre>` since `SchemaField` carries no sub-field shape; design shows nested form rows.
- **per-field confidence dots** — hard-coded to 'high' (moss); needs per-field score from extract LLM.
- **PDF→field bidirectional binding** — current click-to-page (field→PDF) is one-way; clicking in the PDF doesn't activate the corresponding field row.
- **review toolbar `<flagged>/<total> flagged` status** — design shows a flagged-field count between the expand-toggle and prev/next arrows; deferred until per-field confidence lands (a "flag" needs a confidence threshold to count against).
- **schema model alignment with Gemini structured-output (M9a entry point)** — filed 2026-05-12 mid-M9.0. emerge's `SchemaField` diverges from JSON Schema / Gemini in load-bearing ways: (a) `required: bool` per-field instead of parent-level `required: [names]` array; (b) `children: list[SchemaField]` for `array<object>` instead of distinct `items` (array element) vs `properties` (object children); (c) bespoke type vocab (`array<object>`, `date`) vs Gemini's `string/number/integer/boolean/object/array/null` + `format`; (d) no constraint fields (`minimum/maximum/minItems/maxItems/format`). Reference: <https://ai.google.dev/gemini-api/docs/structured-output.md.txt>. Adopting Gemini shape is a full data-model refactor touching `write_schema` / `freeze_version` / extract provider adapters / eval / publish fast-path — natural home is **M9a** (schema first-class) since the workspace-global re-layout already needs to land new bookkeeping. M9.0 deliberately stays viewer-only and keeps the existing `name`/`required: bool`/`children` shape; the Quick-look component contract does not change when M9a adopts Gemini representation (FieldCard renders whatever the resolver returns).

## How to use this file

1. **Before starting a plan**: read this file to know what comes next.
2. **After shipping a plan**: update the row's status to ✅ + commit range. Move the milestone to the bottom of "What each milestone delivers" only if scope evolved during execution.
3. **When a follow-up is identified**: add a bullet to "Open cross-cutting follow-ups". Don't silently fold it into the next milestone — the visibility matters.
4. **When writing the next plan**: open `superpowers:writing-plans` skill, target the milestone listed under "What each milestone delivers", produce a plan file under this same directory dated YYYY-MM-DD.
