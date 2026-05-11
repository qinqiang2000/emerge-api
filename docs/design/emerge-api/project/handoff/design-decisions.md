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

### YYYY-MM-DD — Example: invoice table empty state

- **Status**: 🚨 Needs design review
- **Area**: `ReviewDoc` → invoice table
- **Files**: `src/components/InvoiceTable.tsx`
- **Type**: new-state

**What changed**
Added an empty state for when an uploaded PDF has no extractable line items. Used the existing `EmptyState` primitive with a generic "No items found" message and a re-upload CTA.

**Why**
The Design project shows the populated state only. Real PDFs sometimes parse to zero rows.

**Reference**
- Original Design: `docs/design/handoff-2026-05-08/review-doc.png`
- Current implementation: `docs/screenshots/2026-05-10-empty-table.png`

**Open questions for Design**
- Is "re-upload" the right primary CTA, or should it offer "edit manually"?
- Should this state show the JSON panel still, or hide it?

---

<!-- Archive resolved entries here once they are folded into a new Handoff -->

## Archive

(empty)
