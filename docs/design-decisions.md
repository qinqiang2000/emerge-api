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

---

### 2026-05-11 — `metrics/` ContextSurface section reads real `/eval` data

- **Status**: ✅ Accepted
- **Area**: `Context/ContextSurface`
- **Files**: `frontend/src/components/Context/ContextSurface.tsx`,
  `frontend/src/stores/eval.ts`, `frontend/src/lib/api.ts`,
  `backend/app/api/routes/eval.py`
- **Type**: new-state
- **Resolves**: the 2026-05-10 🟡 Pending entry "`metrics/` ContextSurface
  section uses placeholder data"

**What changed**
The 4 hardcoded placeholder rows (`precision 0.94 / recall 0.91 / f1 0.92 /
coverage 100%`) and the `[ContextSurface] metrics … placeholder` console log
are gone. The section now reads the latest `metrics/eval_*.json` snapshot via
a new `GET /lab/projects/:id/evals/latest` endpoint and a new `useEval`
Zustand store. Successful `/eval` runs refresh the rail in the same SSE turn
via `useChat.handleToolResult` (same pattern as `write_schema` →
`useSchema.invalidate`). The empty state is "no eval yet — type /eval in the
chat", matching the schema section's empty-state pattern.

**Display contract (resolves the 2026-05-10 open question)**
Macro precision · macro recall · macro F1 · coverage (`n_reviewed / n_docs`),
same tone thresholds as `EvalCard.toTone` (≥0.85 ok, ≥0.65 mid, else bad).
Header right-hint reads `macro <f1> · <n> reviewed`. Other metric
permutations (per-field worst, errors count, …) deferred until design weighs in.

**Reference**
- Plan: `docs/superpowers/plans/2026-05-11-m7-2-metrics-panel.md`
- Live check: `docs/screenshots/2026-05-11-m7-2-metrics-panel.png` (shows
  inline `<EvalCard>` at F1 0.847 alongside the right-rail metrics card with
  derived macro values precision 0.88 / recall 0.82 / f1 0.85 / coverage 83%
  for the dogfood us-invoice run)

---

### 2026-05-11 — Adopt ToolStack (done-only) + hoist rich cards to grouping layer

- **Status**: 🟡 Pending
- **Area**: `Chat/MessageList`, `lib/groupChatEvents`, `Chat/ToolStack` (new)
- **Files**: `frontend/src/components/Chat/ToolStack.tsx` (new),
  `frontend/src/components/Chat/MessageList.tsx`,
  `frontend/src/lib/groupChatEvents.ts`,
  `frontend/src/types/chat.ts`,
  `frontend/src/index.css` (`.tstack` block),
  `docs/design/emerge-api/project/{app.jsx,index.html,pieces.jsx}` (synced)
- **Type**: layout | new-state | new-component

**What changed**
A run of consecutive plumbing tool calls in chat (e.g. `read_documents` →
`derive_schema` → `write_schema`) now collapses to a single editorial-italic
line `Ran 3 tools ›` that expands to a vertical-spine tree of `<ToolCall>`
nodes. The 4 rich-card tools — `score`, `readiness_check`, `issue_api_key`,
`start_job` — are **hoisted out** of the ToolStack at the grouping layer
(`lib/groupChatEvents.ts`) and render as independent blocks (`EvalCard`,
`PublishStage check/key`, `JobProgressCard`), exactly as they did before.

The hoist logic that used to live at render time as a chain of 4 `if`s
inside `ToolCallCard` is now expressed as the `HOISTED_TOOL_NAMES` set in
`groupChatEvents.ts`. `MessageList` exposes two card components in its
place: `HoistedToolCard` (the 4 rich-card routes) and `PlumbingToolCard`
(generic `<ToolCall>` for everything else, wrapped by `<ToolStack>`).

**Why**
Plumbing tool calls (≈80% of chat tool noise) are *availability*, not
*attention* — the user's eye should land on agent_text and rich cards, with
tool traces a click away. Each plumbing call was previously a full-width
row competing with `<EvalCard>` / `<AgentMessage>` for focus. Folding them
behind one italic line gives a Claude-style trace without sacrificing the
emerge artifact-first stance.

Rich cards stay hoisted because folding `EvalCard` / `PublishStage` /
`JobProgressCard` behind `Ran N tools ›` would hide their primary surface
(score numbers, readiness checklist, one-time API key reveal, job
progress) — the exact opposite of what the user came for.

**Scope decisions (intentional omissions)**
- **No `run` mode carousel.** The handoff's `ToolStack` had a `state="run"`
  in-place step-by-step animation driven by a prefilled `steps={[...]}`
  prop. emerge's agent streams `tool_use` blocks one at a time and the
  frontend has no way to predict the next step, so the run mode semantics
  don't translate. Run state stays as the existing `calling X…` footer in
  `MessageList`.
- **No `totalDur` chip.** The handoff's `Ran 3 tools · 13.6s ›` cell has
  no data source: the SSE protocol (`backend/app/chat/service.py`) carries
  no timestamps on `tool_call` events, and on chat-history rehydration the
  events arrive batched so wall-clock timing would collapse to ~0ms.
  Rendering "Ran 3 tools ›" without a duration is cheaper than adding a
  timestamp field to the protocol for a glance-value chip. Revisit if the
  chip becomes load-bearing.
- **`Ran 1 tool ›` is accepted.** When the hoist split leaves a 1-element
  plumbing group it shows up as `Ran 1 tool ›` — slightly redundant vs
  rendering the bare ToolCall, but special-casing N=1 adds branching with
  no clear win. Defer until a user complains.

**Reference**
- Design handoff: `https://api.anthropic.com/v1/design/h/Y_ioMfjKoAZmEFaH3H7AXw`
- Synced design files: `docs/design/emerge-api/project/{app.jsx,index.html,pieces.jsx}`
- New tests: `frontend/tests/unit/groupChatEvents.test.ts` covers 3 new
  cases — mid-stream hoist, leading hoist (no empty leading group),
  back-to-back hoist.

**Open questions for Design**
- Is the `Ran 1 tool ›` edge case visually acceptable, or should N=1
  collapse degrade back to the raw ToolCall row? (Currently accepted.)
