# Design Decisions Log

> Append-only log of UI decisions made during Code phase that deviate from, extend, or interpret the Design project.
> **Append-only**: never edit or delete past entries — strike them through if reversed.
> Path: `docs/design-decisions.md` in the Code repo.

---

## How to use this file

- **Code phase, every UI-shaped change**: add an entry below using the template.
- **Design review (weekly / per sprint)**: walk through "Needs design review" entries together; resolve each by either (a) accepting the code's choice and marking ✅, or (b) updating the Design project and marking 🔄 with a link to the new Handoff.
- **New Handoff lands**: archive resolved entries to `archive/` keyed by date, keep open ones in this file.

---

## Status legend

- 🟡 **Pending** — decision made by Code, not yet reviewed
- ✅ **Accepted** — Design reviewed and accepted as-is; will be folded into next Handoff
- 🔄 **Superseded** — Design has updated; Code should re-align next pass
- ⛔ **Rejected** — Code change was wrong; revert
- 🚨 **Needs design review** — Code hit a 🛑 boundary, needs explicit Design input before proceeding

---

## Entry template

```markdown
### YYYY-MM-DD — <short title>

- **Status**: 🟡 Pending
- **Area**: <screen / component / token>
- **Files**: `src/...`, `src/...`
- **Type**: spacing | color | copy | new-state | layout | interaction | other

**What changed**
<one or two sentences describing the change>

**Why**
<what triggered it — design didn't cover this, layout broke, etc>

**Reference**
- Original Design: <link or screenshot path>
- Current implementation: <screenshot path>

**Open questions for Design**
- <if any>
```

---

## Open entries

<!-- Append new entries below this line -->

### 2026-05-10 — Drop dark-mode toggle in M7

- **Status**: 🚨 Needs design review
- **Area**: global theme
- **Files**: `frontend/src/theme/tokens.css`, `frontend/tailwind.config.js`, `frontend/src/App.tsx`
- **Type**: interaction

**What changed**
M7 ships light-only. The `useTheme` store, `ThemeToggle` component, and the `[data-theme='dark']` block are removed. The dark palette will land in a follow-up.

**Why**
The handoff bundle (`docs/design/emerge-api/`) has no dark-mode spec. Shipping a derived dark palette without design input would diverge from the source of truth.

**Open questions for Design**
- Should dark mode be derived (ink↔paper invert) or hand-designed?
- Toggle UI location once dark palette lands (topbar pill? settings?).

---

### 2026-05-10 — Synthetic single section in review when schema has no `sections`

- **Status**: 🟡 Pending
- **Area**: `ReviewMode` → `Section` / `FieldEditor`
- **Files**: `frontend/src/components/ReviewMode/FieldEditor.tsx`, `frontend/src/components/ReviewMode/Section.tsx`
- **Type**: new-state

**What changed**
Schema fields that have no `section` group fall back to a single collapsible section labelled `fields`. The design shows multiple grouped sections; backend schema is currently flat.

**Why**
`backend/app/schemas/schema_field.py` does not have a `section` attribute today. A synthetic single-section keeps the design's section primitive consistent without backend changes.

**Open questions for Design**
- Should the synthetic section header still show a count chip?
- Is "fields" the right default label, or should it be the schema name?

---

### 2026-05-10 — Improve banner pin position

- **Status**: 🟡 Pending
- **Area**: `ImproveBanner`
- **Files**: `frontend/src/components/Improve/ImproveBanner.tsx`, `frontend/src/index.css`
- **Type**: layout

**What changed**
The `/improve` running banner is pinned at top-center 14px down (`.improvebar` from the handoff CSS). The handoff places it absolutely over the conv column.

**Why**
Conversation column is the most prominent surface and the banner needs to stay visible while the user scrolls or drafts a message.

**Open questions for Design**
- Should the banner persist across scene changes (eval, publish)?
- Should there be a dismiss-for-this-session control?

---

### 2026-05-10 — `metrics/` tree section deferred in M7 FSSpine

- **Status**: 🟡 Pending
- **Area**: `Spine/FSSpine`
- **Files**: `frontend/src/components/Spine/FSSpine.tsx`
- **Type**: new-state

