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
| **M4** — polish + dark mode + export bundle | _plan TBD_ | ⏳ last before merge | — |

## What each milestone delivers

### M2C — autoresearch + /improve (next plan to write)

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

## Open cross-cutting follow-ups

These don't fit a milestone but should be tracked:

- **Multi-entity docs** — `score()` and review-mode FieldEditor only handle `entities[0]`. Still open after M3 (scope-cut per design discussion); M4 should land the `score()` / `readiness` fix and the FieldEditor multi-row UI together.
- **`_evidence` round-trip** on review save — `Reviewed` model drops it. M2C (`_source_page` click-to-page) will need a decision.
- **`fetchSchema` in ReviewMode is a one-shot fetch** — M2C autoresearch will mutate schema; review mode will see stale fields. Promote to a Zustand store with explicit invalidate.
- **Cross-store refresh on agent tool events** — M2A patched `ChatPanel.onSubmit` to refresh `useDocs` + `useProjects`. Cleaner: emit a `tool_done` SSE event the stores subscribe to.
- **Audit log for `/v1/{pid}/extract` calls** — M3 only updates `last_used` per row. Deferred: per-call JSONL under `audit/{date}.jsonl` with hash prefix + ts + outcome. Useful once a project has multiple consumers.
- **Workspace-wide flock for `_keys.json`** — M3 `issue_api_key` locks per-pid only; concurrent issuance for *different* pids races on the shared file. Single-user lab is fine; defer fix until multi-tenant.
- **Markdown not rendered in chat** — agent responses contain `**bold**`, `| tables |`, `## headers` as raw text. Add a markdown renderer (e.g. `react-markdown`) to `AgentMessage` in M4 polish.
- **"agent is thinking…" indicator exists but is subtle** — live region (aria-live="polite") shows during agent turns; input is disabled. Consider a more visible spinner or streaming dots for long-running tool calls (e.g. `score` on large projects).
- **`useJob` is a single global Zustand store** — multiple `JobProgressCard`s in the same chat session collapse to one. Last `subscribe()` resets state and old SSE streams aren't aborted, so turn entries leak across runs (T21 smoke saw "turn 5" when only 3 turns actually ran). Refactor to per-jobId state (Map keyed by jobId) and abort the previous SSE on re-subscribe. M4 polish.

## How to use this file

1. **Before starting a plan**: read this file to know what comes next.
2. **After shipping a plan**: update the row's status to ✅ + commit range. Move the milestone to the bottom of "What each milestone delivers" only if scope evolved during execution.
3. **When a follow-up is identified**: add a bullet to "Open cross-cutting follow-ups". Don't silently fold it into the next milestone — the visibility matters.
4. **When writing the next plan**: open `superpowers:writing-plans` skill, target the milestone listed under "What each milestone delivers", produce a plan file under this same directory dated YYYY-MM-DD.