- When/if calling-time timing becomes desirable, the path is: add
  `ts_start_ms`/`ts_end_ms` to the `tool_call` SSE event in
  `backend/app/chat/service.py:213-249` and surface `· 0.0s` next to
  `Ran N tools`. Not done in this pass.

---

### 2026-05-11 — Composer slash-command submit: fix Enter re-pick loop, add Tab, close menu on pick

- **Status**: 🟡 Pending
- **Area**: `Chat/Composer`
- **Files**: `frontend/src/components/Chat/Composer.tsx`,
  `frontend/tests/unit/Composer.test.tsx`
- **Type**: interaction (bug fix)

**What changed**
Three coupled fixes to the slash-command autocomplete:
1. **Enter no longer loops.** Before: while the text started with `/` the
   menu was always open, so plain Enter always "picked the active item" →
   `setText('/eval ')` → still starts with `/` → next Enter re-picks…
   forever. A slash command could only be submitted with ⌘/Ctrl+Enter.
   Now the menu is considered *dismissed* once a full command prefixes the
   text (`/eval`, or `/eval …`), so after a pick the next plain Enter falls
   through to `submit()` — consistent with the `⌘ ↵ send` footer hint.
   ⌘/Ctrl+Enter still submits unconditionally, including mid-typing.
2. **Tab picks the active item**, same as Enter (`preventDefault` so it
   doesn't shift focus). Common autocomplete affordance.
3. **The menu closes after a pick / after a full command name is typed.**
   `showSlash = text.startsWith('/') && !completedCommand`, where
   `completedCommand` is true when the text is exactly a command or is
   prefixed by `<cmd> `. Previously the menu lingered (e.g. it stayed open
   showing all 6 commands with `/eval ev` in the box).

**Why**
Reported during the 2026-05-11 ToolStack browser dogfood: typing `/eval`
and pressing Enter did nothing visible (silent re-pick loop), the menu
never went away, and there was no Tab support. User's stated preference:
keep the combo shortcut as the canonical submit (the footer already
advertises `⌘ ↵`), and don't let plain Enter dead-end.

**Reference**
- New tests: `frontend/tests/unit/Composer.test.tsx` — Enter picks→closes→
  submits, Tab picks, full-command-name closes the menu, ⌘/Ctrl+Enter
  submits while the menu is open.
- Live check: dogfood on us-invoice — typed `/ev` → menu filtered to
  `/eval` highlighted → Tab → `/eval ` filled, menu closed, focus retained
  → Enter → submitted (screenshot `docs/screenshots/2026-05-11-slash-ev.png`
  shows the filtered menu state pre-Tab).

---

### 2026-05-12 — E2E specs realigned to M7 UI; two assertions adjusted to closest equivalent

- **Status**: 🟡 Pending
- **Area**: `tests/e2e` (Chat thread, Publish key card)
- **Files**: `frontend/tests/e2e/chat-layout.spec.ts`,
  `frontend/tests/e2e/publish-modal.spec.ts` (+ selector-only churn in
  `walking-skeleton`, `review-mode`, `review-mode-evidence`)
- **Type**: other (test maintenance)

**What changed**
The `m7-design-handoff-ui` merge rewrote the markup the Playwright suite
targeted, so all 5 specs were re-selectored against the current DOM
(project selection is a `.proj` sidebar row, not a `<button>`; right-rail
doc list rows are `role="button"` with an uppercase status badge; ToolStack
`Ran N tools ›` collapse; etc.). Two assertions tested behavior the M7 UI
no longer has and were adjusted (not dropped):
1. **`chat-layout`** — old: user message renders as a right-aligned
   "bubble" (`[data-role="user-bubble"]` whose parent has `justify-end`).
   New: the terminal-style thread renders the user line as `.msg.user`
   (italic, smart-quoted via CSS `::before`/`::after`), visually distinct
   from agent turns but not bubble-laid-out. The spec now asserts the
   `.msg.user` element exists and carries the typed text.
2. **`publish-modal`** — old: the redacted "key issued · prefix …hash"
   trail was asserted *alongside* the one-time-reveal card. New: the reveal
   card and the trail are the same inline `PublishStage` card in two states
   (`useApiKey.current` set vs cleared), so the trail only appears *after*
   the reveal is closed. The trail assertions (`key issued`, prefix,
   `hash ffffff`) moved to after the close click.

**Why**
`cd frontend && npm run e2e` was failing all 5 specs (pre-M7 selectors).
No product behavior changed — only the tests. The two adjustments above
keep coverage on the same intent (user line is visually distinct; the
plaintext key never persists and a redacted trail remains) against the
shapes the M7 UI actually renders.

**Reference**
- Verified: `cd frontend && npm run e2e` → 5/5 green (run twice, stable).
- UI snapshotted live via chrome-devtools-mcp against the e2e test-mode
  backend (`EMERGE_TEST_MODE=1`, seeded project `e2e-test`) before
  reselectoring.

---

### 2026-05-11 — Chat history survives page reload (per-project chatId + hydrate on entry)

- **Status**: ✅ Resolved by M8 (`docs/superpowers/plans/2026-05-12-m8-chat-history.md`) — per-project chatId persistence still applies, but the single-chat model it described is superseded by multi-chat (`emerge.chatId.<pid>` → `emerge.activeChatId.<pid>`; chats are now server-listed via `GET /lab/chats/{pid}`).
- **Area**: `Chat/ChatPanel`, `stores/chat`
- **Files**: `frontend/src/stores/chat.ts`, `frontend/src/lib/api.ts`,
  `frontend/src/components/Chat/ChatPanel.tsx`, `frontend/tests/unit/chat-hydrate.test.ts`
- **Type**: new-state (bug fix)

**What changed**
The chat store now persists a per-project `chatId` in `localStorage`
(`emerge.chatId.<pid>`) and, on project entry (`enterProject`), rebinds to
that id and hydrates `events` from `GET /lab/chats/{pid}/{cid}` (passive
replay via a pure `reduceEvents`; no side effects). The create-project flow
adopts the in-flight conversation without clearing/hydrating. Backend already
resumes the SDK session via `chats/{chat_id}.meta.json`. No new UI surface —
single per-project chat, no history sidebar.

**Why**
Refreshing the page lost the chat: `events` were in-memory only and a fresh
random `chatId` was minted per page load (so the backend also saw a new chat).

**Reference**
- New tests: `frontend/tests/unit/chat-hydrate.test.ts` (reduceEvents pairing,
  chatIdFor persistence, enterProject switch/adopt/no-op cases).
- e2e reload-restore coverage is a follow-up (the e2e `/lab/chat` stub doesn't
  write the JSONL log, so it'd need harness work).

---

### 2026-05-12 — Design handoff introduces multi-chat history + left-rail slim (deferred to next milestone)

- **Status**: ✅ Implemented by M8 (`docs/superpowers/plans/2026-05-12-m8-chat-history.md`, commits `113f792..d858b19`). `ConvHeader` ships with the two floating chips + popover; `FSSpine` drops the meta doc-count, gains a 6 px status dot, and collapses `reviewed/` / `versions/` by default; the chat store migrates to `emerge.activeChatId.<pid>` with `chatsByProject` + `listChats / switchChat / newChat`; backend grows `GET /lab/chats/{pid}` + the `{label,kind,created_at}` sidecar half; `GET /lab/projects` carries an additive `status: live|draft|empty`. Project-status partition (live/draft/empty) is the committed answer to the open question.
- **Area**: `Chat/ConvHeader` (new), `Spine/FSSpine`, `stores/chat`
- **Files**: `docs/design/emerge-api/project/{app,data,pieces}.jsx`,
  `docs/design/emerge-api/project/index.html`,
  `docs/design/emerge-api/chats/chat2.md`
- **Type**: new-state + interaction

**What changed**
A `/sync-design` pull brought in two design changes for the conv column
and left rail:
1. New `ConvHeader` floating at conv top-right with two icon chips —
   ⏱ Chat history (opens per-project sessions popover) and `+ New`
   (jumps to EmptyHero). Hidden in Review mode.
2. `FSSpine` slim: project rows lose the `42 docs` meta; active row
   gets a 6 px status dot (`live/draft/empty`); FS tree default-opens
   only `docs/`, collapses `reviewed/`/`versions/`/`metrics/` to one
   row + count.

This generalizes the M7.1 single-chat-per-project model (see preceding
entry) to **multi-chat per project**, with read+write of chat-history
metadata — a sizable module. Per user direction, code is not changed in
this commit; a planning prompt was written at
`docs/superpowers/plans/PROMPT-2026-05-12-chat-history.md` to be fed to
`superpowers:writing-plans` in a follow-up session.

**Why**
The design conversation (`docs/design/emerge-api/chats/chat2.md`)
identified history-recall as a high-frequency need not surfaced by the
current FS-tree-only spine. The chosen pattern matches Claude's own UI
language, which the user explicitly referenced.

**Reference**
- Source-of-truth design: `docs/design/emerge-api/{chats/chat2.md, project/pieces.jsx, project/index.html}` (this commit).
- Planning input: `docs/superpowers/plans/PROMPT-2026-05-12-chat-history.md`.
- Predecessor in this log: 2026-05-11 "Chat history survives page reload".

**Open questions for Design**
- Project `status` source ("live/draft/empty") — current backend has no
  such field; the plan recommends an additive derivation from
  `versions/`+`schema.json` presence, but Design should confirm the
  three buckets are the right partition.

---

### 2026-05-12 — UI vocabulary becomes task-type-agnostic (deferred-impl directive)

- **Status**: ✅ Implemented by M8 (`docs/superpowers/plans/2026-05-12-m8-chat-history.md`, commits `113f792..d858b19`). Chat-kind taxonomy ships as the locked generic-verb set `init | run | tune | review | publish | ingest | chat` (slash-cmd → kind map in `backend/app/chat/log.py:derive_chat_kind`, many-to-one — `/extract` and `/eval` both → `run`; attachments-on-turn-1 → `ingest`). Popover header is mono uppercase `history`; empty state `No sessions yet.`; row schema is `kind / label / ts` with no `summary`. Future task types share this kind vocab; `/extract` and `/v1/{pid}/extract` keep their names for backward compatibility.
- **Area**: project-wide chrome — kind chips, slash-menu labels, button copy, empty states, popover headers
- **Files**: `CLAUDE.md` (Engineering section, new bullet),
  `docs/superpowers/plans/PROMPT-2026-05-12-chat-history.md` (§1a),
  `docs/design/emerge-api/chats/chat2.md` (last user turn)
- **Type**: copy + new-state (design directive)

**What changed**
A second `/sync-design` pass on 2026-05-12 introduced a strategic
directive: this UI shell will host non-extraction task types
(document matching, classification, etc.); only the API publish layer
stays universal. Concrete consequences captured in the design:

- Chat-history kind taxonomy switched from extraction-specific
  (`extract`, `improve`) to generic verbs
  (`init / run / tune / review / publish / ingest`).
- History-popover row schema dropped `summary`; rows are now one line
  (kind / label / ts).
- Empty state copy: `"No sessions yet."` (was a multi-line `/init`-flavored hint).
- Header is mono-uppercase `history` instead of italic-serif `chat history`.

The directive is now codified in `CLAUDE.md` under Engineering and in
the user's auto-memory (`feedback_task_type_agnostic_ui.md`). All
future UI plans should honor it.

**Why**
User: "希望本设计能复用到其他非文档提取类任务，比如文档匹配等等，
但API发布是通用。所以希望少一点专用的设计，多一点通用的".
The chrome must read for users who arrive with non-extraction
intents; reserving doc-extraction terms for the chrome would force a
copy rewrite for every new task type.

**Reference**
- Source-of-truth design: `docs/design/emerge-api/{chats/chat2.md (last turn), project/data.jsx, project/index.html, project/pieces.jsx}` (this commit).
- Planning input: `docs/superpowers/plans/PROMPT-2026-05-12-chat-history.md` (§1a captures the constraint; §6 lists the locked kind taxonomy).

**Open questions for Design**
- Grandfathered names: `/extract` slash-command and `/v1/{pid}/extract`
  API path stay as-is for backward compat. Future task types will get
  their own slash-commands but share the same kind-chip vocab. Confirm
  this split (slash-cmd specific, kind generic) is acceptable.
- Whether the kind taxonomy should be extensible (per-project or
  per-task-type) or locked at the seven generic verbs. Current
  recommendation: locked — pick a verb, don't invent a noun.

### 2026-05-12 — ✅ schema.json + frozen versions become one-click viewable (M9.0 shipped)

**Status**: resolved — sheet ships behind FSSpine `schema.json`, FSSpine `versions/v{N}`, right-rail `schema.json` card title, and right-rail `+ N more`.

**What changed**
The right rail's schema card silently truncated the field list at 7 with a non-interactive `+ N more` hint, and `schema.json` rows in both the FSSpine and the right rail were inert — there was no path to the full schema short of `cat`-ing the file. M9.0 adds a read-only Quick-look sheet (centred modal, scrim, Esc/✕ close) reachable from those four surfaces, plus `versions/v{N}` leaves in the FSSpine for frozen versions.

Two tabs: **fields** (default; per-field card with name + type + REQUIRED pill + description + examples + enum + reserved notes-hint slot rendered as `—`; `array<object>` discloses children recursively, no depth cap) and **raw json** (lazy-loaded pretty-printed from `/lab/projects/{pid}/schema/raw` or `/lab/projects/{pid}/versions/{vid}/raw`, with a `copy` button — read-out only, not mutation).

The sheet is **schema-shaped, not project-shaped**: the header takes a synthesised `schemaId` (`pid` for live, `pid/versionId` for frozen), reserves a `derived from: —` lineage row in DOM today, and each field card reserves a per-field notes-hint slot. M9a (schema first-class) and M9b (fork lineage) plug into the same component contract — no redesign.

**Why**
The user-reported papercut (`+ N more` not clickable, FSSpine rows inert) was the surface symptom; the underlying complaint was that `schema.json` is treated as a string inside a project's folder, not as a first-class object the user wants to inspect, reuse, and compare. M9.0 deliberately under-commits to the *viewer* and files the data-model work (workspace-global schema, fork, A/B compare, autoresearch UI) as M9a-d. The viewer's schema-shape lets those follow-ups land without redesigning the rendering.

**Hard rules respected**
- No edit affordance anywhere in the sheet — schema mutations stay agent-mediated through chat / `write_schema`.
- Raw-json `copy` is read-out (clipboard write), not a content edit.
- No version diff between v5 and v6 (deferred); no schema fork / multi-schema picker (M9a-c).
- AutoResearch + counterexample red lines untouched.

**Notable in-flight discoveries (filed during execution)**
- **Frontend `SchemaField` was narrower than backend pydantic.** T4 widened `frontend/src/stores/schema.ts` to add optional `required` / `examples` / `children` so the canonical type matches `backend/app/schemas/schema_field.py` (the single schema truth per `CLAUDE.md`). Existing consumers only read `name`/`type`/`description`/`enum`, so widening was non-breaking.
- **Frozen-version blob uses `schema` key, not `fields`.** Live-verify on us-invoice v6 caught that `publish.py:331` writes `{ "schema": [...], "frozen_at": ..., ... }`, while spec §3.3 contracts `{ fields: SchemaField[], ... }` for `?shape=fields`. Fix: the `?shape=fields` route is now the wire-format adapter — remaps `schema` → `fields` and passes the rest through. `publish.py` and existing frozen version files untouched. Without this, every FSSpine `versions/v{N}` click would have rendered "empty version" on real workspaces.
- **Gemini-style schema representation filed under M9a.** The user pointed at <https://ai.google.dev/gemini-api/docs/structured-output.md.txt> mid-implementation. Adopting Gemini's shape (`required` as parent-level array; `items` vs `properties` instead of bespoke `children`; type vocab swap; constraint fields) is a full data-model refactor that touches `write_schema` / extract provider adapters / eval / publish fast-path — the natural home is M9a (schema first-class) since the workspace-global re-layout already needs new bookkeeping. M9.0 viewer renders whatever the resolver returns; the component contract does not change when M9a adopts Gemini representation.

**Reference**
- Spec: `docs/superpowers/specs/2026-05-12-schema-quicklook-design.md`
- Plan: `docs/superpowers/plans/2026-05-12-m9-0-schema-quicklook.md` (13 tasks, TDD per task)
- Range: `848cb8f..65dd377` (15 commits incl. scaffold + Gemini-followup doc + live-verify fix)
- Screenshots: `docs/screenshots/2026-05-12-m9-0-quicklook-{schema,rawjson,v6-frozen}.png`

**Spun out**
- M9a — schema first-class (workspace-global `schemas/<sid>/`, project references `sid`); folds in drift detection + Gemini-aligned representation.
- M9b — schema fork (clone-at-fork-time + lineage row in Quick-look).
- M9c — schema A/B compare (per-schema eval columns + Quick-look picker).
- M9d — autoresearch UI (review notes → proposed description tweaks; Quick-look notes-hint slot becomes `N notes · open`).

### 2026-05-13 — ✅ experiments axis + Review-mode multi-tab (M9.3 shipped)

**Status**: resolved — experiment is now a first-class `(prompt_id, model_id)` reference pair with per-doc extracts. 7 MCP tools, 4 HTTP routes, FSSpine `experiments/` group, Review-mode tab strip with read-only experiment tabs. Backend + frontend complete, e2e green, no regressions.

**What changed**
The user can now isolate alternative `(prompt, model)` combinations as named experiments without touching the project's active pair. Workflow: `create_experiment` (defaults to active axes) → `extract_with_experiment(doc_id)` for per-doc probes → `run_experiment_eval` for full reviewed/ scoring → `promote_experiment` to flip active and re-seed `predictions/_draft/` from the experiment's cached extracts → `archive_experiment` for rejected attempts. Review-mode shows a horizontal tab strip (⭐ Active + N attached experiments + `[+]` popover) above the field editor; tabs read from `predictions/_draft/{doc_id}.json` (active, editable, saves to `reviewed/`) or `experiments/{exp_id}/extracts/{doc_id}.json` (read-only, evidence click-to-page still works for PDF navigation).

**Key design decisions (with rationale)**

1. **Extended `useReview` instead of new `useExperimentReview` store.** Tab state is doc-scoped — `attachedExperimentIds`, `activeTabKey`, `extractsByExp` all reset on `open(new_doc)` alongside `entities` / `evidence` / `notes`. A separate store would duplicate `activeDocId`/`page` and split the ground-truth save path (which can only run on ⭐ Active) across stores, creating a tempting bug surface. The field-editor data source is a single derived `displayEntities` selected by `activeTabKey`.

2. **`run_experiment_eval` is foreground synchronous, not a `JobRunner` job.** Lab projects typically have <20 reviewed docs (M2A `us-invoice` dogfood: 5–7). At ~3–5s per extract, a full eval is ~30–100s — acceptable for a tool turn. Defer to `JobRunner` only when projects routinely exceed ~50 reviewed.

3. **`promote_experiment` re-seeds `predictions/_draft/` from the experiment's cached extracts** (spec §3.5 verbatim). Costs a few KB per doc × N but buys immediate Review-mode visibility of the new active without forcing the user to re-extract every doc. The experiment dir is preserved with status=`"promoted"` and `promoted_at` for audit trail; the prompt's `derived_from` lineage chain remains queryable.

4. **`delete_prompt` / `delete_model` blocked by non-archived experiments — promoted DO block.** Archive (recoverable) to unblock deletion of a draft variant. Promoted experiments stay blocking forever — their referenced prompt/model files must be queryable to interpret historical contracts. Closes the M9.2 follow-up that left those deletes only checking active.

5. **Defense-in-depth on `readOnly` for contentEditable spans.** Since React's `disabled` attribute doesn't work on contentEditable, the FieldRow / ObjectField / ArrayField components each independently apply `contentEditable={!readOnly}` at the DOM level AND `if (!readOnly) return` inside their `onBlur` handlers. Even if a parent component accidentally passes the wrong flag, the blur handler still won't mutate state.

6. **Evidence click-to-page deliberately NOT gated by readOnly.** PDF navigation is read-out, not a write — users on experiment tabs still need to navigate the PDF while comparing. The `onJumpToPage` button stays unconditional.

**Hard rules respected**
- Publish fast-path 0 改动 — `freeze_version` / `versions/v{N}.json` / `/v1/{pid}/extract` not touched.
- `reviewed/` is project-scoped — shared across all experiments, ground truth is one set, never duplicated per experiment.
- Experiments NEVER auto-promote — `promote_experiment` is the only path that flips active and requires user-mediated tool call (risk-gated in `emerge_extractor.md` skill copy).
- Agent brain ↔ Extract LLM separation — `extract_with_experiment` resolves provider via `get_provider_for_model(model.provider_model_id)` and calls the adapter directly. Never re-enters the SDK.
- Task-type-agnostic chrome — "experiment" is a generic verb. The vocabulary works for matching/classification tasks as well as extraction.

**Notable in-flight discoveries (filed during execution)**

- **Spec-reviewer caught `doc_id` validation gap in HTTP routes.** The initial T8 commit (`8c08a17`) called `safe_project_id` but missed `safe_doc_id` on the two extract routes. Fix in `6f08a69` aligns with the pattern in `predictions.py` / `reviewed.py` / `docs.py`.
- **Code-reviewer caught `migrate_project_if_needed` missing on 3-of-4 routes.** Only the list route called it; GET-single / GET-extract / POST-run-extract would 404 on pre-M9.1 projects hitting them directly without first going through list. Fix in `d75b612`.
- **`_seed_doc` factoring landed in T5 per T4 reviewer's note.** The minimal-PNG + `meta.json` doc-stub setup is ~10 lines of boilerplate; factoring it out paid off across T6's 4 more tests and the e2e seed.
- **Plan's test scaffolds invented a `fake_provider` fixture; `stub_provider` already existed.** The plan was written against the M2A test convention; T4 onwards rewrote each test to use the existing `stub_provider` (AsyncMock of the Provider protocol) and `make_provider_result(payload)` helper. This is the only sustained adaptation across the backend half.

**Test footprint**
- Backend: 469 → 482 passed (+13 experiment tests across T1/T3/T4/T5/T6/T7/T8/T9), 2 skipped (pre-existing).
- Frontend: 309 → 333 passed across 45 files (+24: api 5, store 4+6, components 9+5, FSSpine 4, ReviewOverlay 5).
- E2E: 7 → 8 specs, all passing (added `experiment-tabs.spec.ts`).
- TypeScript: clean (`tsc --noEmit` no errors).

**Reference**
- Spec: `docs/superpowers/specs/2026-05-12-extraction-comparability-design.md` (§3.3 tools, §3.5 promote semantics, §7.4 review tabs, §7.1 FSSpine layout)
- Plan: `docs/superpowers/plans/2026-05-13-m9-3-experiments-and-review-tabs.md` (18 tasks, TDD per task, subagent-driven with spec + code-quality review per task)
- Range: `f0f6f13..aa1847b` (25 commits: 18 feat/fix/test/docs + 7 polish from review rounds)
- **Live verify done** (2026-05-13) — scenario §4.3 (prompt-variant A/B) ran end-to-end on `us-invoice` workspace against real Gemini-2.5-flash:
  - Created variant `pr_7tqzwqvjx1p3` ("issuer top-right hint") cloned from `pr_baseline` with the `issuer` field description extended by ". Usually appears in the top-right or top-left letterhead of the page".
  - Created experiment `ex_6hxiqgvl3ajd` binding (variant, gemini-2.5-flash) and ran `run_experiment_eval` against the 5 reviewed docs.
  - **Result: macro_f1 = 0.6861 vs baseline 0.85 — variant scored WORSE by 0.16.** Per-field breakdown showed `issuer` itself stayed at 0.80 (the hint didn't help), while `supplier_brn` / `page_number` dropped to 0.0 (model failed to extract these on the variant prompt — a regression from baseline). Verdict: do NOT promote. Exactly the kind of negative signal the experiments axis was designed to surface before the user touches `freeze_version`.
  - FSSpine `experiments/` group rendered the new row with stamp `ran · 0.69` as expected (screenshot `docs/screenshots/2026-05-13-m9-3-experiments-with-real-score.png`).
  - **Note (UI nit, not blocking):** in Phase 1's read-only experiment tab, FieldRow's "edited" red-dot indicator (`●`) appeared on the experiment-tab values because the component compares the rendered value to the captured `originalValue` from mount — but the experiment tab swaps the value via prop change, not via user edit. Cosmetic; deferred as M9.x follow-up if it surfaces again in dogfood.
  - Scenario §4.4 (model A/B) skipped — the workspace's second model (`m_2xpcm8cm1wdx` = `gemini-3-flash-preview`) is a placeholder for an unreleased model, so a real A/B against it would 404. Trivially extensible via the same path once a second real model is configured.

**Spun out**
- M9.4 — `fork_project` + `import_prompt` (cross-project clone-at-time). Swapped with the original M9.4 numbering on 2026-05-13 — fork has real dogfood data (海外发票 samples) ready and is more user-visible than the autoresearch path migration.
- M9.5 — autoresearch path migration (`versions/_candidate/` → `prompts/_candidate/`, "Accept turn N" → "Save turn N as variant"). Originally numbered M9.4; demoted to M9.5 to avoid a numbering skip.
- M9.6 — `readiness_check` rule loosening (some hard fails → soft warns).
- Field-diff power-user view (spec §7.4.1 "compare with…") → M9.x follow-up; tab switch + chat-text score-delta already covers 80%.
- Experiment detail sheet (clicking FSSpine experiment row opens quick-look-style modal) → M9.x follow-up; rows inert in M9.3.
- Global-notes wiring into the extract prompt — `_build_field_instructions` currently consumes only `schema.fields[i].description`. Tracked outside the M9.x family.




### 2026-05-14 — ✅ cross-project fork + import_prompt (M9.4 shipped, pending live dogfood)

**Status**: resolved — `fork_project` and `import_prompt` are two clone-at-time tools that let users reuse prompt/model setup across projects without any live link. Backend + frontend wiring complete, e2e green, 486/488 backend tests pass, 333/333 frontend tests pass. T8 live dogfood (UK invoice fork from us-invoice) is pending user execution; the chat path + skill section are in place.

**What changed**
Two new MCP tools:

- `fork_project(src_pid, name, include_docs=False)` — clones an entire project's prompt/model setup into a fresh `project_id`. Whitelist copy: `project.json` (rewritten with the new name + `active_version_id=None`), all `prompts/*.json`, all `models/*.json`. Skips everything else (chats, reviewed, predictions/_draft, experiments, versions, metrics — all project-bound). `include_docs=True` hardlinks every `docs/` file into the new project with `shutil.copy2` fallback on `OSError`. `migrate_project_if_needed(src_pid)` runs first so legacy schema.json projects fork cleanly without carrying transition cruft. `ForkSourceNotFoundError` raised pre-mint to avoid phantom dirs on failure.

- `import_prompt(src_pid, src_prompt_id, into_pid, new_label?)` — clones a single prompt variant from one project to another. Always mints a fresh `pr_*` id (never reuses `src_prompt_id` — would collide if dest already has the same name). Copies schema + global_notes verbatim. Sets `derived_from = "{src_pid}/{src_prompt_id}"` as lineage display string; no live link. `new_label` defaults to source label when None or empty.

**Disk-layout decision matrix** (locked at plan time, validated by T1's spec reviewer):

| Subdir / file | Action | Why |
|---|---|---|
| `project.json` | copy + rewrite (new pid, new name, `active_version_id=None`) | the whole point — fork starts from src's project metadata |
| `prompts/*.json` | copy | named variants are what the fork carries forward |
| `models/*.json` | copy | model configs are cheap and the fork user intent is "same setup, new domain" |
| `prompts/_candidate/` | skip | autoresearch staging is session-bound to src |
| `experiments/` | skip | per-doc extracts depend on docs (skipped); meta-only copy dangles |
| `versions/` | skip | each project starts fresh publish lineage at v1; `derived_from` audit on future freeze records fork origin |
| `predictions/_draft/` | skip | per spec §3.4 |
| `reviewed/` | skip | ground truth tied to source docs not copied |
| `docs/` | skip default; hardlink-or-copy with `include_docs=True` | per spec §3.4 |
| `chats/` | skip | conversation history is personal/session state |
| `metrics/` | skip | depends on reviewed which is not copied |
| `_keys.json` | skip (workspace-global) | hard rule — keys never fork |

**Decisions affirmed**

- **Whitelist beats blacklist** for `fork_project`. A short explicit copy list survives future disk-layout additions without growing exclusion rules.
- **Lean bootstrap.** Only `docs/`, `prompts/`, `models/` mkdir'd in the new project — `predictions/_draft/`, `versions/`, `chats/` are created lazily by their writers (every read path guards `.exists()`, verified by T1's spec reviewer across 8+ representative read paths in routes/projects, tools/predictions, tools/publish, tools/extract, tools/experiment, tools/score, chat/log, workspace/paths). Resolves a plan-internal contradiction.
- **`versions/` not copied.** Each project's publish lineage is independent. The fork's first freeze will be `v1`, with `derived_from` audit field on `versions/v{N}.derived_from` recording "this came from src_pid" if needed (spec §6.1).
- **`experiments/` not copied.** Even meta-only would be misleading without the per-doc extracts (which depend on docs not being copied).
- **`import_prompt` always mints a fresh id**, never reuses `src_prompt_id`. Lineage is in `derived_from`, not in the id.
- **`include_docs=True` uses hardlink with `copy2` fallback.** Cheapest "clone" of bytes; new project owns its filesystem entries. Known caller risk (documented in skill copy): re-uploading the same `doc_id` in src diverges silently.

**Surface impact**

- 2 new HTTP routes: `POST /lab/projects/fork` (validates `body.src_pid` via `safe_project_id`; maps `ForkSourceNotFoundError` → 404 `project_not_found`) and `POST /lab/projects/{pid}/prompts/import` (reuses `_project_or_404` for dest; maps `PromptNotFoundError` → 404 `prompt_not_found`).
- 2 new MCP wrappers in `build_emerge_mcp` + 2 names appended to `_EMERGE_TOOL_NAMES` (allowlist).
- Frontend `useChat.handleToolResult` (`chat.ts`) extends two existing OR-chains: `fork_project` joins the `useProjects.refresh()` branch (alongside `create_project`/`freeze_version`); `import_prompt` joins the prompt-mutation branch that invalidates schema + prompts and reloads prompts for the current project.
- `emerge_extractor.md` skill copy gains a "Cross-project clone (M9.4)" section explaining when to use each tool and the typical post-import workflow chain (`create_experiment` → `extract_with_experiment` → user judgment → `promote_experiment` or `archive_experiment`), plus 2 new risk-gate entries (always confirm before fork or import).

**Hard rules respected**

- Forks are clone-at-time (no live link / no transclusion) — verified in T1/T2 tests.
- `_keys.json` never forks (workspace-global; whitelist excludes implicitly).
- `predictions/_draft/`, `chats/`, `reviewed/` never copied — protects audit / privacy / ground-truth boundaries.
- Publish fast-path zero changes — `versions/` skipped, `freeze_version` / `/v1/{pid}/extract` untouched.
- Task-type-agnostic vocabulary — "fork" / "import" are generic verbs.

**Notable in-flight discoveries (filed during execution)**

- **Plan-internal contradiction caught by T1's spec reviewer.** The plan's reference impl mkdir'd `predictions/_draft/`, `versions/`, `chats/` (matching `create_project`'s shape), but the plan's own test asserted those dirs do NOT exist after fork. The implementer kept the test contract (lean bootstrap) and the reviewer validated by checking 8+ representative read paths — none assume the dir exists. The plan was patched mid-execution to match the lean bootstrap (commit `b10bdec`).
- **No actual implementation gaps found across T1–T7.** Plan executed straight-through with no BLOCKED or major rework — the spec was tight enough that each subagent just had to copy the plan code blocks. The two minor polish items (lock-scope comment on fork's `project_lock`, plan reference cleanup) landed in the same `b10bdec` commit.

**Test footprint**
- Backend: 482 → 486 passed (+4: 4 fork unit + 4 import_prompt unit + 5 fork-and-import route + 1 e2e + 1 registration assertion = 15 new tests; some adjacent counts shifted), 2 skipped (pre-existing).
- Frontend: 333 / 0 changed (T5 was a behavioral extension to existing OR-chains; no test additions needed because the cross-store-refresh tests are integration-level via dogfood).
- TypeScript: `tsc -b --noEmit` clean.

**Reference**
- Spec: `docs/superpowers/specs/2026-05-12-extraction-comparability-design.md` (§1.4 cross-project clone-at-time, §3.4 tool signatures, §4.1 UK invoice fork scenario, §4.2 multi-import scenario, §5.3 prompts/_candidate not importable, §10 YAGNI)
- Plan: `docs/superpowers/plans/2026-05-14-m9-4-fork-and-import.md` (9 tasks, TDD per task, subagent-driven with spec + code-quality review per task)
- Range: `1732f2e..4fe82f2` (8 task commits + 1 polish)
- **Live verify pending** — T8 dogfood (fork us-invoice → uk-invoice, upload UK PDFs from `/Users/qinqiang02/job/产品/文档AI/海外发票样本/荣耀_金蝶发票测试样例_1.20/英德法V1/`) is user-driven. Will append a follow-up entry with results when run.

**Spun out**
- Frontend dedicated "Fork project" / "Import prompt" button surfaces (chat-only today) → wait for user signal.
- `fork_project(include_reviewed=True)` opt-in from spec §3.4 — not implemented; defer until user demand surfaces.
- Hardlink-aware "stale fork" warning (re-upload of same doc_id in src diverges silently) — only relevant if hardlinking becomes default.

---

### 2026-05-13 — Composer: plain Enter inserts newline; ⌘/Ctrl+Enter is the only submit; OS-aware footer

- **Status**: 🟡 Pending
- **Area**: `Chat/Composer`
- **Files**: `frontend/src/components/Chat/Composer.tsx`,
  `frontend/tests/unit/Composer.test.tsx`,
  `frontend/tests/e2e/{walking-skeleton,chat-layout,publish-modal}.spec.ts`
- **Type**: interaction (intentional behavior change)

**What changed**
1. Plain Enter no longer submits when the slash menu is closed — it now
   inserts a newline like a normal textarea. Submission is **only**
   ⌘+Enter (macOS) / Ctrl+Enter (Win/Linux), matching the footer hint.
   Inside the open slash menu, Enter still picks the active command
   (autocomplete affordance), which closes the menu without submitting.
2. The footer kbd glyph is OS-aware: shows `⌘` on Mac, `Ctrl` elsewhere.
   Detection uses `navigator.userAgentData.platform` with fallbacks to
   `navigator.platform` / `userAgent` — non-Mac is the safe default if
   `navigator` is unavailable.
3. Tests updated: unit suite now asserts plain Enter is a no-op and
   ⌘/Ctrl+Enter is required; e2e specs press `ControlOrMeta+Enter`
   (cross-platform Playwright modifier) instead of `Enter`.

**Why**
Reverses the "plain Enter falls through to submit() once a full command
is typed" branch from the 2026-05-11 fix. The footer always advertised
`⌘ ↵`, but plain Enter was secretly also wired up, which made the hint
misleading and surprised users who expected Enter to wrap a line in a
multi-line textarea. The 2026-05-11 change can be considered superseded
by this entry — only the slash-menu pick-on-Enter and the
completed-command menu-dismissal logic survive.

**Reference**
- Updated tests: `frontend/tests/unit/Composer.test.tsx` — 7/7 pass;
  the renamed "plain Enter does not submit — only ⌘/Ctrl+Enter does"
  test types `hello{Enter}{Ctrl+Enter}` and confirms `onSubmit` fires
  exactly once with the trimmed text.
- E2E modifier: `textarea.press('ControlOrMeta+Enter')` works against
  both macOS (⌘) and Linux/Windows (Ctrl) runners.

---

### 2026-05-13 — Composer: Stop button + Esc cancels an in-flight chat turn

- **Status**: 🟡 Pending
- **Area**: `Chat/Composer`
- **Files**: `frontend/src/stores/chat.ts`,
  `frontend/src/components/Chat/Composer.tsx`,
  `frontend/src/components/Chat/ChatPanel.tsx`,
  `frontend/src/index.css`
- **Type**: interaction (additive — new affordance)

**What changed**
1. The chat store now creates an `AbortController` per turn, threads its
   signal into the SSE `fetch`, and exposes `cancel()`. Aborts surface
   as `AbortError` and are swallowed silently (no `error` event added
   to the chat log).
2. The Composer's row2 swaps the `⌘↵ send` hint for a **Stop · Esc**
   pill whenever `disabled` is true and `onCancel` is wired. Clicking
   the pill or pressing **Esc** anywhere on the page (window-level
   listener active only while busy) calls `cancel()`. Mirrors
   claude.ai's stop affordance.
3. Backend untouched. `sse_starlette` already detects client
   disconnect; the cancellation propagates into `chat_turn`'s
   `ClaudeSDKClient` context, which exits via `__aexit__`. The
   `finally:` clause still persists `latest_sid` so the next turn can
   resume normally.

**Why**
Once a turn is in flight, the textarea is disabled and there is no way
to bail out of a long agent response or a runaway tool loop — users
have to wait for `max_turns=20` to exhaust. Matching claude.ai's Stop
button + Esc shortcut gives the user the same recovery they already
have muscle memory for. SSU: frontend abort + relying on sse_starlette
disconnect detection avoids exposing a separate `/lab/chat/cancel`
endpoint or tracking per-request SDK clients.

**Reference**
- Cancel path: `AbortController.abort()` → `fetch` signal trips →
  `reader.read()` rejects with `AbortError` in `streamSSE` → consumer
  `catch` filters by `signal.aborted` to stay silent.
- Tests: `frontend/tests/unit/Composer.test.tsx` 7/7 still pass — the
  new `onCancel` prop is optional, so existing call sites compile and
  the Stop pill only renders when both `disabled` and `onCancel` are
  set (busy state only).

---

### 2026-05-13 — Chat thread: right-aligned user bubble + sr-only turn meta (reverses 2026-05-12 terminal-style decision)

- **Status**: 🟡 Pending
- **Area**: `Chat/Turn`, chat thread visual identity
- **Files**: `frontend/src/components/Chat/Turn.tsx`,
  `frontend/src/index.css`
- **Type**: visual (reversal of prior decision)

**What changed**
1. **`Turn.tsx`** — the per-turn `<div class="turn-meta">…<span class="who">you</span> · <span class="ts">…</span> <span class="rule"/>…</div>` header is gone from the visual layout. The `<span class="who">` (and a sibling `sr-only` "who · ts" descriptor) are still emitted in the DOM as screen-reader-only nodes, so a11y plus existing unit tests that assert on the `you` / `agent` text nodes and `.who.agent` className still pass. The container className branches: `turn-you` for user turns (right-aligned), `turn-agent` for agent turns (full-width).
2. **`index.css`** — `.turn` simplified to a column flex with `gap:6px`; new `.turn-you{align-items:flex-end}` and `.turn-agent{align-items:stretch}`. `.msg` body stays at 17px but gets claude.ai-style breathing room: `line-height` 1.6 → 1.7 and paragraph margin `.65em` → `.85em`. `.msg.user` becomes a right-aligned `var(--paper-2)` pill (`border-radius:14px; padding:10px 16px; max-width:min(75ch,85%)`) — the smart-quote `::before/::after` pseudo-elements and `font-style:italic` are removed. Composer textarea drops italic and shrinks from 16px to 14.5px (placeholder no longer italic) so the input sits a clear step below the body in the visual hierarchy.
3. The `▸` ochre caret in the composer row stays; slash chips, send/stop button styling, and `conv-inner gap:28px` are untouched.

**Why**
The 2026-05-12 "terminal-style thread" decision (logged in the `chat-layout` E2E realignment entry above) intentionally removed the right-aligned bubble in favor of an all-left, italic, smart-quoted user line. After a week of dogfooding the user requested the visual move closer to claude.ai — right-aligned paper-2 pill for the user, full-width prose for the agent, no per-turn metadata line — while keeping emerge's editorial identity (Lora serif, paper palette, no neutral-grey UI grey). This reversal restores role-by-alignment as the primary visual cue. The "crowded" feedback turned out to be about the italic + smart-quotes + meta-rule packing (now gone), not body size — body stays at 17px and instead earns its breathing through line-height 1.7 and paragraph spacing .85em, matching the claude.ai prose feel. Composer alone shrinks to 14.5px so the input doesn't compete with the thread for typographic weight.

**Reference**
- Reverses: `2026-05-12 — E2E specs realigned to M7 UI…` (above), which had documented the terminal-style `.msg.user` italic + smart-quote rendering as the post-M7 state.
- Test compatibility: the e2e `chat-layout.spec.ts` only asserts `.msg.user` is visible and contains the typed text — both still hold. The unit `tests/unit/UserBubble.test.tsx` asserts `getByText('you')` / `getByText('agent')` and `.who` className, which the preserved `sr-only` `<span class="who">` continues to satisfy.
- No E2E selector churn required; no test edits in this change.

---

### 2026-05-13 — Chat body shrinks to 15px / 1.6 (reverses "body stays at 17px" from the entry above)

- **Status**: 🟡 Pending
- **Area**: `Chat` body typography
- **Files**: `frontend/src/index.css`
- **Type**: visual (reversal of prior decision in the same day's earlier entry)

**What changed**
`.msg` font-size 17px → 15px, line-height 1.7 → 1.6, paragraph margin .85em → .7em. Nothing else moved — bubble padding, composer 14.5px, slash chips, tool blocks unchanged.

**Why**
User did a direct side-by-side with claude.ai's shared-chat view and the 17px serif body still read noticeably larger and more breathy than claude.ai's body text, even after the italic/smart-quote/meta-rule reductions from the earlier entry today. The prior "the crowdedness was packing, not size" hypothesis turned out to be only half right: removing the packing helped, but the body itself is also genuinely too large for the three-pane shell. 15px / 1.6 is the size claude.ai uses for its chat prose; matching it removes the residual "bigger than the reference" feel without touching the editorial identity (still Lora serif, paper palette, paper-2 user pill, full-width agent prose).

**Reference**
- Reverses (partially): the prior 2026-05-13 entry above which kept body at 17px and earned breathing room via line-height/paragraph margin instead.
- Composer remains at 14.5px (still a clear step below body, 15px → 14.5px is a half-step rather than the previous full step from 17px).
- No selector or DOM changes; existing chat-layout E2E and UserBubble unit tests untouched.