**What changed**
The handoff prototype's FSSpine includes a `metrics/` directory entry. M7 omits it because the eval-history API surface doesn't exist yet (`useEval.history(pid)` is referenced by the plan but never built).

**Why**
Adding a metrics tree section without an API would mean either rendering an empty placeholder forever or hardcoding fake data. Both diverge from real product behavior.

**Open questions for Design**
- Should the row appear with an empty/placeholder state when no eval has run, or stay hidden?
- What's the canonical filename inside `metrics/` — one file per eval run, or a rolling history?

---

### 2026-05-10 — `metrics/` ContextSurface section uses placeholder data

- **Status**: 🟡 Pending
- **Area**: `Context/ContextSurface`
- **Files**: `frontend/src/components/Context/ContextSurface.tsx`
- **Type**: new-state

**What changed**
The `metrics/` section in the right context surface renders 4 placeholder metric rows. Real eval-history wiring requires a `useEval` store + `/lab/projects/:id/evals` endpoint that don't exist yet.

**Why**
The section is part of the design's tri-card layout; leaving it out would break the visual rhythm. Placeholder rows mark the slot until the eval API lands.

**Open questions for Design**
- What's the canonical metric set (precision/recall/F1/macro/coverage/etc) for the latest-eval card?
- Should this stay hidden when no eval has run, or show "no eval yet"?

---

### 2026-05-10 — Confidence labels hard-coded to high in M7 review fields

- **Status**: 🟡 Pending
- **Area**: `ReviewMode/FieldRow`, `ObjectField`, `ArrayField`
- **Files**: `frontend/src/components/ReviewMode/FieldRow.tsx`, `frontend/src/components/ReviewMode/ObjectField.tsx`, `frontend/src/components/ReviewMode/ArrayField.tsx`
- **Type**: new-state

**What changed**
The design shows per-field confidence dots (low/mid/high → rose/ochre/moss). Backend doesn't emit per-field confidence yet, so all dots render at 'high' (moss). CSS classes `.cdot.mid` and `.cdot.low` are wired but unused.

**Why**
Without backend confidence the dots would show fake signal. High-tone (moss) is the most neutral default — it signals "extraction present" rather than implying certainty.

**Open questions for Design**
- Should the dot be hidden entirely until confidence is real?
- What scoring mechanism provides the input (model logprobs / extract LLM internal score / heuristic)?

---

### 2026-05-10 — Publish stage rendered inline in chat thread (not full overlay)

- **Status**: 🟡 Pending
- **Area**: `Publish/PublishStage`
- **Files**: `frontend/src/components/Publish/PublishStage.tsx`, `frontend/src/components/Chat/MessageList.tsx`
- **Type**: layout

**What changed**
The handoff design renders the publish readiness check + key reveal as a full-conv-column overlay (`.pub-stage` is `position:absolute; inset:0`). M7 implements it as inline chat messages — readiness_check tool result becomes one card, issue_api_key result becomes another (or a key card if the reveal SSE has fired).

**Why**
The chat-thread architecture means the user has already typed `/publish` and seen the agent's reasoning. Hijacking the entire conv with an overlay obscures that history and conflicts with how every other tool result renders. Inline preserves the editorial flow and lets the user scroll back to see the readiness checklist after they've minted the key.

**Open questions for Design**
- Should the publish UX intentionally interrupt and dim the chat history (modal-like)? Or is the inline thread acceptable?
- Should we add a "mint key →" call-to-action somewhere besides clicking inside the readiness card?

---

### 2026-05-10 — Object/array sub-shape rendering simplified in M7 review

- **Status**: 🟡 Pending
- **Area**: `ReviewMode/ObjectField`, `ArrayField`
- **Files**: `frontend/src/components/ReviewMode/ObjectField.tsx`, `frontend/src/components/ReviewMode/ArrayField.tsx`
- **Type**: new-state

