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
- **metrics tree section** — `FSSpine` `metrics/` row deferred until eval history is exposed via `/lab/projects/:id/evals`.
- **per-field accept in /improve** — currently turn-level; needs new backend tool + state machine for field-level granularity.
- **publish stage overlay vs inline** — current implementation is inline chat cards; design intends a full-conv-column overlay (`.pub-stage` position:absolute inset:0).
- **review object/array sub-shape** — object/array fields render as editable JSON `<pre>` since `SchemaField` carries no sub-field shape; design shows nested form rows.
- **per-field confidence dots** — hard-coded to 'high' (moss); needs per-field score from extract LLM.
- **PDF→field bidirectional binding** — current click-to-page (field→PDF) is one-way; clicking in the PDF doesn't activate the corresponding field row.
- **review toolbar `<flagged>/<total> flagged` status** — design shows a flagged-field count between the expand-toggle and prev/next arrows; deferred until per-field confidence lands (a "flag" needs a confidence threshold to count against).

## How to use this file

1. **Before starting a plan**: read this file to know what comes next.
2. **After shipping a plan**: update the row's status to ✅ + commit range. Move the milestone to the bottom of "What each milestone delivers" only if scope evolved during execution.
3. **When a follow-up is identified**: add a bullet to "Open cross-cutting follow-ups". Don't silently fold it into the next milestone — the visibility matters.
4. **When writing the next plan**: open `superpowers:writing-plans` skill, target the milestone listed under "What each milestone delivers", produce a plan file under this same directory dated YYYY-MM-DD.
