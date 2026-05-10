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