**What changed**
Object and array fields don't render a nested form because the backend `SchemaField` doesn't carry sub-field shape today. `ObjectField` shows the raw object value as an editable JSON `<pre>`; `ArrayField` shows each entry as a collapsible `.rcard` with its JSON content also editable. The design's nested-form treatment (sub-field rows with names, types, evidence, notes) is not implemented.

**Why**
The design's nested-form treatment requires sub-field metadata (names, types, summaries, evidence per sub-field) that the schema model doesn't have. Adding sub-shape would require `SchemaField` model changes + extract-LLM prompt updates.

**Open questions for Design**
- Is sub-shape something we add to `SchemaField`, or do we keep object/array as opaque-JSON in the lab UI and only break them out when the user explicitly adds separate fields?
- For array types: should each item card show a derived summary (first string value) or always show "item N"?

---

### 2026-05-10 — Improve candidate accept is turn-level, not field-level

- **Status**: 🟡 Pending
- **Area**: `Improve/ProposalCandidateCard`, `useJob.accept`
- **Files**: `frontend/src/components/Improve/ProposalCandidateCard.tsx`, `frontend/src/stores/jobs.ts`
- **Type**: interaction

**What changed**
The design's proposal cards have per-field accept/reject buttons. M7 implements accept as turn-level (calls `useJob.accept(jobId, turnNumber)` which freezes whatever the active turn proposed). Reject is a UI-only dismiss (no backend rejection — the card unmounts locally).

**Why**
Backend `accept_candidate` API is keyed by (jobId, turn), not (jobId, fieldName). Adding field-level granularity needs a new tool + autoresearch-job state machine for partial accepts.

**Open questions for Design**
- Is per-field accept semantically meaningful, or is "accept the whole turn" enough? (One turn often proposes one field at a time anyway.)
- Should reject persist anywhere, or is dismiss-only fine?

---

### 2026-05-10 — Review toolbar `<flagged>/<total> flagged` status text deferred

- **Status**: 🟡 Pending
- **Area**: `ReviewMode/ReviewBar`
- **Files**: `frontend/src/components/ReviewMode/ReviewBar.tsx`
- **Type**: new-state

**What changed**
The handoff design's review toolbar shows a `<flagged>/<total> flagged` status string between the expand-toggle and the prev/next arrows (e.g. `4/13 flagged`). M7 omits this string; the toolbar jumps directly from the expand icon to the nav arrows.

**Why**
Backend doesn't expose a per-field "flag" count (a flag would mean "low/mid confidence" or "needs review" — both depend on the still-deferred per-field confidence signal). Rendering `0/N flagged` would be misleading; rendering nothing is cleaner.

**Open questions for Design**
- Once per-field confidence lands, is "flagged" defined as `confLab !== 'high'` (low + mid) or only `low`?
- Where should the count live when there are zero flagged fields — hidden, or `0/N flagged` greyed out as a confidence signal?

---

### 2026-05-11 — `/eval` renders as agent markdown table; `EvalCard` component unused

- **Status**: 🟡 Pending
- **Area**: `Chat/EvalCard`, `Chat/MessageList`, `Context/ContextSurface`
- **Files**: `frontend/src/components/Chat/EvalCard.tsx`, `frontend/src/components/Chat/MessageList.tsx`
- **Type**: new-state

**What changed**
`/eval` results render as a markdown `<h2>` + table inside the agent's message bubble. The styled `EvalCard` component (`.eval-card`, per-field tonal rows, nbar) is built but never mounted — `MessageList` doesn't detect the `score` tool result and inline it. (The right-panel `metrics/` section also doesn't update after a fresh `/eval` — that's the same root cause as the `metrics/ ContextSurface placeholder` entry above: no `useEval` store. Not re-logging it here.) Net effect: eval output lives only as chat prose; no styled card, no sticky "current F1" anywhere.

**Why**
The `score` tool result isn't matched to an `EvalCard` adapter the way the M7 plan (T12.3) assumed; the agent's prose-with-markdown-table path takes over. Discovered during M7 scene verification.

**Open questions for Design**
- Keep the agent markdown table, or wire the `score` result into `<EvalCard>` (and feed `metrics/`)?
- Should the latest eval be a persistent artifact (sticky in context surface / FS spine) rather than a one-off chat message?

