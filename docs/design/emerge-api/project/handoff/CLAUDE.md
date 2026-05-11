# CLAUDE.md

> Persistent rules for Claude Code working in this repo.
> Place this file at the **root of the Code repository** (not the Design project).

---

## Project context

- **Product**: <one-line description>
- **Design source of truth**: <Design project URL>
- **Last Handoff snapshot**: `docs/design/handoff-YYYY-MM-DD/`
- **Design decisions log**: `docs/design-decisions.md` — read this before changing UI

When in doubt about visual / interaction behavior, the Design project wins. When in doubt about logic / data flow, this repo wins.

---

## Boundaries — what Claude Code MAY change autonomously

✅ **Free to change without asking**
- Logic, data fetching, state management, error handling
- Performance optimizations that don't change rendered output
- Adding tests, fixing types, refactors that preserve DOM/CSS output
- Copy fixes for typos, grammar, obvious wording bugs
- Accessibility fixes (aria, keyboard nav, contrast bumps within token range)

⚠️ **Change, but log to `docs/design-decisions.md`**
- Spacing tweaks ≤ 4px to fix layout bugs
- Color swaps **within** the existing design token set
- Adding empty / loading / error states using existing component primitives
- Truncation, overflow, responsive breakpoint adjustments

🛑 **Do NOT change without going back to Design**
- New colors, fonts, font sizes, or radii outside the token set
- New component types or visual patterns not present in the Handoff
- Information architecture: nav structure, page hierarchy, field order in forms
- Any change that would make a screenshot diverge meaningfully from the Design project
- Iconography choice, illustration style, brand-adjacent visual decisions

If you hit a 🛑 case, **stop and surface it**: write a note in `docs/design-decisions.md` under "Needs design review" and ask the user to handle it in the Design project.

---

## Design tokens

Tokens live in `<path/to/tokens>`. Treat this file as generated — do not hand-edit it. To change tokens, change them in the Design project and re-run Handoff.

Components must consume tokens by name, never by literal value:

```tsx
// ✅
<div className="bg-surface-1 p-4 rounded-md" />

// 🛑
<div style={{ background: '#f6f4ef', padding: 16, borderRadius: 8 }} />
```

---

## Component contract

Every component imported from the Handoff snapshot has a **frozen public API**:
- Props names and types
- Slots / children expectations
- Variant names

You may refactor internals, but do not rename or remove props without checking `docs/design-decisions.md` and adding an entry there.

---

## Workflow rules

1. **Before any UI-shaped change**: skim `docs/design-decisions.md` for prior context on the same area.
2. **After any UI-shaped change**: append an entry to `docs/design-decisions.md` (see format in that file).
3. **Before opening a PR that touches UI**: take screenshots of the changed screens at standard breakpoints and drop them in the PR description so design review is fast.
4. **When you find missing states** (empty / loading / error / overflow): build a placeholder using existing primitives, log it under "Needs design review", and keep moving — don't block.

---

## Things to never do

- Never invent new SVG illustrations or icons. Use the icon set from the Handoff or a placeholder box with a label.
- Never use AI-slop visual tropes: gradient hero backgrounds, glassmorphism, emoji as UI affordances, left-border accent cards — unless they exist in the Design project already.
- Never inline copy that's marketing/brand-facing. Surface those strings to the user for Design / PM review.
- Never silently downgrade an interaction (e.g. replace a custom drag with a select) without logging it.

---

## Updating this file

This file is the contract between Design and Code. If a rule here is wrong or missing, update it in the same PR that exposes the gap.