**Reference**
- Original Design: `docs/design/emerge-api/project/app.jsx` (EvalConversation ~323-356), `index.html:384-405`
- Current implementation: `docs/screenshots/2026-05-10-m7-eval-card.png`

---

### 2026-05-11 — Publish stage shows raw IDs / placeholder checklist; "mint key" round-trips through the agent

- **Status**: 🟡 Pending
- **Area**: `Publish/PublishStage`
- **Files**: `frontend/src/components/Publish/PublishStage.tsx`, `frontend/src/components/Chat/MessageList.tsx`
- **Type**: copy | new-state | interaction
- **Relates to**: the `Publish stage rendered inline in chat thread (not full overlay)` entry above — that one is about *layout*; this one is about the *data the stage shows* and the *mint action*.

**What changed**
1. The `check` and `key` stage eyebrows render the uppercased `project_id` (`READINESS · P_4W6RZEUZ9DFI`, `KEY MINTED · P_4W6RZEUZ9DFI / V1`) instead of the project name + slash the design uses (`READINESS · invoices/`).
2. The `check` stage's checklist is a single placeholder line `✓ no checks required`; the actual readiness checks (Schema non-empty / Reviewed & F1 / Reviewed fields in schema / No running jobs / Contract diff compat — all pass in dogfood) are printed separately as a markdown table in the agent's text, not fed into the `PublishStage` `checklist` prop.
3. `mint key →` doesn't call `useApiKey.mintAndReveal()`; it injects the chat message "yes, mint the key now" and the agent re-runs `list_projects` → `issue_api_key` (two extra LLM round-trips per mint).
4. `KEY MINTED · … / V1` — the "V1" looks like the API key's own counter but sits next to the readiness report's "next frozen version will be v5", which reads as a contradiction.

**Why**
The styled `PublishStage` panel was built ahead of (or separate from) the data that drives it — eyebrow string, checklist items, and the mint action bypass the component's props and either show raw values or route through the agent. Discovered during M7 scene verification.

**Open questions for Design**
- Eyebrow: project name + slash (`us-invoice/`) — confirm, and what to show when there's no friendly slug.
- Should `mint key →` be a direct UI action (instant reveal), or is the agent round-trip acceptable for an action of this weight?
- How to label the key's own version vs. the schema version so the two `vN`s don't collide.

**Reference**
- Original Design: `docs/design/emerge-api/project/index.html:407-435`
- Current implementation: `docs/screenshots/2026-05-10-m7-publish-check.png`, `docs/screenshots/2026-05-10-m7-publish-key.png`

---

### 2026-05-11 — Mixed CN/EN microcopy in publish key card

- **Status**: 🟡 Pending
- **Area**: `Publish/PublishStage` (key stage)
- **Files**: `frontend/src/components/Publish/PublishStage.tsx`
- **Type**: copy

**What changed**
The one-time key-reveal card mixes languages: the `copy` button has a Chinese tooltip (`复制`) and the close button's accessible name is Chinese (`我已保存 - 关闭`) while the rest of the surface (and the whole app) is English.

**Why**
Leftover from iterating on this card; no i18n layer in M7.

**Open questions for Design**
- Confirm English as the M7 baseline microcopy (and file a separate i18n track), or is bilingual intentional anywhere?

---

### 2026-05-11 — Improve proposal-candidate cards unreachable in the autoresearch flow

- **Status**: 🟡 Pending
- **Area**: `Improve/ProposalCandidateCard`, `Improve` job card, `Chat/MessageList`
- **Files**: `frontend/src/components/Improve/ProposalCandidateCard.tsx`, `frontend/src/components/Improve/ImproveBanner.tsx`, `frontend/src/stores/jobs.ts`
- **Type**: new-state | interaction
- **Relates to**: the `Improve candidate accept is turn-level, not field-level` entry above — that one discusses the cards' accept *granularity* (assuming they appear); this one notes that in the autoresearch job flow they don't appear at all.

**What changed**
`ProposalCandidateCard` (the diff + accept/edit/dismiss card the design centers the `/improve` scene on) renders only from a chat `tool_call` event whose name ends in `propose_description`. The autoresearch loop runs server-side (JobRunner) and surfaces per-turn proposals only as `job_event` progress lines (`turn N · best f1 X (turn M)`) — it never emits `propose_description` as a chat tool call. So during a real `/improve` run there is **no per-field candidate card to accept or reject**. Related: the job card has `pause`/`cancel` but no "accept the best candidate" button (the agent's intro text promises "accept the best candidate via the UI button"); and it shows `best f1` with no baseline — in the dogfood run the best candidate was `0.83` vs. the live schema's `0.97`, with no warning that accepting would regress.

**Why**
The candidate card was wired for a chat-streamed proposal model; the actual autoresearch job is a separate async worker whose internal proposals don't flow through the chat SSE. Discovered during M7 scene verification.

**Open questions for Design**
- Should autoresearch per-turn proposals be mirrored into the chat thread as `cand` cards, or should accept/reject live entirely on the job card (and only at job end)?
- The job card needs a baseline F1 to compare `best f1` against, plus an explicit accept (and probably a "this would regress" guard). Where does the accept control live — job card, a job-complete summary message, or both?
- Reconcile the agent's copy ("accept the best candidate via the UI button") with whatever UI actually ships.

**Reference**
- Original Design: `docs/design/emerge-api/project/app.jsx` (improve scene ~305-340), `pieces.jsx:325-337`, `index.html:436-446`
- Current implementation: `docs/screenshots/2026-05-10-m7-improve-banner.png`, `docs/screenshots/2026-05-10-m7-improve.png`

---

### 2026-05-11 — `new project…` entry point is a no-op; project-scoped EmptyHero unreachable from the UI

- **Status**: 🟡 Pending
- **Area**: `Spine/FSSpine`, `Empty/EmptyHero`
- **Files**: `frontend/src/components/Spine/FSSpine.tsx`, `frontend/src/components/Empty/EmptyHero.tsx`
- **Type**: interaction | new-state

**What changed**
Clicking `+ new project…` in the FS spine produces no visible result (no name prompt, no new project row, no DOM change). Because no project can be created from the UI, the project-scoped `EmptyHero` variant (eyebrow `~/projects/<name>/`, drop zone scoped to a real folder) is unreachable — the only hero state you can see is the "no project selected" variant (eyebrow `~/PROJECTS/`).

**Why**
The create-project flow behind `new project…` isn't wired in M7 (or fails silently). Discovered during M7 scene verification.

**Open questions for Design**
- Create-project UX: inline rename row in the spine, a small dialog, or a chat command (`/init` after picking a name)?
- Should the "no project selected" hero and the "empty project" hero be the same component with a swapped eyebrow, or visually distinct states?

**Reference**
- Original Design: `docs/design/emerge-api/project/app.jsx:155-187`, `pieces.jsx:94-130`
- Current implementation: `docs/screenshots/2026-05-10-m7-empty-hero.png`

---

### 2026-05-11 — M7.1 resolutions (wiring & polish from the 2026-05-11 verification)

The six 🟡 Pending entries above were addressed by M7.1
(plan: `docs/superpowers/plans/2026-05-11-m7-1-handoff-wiring-fixes.md`,
commits `576089f..81bd62d`). One Accepted decision per resolution below.

#### `/eval` → real `<EvalCard>`; agent no longer prints a markdown table

- **Status**: ✅ Accepted
- **Files**: `backend/app/tools/__init__.py`, `backend/app/skills/emerge_extractor.md`,
  `frontend/src/components/Chat/EvalCard.tsx`
- **What changed**: T1 — `t_score` now emits `_json.dumps(...)` (was
  `str(dict)`, a Python repr that broke the frontend `JSON.parse`); same
  fix in sibling `t_get_prediction`. T2 — `adaptScoreResult` reads `ts`
  as the timestamp fallback (the backend field is `ts`, not `scored_at`).
  T7 — the `emerge-extractor` skill now has an explicit "Rendering
  contract: the lab UI renders the full per-field table; do NOT reproduce
  it" block, so the agent gives a one-sentence narrative instead.
- **Why**: the `EvalCard` component existed but never rendered — the
  adapter silently fell back to a plain tool pill because of the
  `JSON.parse` throw, and the agent filled the gap with a `📊 Eval Results`
  markdown table.
- **Reference**: `docs/screenshots/2026-05-11-m7-1-eval-card.png` (after).

#### Publish stage shows real readiness checklist + project name eyebrow

- **Status**: ✅ Accepted
- **Files**: `frontend/src/components/Publish/PublishStage.tsx`,
  `frontend/src/components/Chat/MessageList.tsx`,
  `backend/app/skills/emerge_publish.md`
- **What changed**: T2 — `adaptReadiness` now parses a JSON-string
  `tool_result` (the frontend keeps the raw string for everything except
  `issue_api_key`), and a `key`→`label` humanizer maps
  `schema_non_empty`→`Schema non-empty`, `reviewed_and_f1`→`Reviewed & F1`,
  etc. T3 — `PublishStage{Check,Key}Adapter` resolves `project_id` →
  project name via a `useProjectName` helper, so the eyebrows read
  `READINESS · us-invoice` and `KEY MINTED · us-invoice/v…` instead of
  the uppercased raw id. T7 — the `emerge-publish` skill now has an
  explicit "Rendering contract" block telling the agent NOT to reproduce
  the `| Check | Status | Detail |` markdown table.
- **Why**: even though `readiness_check` already emitted valid JSON, the
  adapter required an object input → JSON-string → `null` → the "no
  checks required" placeholder. The eyebrow string and the agent's
  duplicate table were the remaining cosmetic gaps.
- **Decisions affirmed (unchanged)**: publish stage stays inline (not the
  full-conv-column overlay) — keeping the conversation context visible
  wins; `mint key →` stays agent-mediated (chat message →
  `issue_api_key`); the schema `vN` (next-frozen) is surfaced in the
  agent's one-line narrative, the API key's own `vN` lives on the
  key-stage eyebrow.
- **Reference**: `docs/screenshots/2026-05-11-m7-1-publish-eyebrow.png`,
  `docs/screenshots/2026-05-11-m7-1-publish-check.png`.

#### English-only labels in the key-reveal card

- **Status**: ✅ Accepted
- **Files**: `frontend/src/components/Publish/PublishStage.tsx`
- **What changed**: T4 — `CopyButton` title `Copied`/`Copy` (was
  `已复制`/`复制`) and `aria-label="copy api key"` (was `copy`); `KeyStage`
  close button `aria-label="I've saved this key — close"` (was
  `我已保存 - 关闭`). `rg '\p{Han}' frontend/src/components` is now clean
  of user-facing CJK.
- **Why**: the M7 baseline microcopy is English; the leftover Chinese
  tooltips read as unfinished.
- **Reference**: `docs/screenshots/2026-05-11-m7-1-key-card-en.png`.

#### `JobProgressCard` shows baseline + delta; accept-best-turn after cancel; never offers a regression

- **Status**: ✅ Accepted
- **Files**: `frontend/src/components/Chat/JobProgressCard.tsx`,
  `frontend/tests/unit/JobProgressCard.test.tsx`
- **What changed**: T5 — extracted a pure `formatJobLine` helper that
  produces `turn N · best f1 X (turn M) · baseline Y (Δ ±Z)` (was just
  `turn N · best f1 X (turn M)`). The accept block now fires for both
  `'done'` AND `'cancelled'`, so a user who cancels a productive run can
  still keep the best turn. And the accept button is gated by
  `bestTurn.macro_f1 > turns[0].macro_f1` — if the best turn ≤ baseline,
  the card shows "baseline still best — schema unchanged" instead of
  offering an accept that would regress.
- **Why**: per the M7 plan and the 2026-05-11 verification — the job card
  under-communicated and didn't let the user keep a good candidate after
  cancelling.
- **Reference**: `docs/screenshots/2026-05-11-m7-1-improve-jobcard.png`.

#### `ProposalCandidateCard` retired — autoresearch accept is turn-level (load-bearing)

- **Status**: ✅ Accepted (load-bearing decision)
- **Files deleted**: `frontend/src/components/Improve/ProposalCandidateCard.tsx`,
  `frontend/tests/unit/ProposalCandidateCard.test.tsx`
- **Files modified**: `frontend/src/components/Chat/MessageList.tsx`
  (removed the `propose_description` branch, the `isProposalCandidate`
  helper, and the `'cand'` return from `toolStatus`)
- **Files kept** (for the deferred per-turn-diff follow-up):
  `ProposalDiff.tsx`, the `'cand'` `ToolStatus` member in `ToolCall.tsx`,
  the `.tool .t-status.cand` CSS rule in `index.css`.
- **Reasoning**: the unit of "did this help" in autoresearch is the
  *whole-schema macro F1 at a given turn* (a turn changes a field's
  `description`, re-extracts all reviewed docs, re-scores). Per-field
  accept *across* turns is incoherent — a turn-N description was scored
  in the context of turn N's full schema. So the committed model is
  turn-level accept via `JobProgressCard`'s "accept turn N" button (T5).
  The per-field `ProposalCandidateCard` was wired for a chat-streamed
  proposal model that doesn't exist (`grep -rn "propose_description"
  backend/app/` returns nothing — no chat-exposed `@tool` ever emits the
  event the card was waiting for). Closes the "per-field accept in
  /improve" open follow-up by deciding *against* it.
- **Carried forward to M7.2**: "preview what turn N changed before you
  accept it" reuses the retained `ProposalDiff.tsx`.

#### Agent no longer re-emits eval / readiness results as markdown tables

- **Status**: ✅ Accepted
- **Files**: `backend/app/skills/emerge_extractor.md`,
  `backend/app/skills/emerge_publish.md`
- **What changed**: T7 — added explicit "Rendering contract" blocks to
  both skill prompts. The `emerge-extractor` `/eval` section now reads
  "the lab UI renders the full per-field precision/recall/F1 table from
  the tool result automatically. Do NOT reproduce that table in your
  reply — no `📊 Eval Results` heading, no markdown table, no per-field
  bullet list." The `emerge-publish` workflow step now reads "the lab UI
  renders the readiness checklist automatically. Do NOT reproduce it as
  a markdown table." Both replace the previous "Summarize / Present"
  wording that the model was interpreting as "format the rows as a table."
- **Why**: the UI cards are canonical; the duplicate agent table read as
  a double-render and made the `EvalCard` / `PublishStage` feel redundant.

#### `Skill ERR` chip on `/publish` — fix: deny built-in `Skill` SDK tool

- **Status**: ✅ Accepted
- **Files**: `backend/app/chat/service.py`
- **What changed**: T8 — added `"Skill"` to the `_SDK_BUILT_IN_TOOLS`
  `disallowed_tools` list. That list was meant to enumerate every SDK
  built-in we don't expose; `Skill` was simply missing.
- **Why**: the agent reached for `Skill("emerge-publish")` (a built-in
  SDK tool) on `/publish`; emerge loads its skills as `system_prompt`
  text rather than registering them with the SDK Skill mechanism, so the
  SDK returned `<tool_use_error>Unknown skill: emerge-publish</tool_use_error>`
  and the chat showed a stray `▸ Skill ERR` chip. The agent recovered
  (the skill text was already in the system prompt), but the failed
  `tool_call` littered the trail. Diagnosis evidence: chat
  `c_11f0c9f0e0fc.jsonl` lines 2-3 capture the exact
  `tool_call → "Unknown skill"` pair.

---

### 2026-05-11 — Agent no longer re-emits `issue_api_key` metadata as a markdown table (M7.1 follow-up)

- **Status**: ✅ Accepted
- **Files**: `backend/app/skills/emerge_publish.md`
- **Type**: copy

**What changed**
Surfaced during the post-M7.1 end-to-end verification (chat
`c_bbcddbe1c5b3.jsonl`, 2026-05-11). After `issue_api_key`, the UI's
key-stage `<PublishStage>` already renders the project, version,
plaintext key (one-time), prefix, hash, created timestamp, and the
`$EMERGE_API_KEY`-templated curl snippet — but the agent was ALSO
emitting a `Detail | Value` markdown table re-stating project / key
prefix / created date. Same double-render pattern M7.1 T7 fixed for
`score` / `readiness_check`, just for a tool T7 didn't cover. Folded
into M7.1 rather than punted to M7.2 — same shape of edit, same
verification path, no reason to defer.

**Fix**
`emerge_publish.md` step 7 — added a "Rendering contract" block telling
the model: the UI renders the key card; do NOT reproduce its metadata
in a markdown table or inline curl block; give one short sentence
acknowledging the mint and pointing at the card; mention the
`Authorization: Bearer $EMERGE_API_KEY` usage only if the user asks.

**Verified**
Re-ran `/publish issue the api key now — readiness already passed` on
us-invoice. Backend restarted to reload the skill, v5 frozen, key minted
(`ek_bYsZrZxZ…/202f19`), agent's post-key narrative: "v5 frozen and
key minted — copy it from the card above before closing; it won't be
shown again. The prior v4 key is now invalid. Calls go to
`POST /v1/p_4w6rzeuz9dfi/extract` with `Authorization: Bearer
$EMERGE_API_KEY`." No `Detail | Value` table.

**Pre-existing snag surfaced (out of scope, logged below)**
The `mint key →` button injects `"yes, mint the key now"` as the next
user message, but `ChatService._select_system_prompt` only loads the
publish skill when the message *starts with* `/publish`. The model can
go either way (the earlier successful run did `list_projects` →
`issue_api_key` despite the skill not being loaded; this run refused
with "this skill needs to be loaded"). The publish flow is multi-turn
and the per-turn keyword-prefix skill loader doesn't respect that.
Separate architectural concern; see the next entry.

**Reference**
- Verification screenshot (now without the duplicate table):
  `docs/screenshots/2026-05-11-m7-1-publish-key.png`.

---

### 2026-05-11 — `mint key →` prefixes `/publish ` on the injected message (option b)

- **Status**: ✅ Accepted
- **Files**: `frontend/src/components/Chat/MessageList.tsx`
  (`PublishStageCheckAdapter.handleAdvance`)
- **Type**: interaction | architecture-light

**What changed**
The `mint key →` button used to inject the literal message
`"yes, mint the key now"`. That worked on the model's good days but —
because `ChatService._select_system_prompt` keys off the literal
`/publish` prefix per turn — sometimes the model saw only the default
extractor skill on the mint-confirmation turn and refused with
"this skill needs to be loaded." Per-turn keyword-prefix skill loading
is structurally at odds with multi-turn flows.

**Fix (option b from the three written in the original entry)**
`handleAdvance` now sends `"/publish yes, mint the key now"`. The
`/publish` prefix triggers `_select_system_prompt` to re-load the
publish skill on this turn, so `issue_api_key` is always invoked
under the same skill that ran readiness. One-line change with a
comment pointing at this entry.

**Why this option (not a/c)**
- (a) state-based skill loading: introduces a chat_id→skill-set
  mapping and a state machine for skill scope. Larger blast radius
  than the user-facing problem.
- (c) move mint to a direct UI action: cleanest, but explicitly
  contradicts the M7.1 plan's Out-of-scope note ("Agent-native; not
  changing it here"). Would need a separate design pass.
- (b) frontend prefix injection: 1 line, no contract change, the
  injected `/publish ` is visible in the chat trail so the user can
  see exactly what happened.

**Verified**
Single-click `mint key →` on us-invoice ran end-to-end without refusal
(chat `c_180d92d64057.jsonl`, 2026-05-11): list_projects →
readiness_check → freeze_version → issue_api_key. v6 frozen, key minted.
No "skill needs to be loaded" anywhere in the chat trail.

**Open**
The underlying architectural concern — per-turn keyword-prefix skill
loading is fragile for any multi-turn flow — is still real. This fix
patches the one path that's exercised today (`/publish` → `mint key →`);
similar problems may show up if `/improve` or `/extract` gain a
mid-flow button that injects a follow-up message. Defer until a
second instance materializes.
