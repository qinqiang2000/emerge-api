# Schema Quick-look — read-only viewer for `schema.json` + frozen versions

> **Status**: design (2026-05-12)
> **Parent spec**: `2026-05-08-agent-native-design.md`
> **Milestone target**: **M9.0** — schema-quick-look prelude. Ships standalone before any M9a-d data-model work.

The user can name a `schema.json` in the FSSpine and a `schema.json` card in the right rail, but neither responds to a click, and the right-rail card silently truncates the field list at 7 with a non-interactive `+ N more` hint. There is no path to see the full schema without opening a terminal and `cat`-ing the file.

This spec adds a single read-only **Quick-look sheet** opened from three entry points. It deliberately under-commits: nothing about the schema data model changes; cross-project fork, multi-schema A/B, and AutoResearch wiring are filed as M9a-d follow-ups so this milestone can ship in one chat session.

---

## 0. Why now, why this scope

The user reported the immediate papercut (`+ N more` not clickable, FSSpine rows inert) but the underlying complaint is bigger: **`schema.json` is treated as a string inside a project's folder, not as a first-class object the user wants to inspect, reuse, and compare**. The honest fix is to lift schema into a global namespace and add fork / compare flows — that is large enough to need its own spec.

This spec deliberately stays on the surface that the user can hit *today*: a sheet that opens, shows the full schema, and closes. But the sheet is **shaped like a schema-object viewer, not a project-attribute viewer** — its header takes a `schema_id` (right now fallback to `pid`), it reserves a `lineage` row, and each field card reserves a `review-notes` hint slot. When M9a lands, the viewer doesn't need to be redesigned; the placeholders fill in.

---

## 1. Goals & non-goals

### Goals (G)

- G1 — A user who wants to see the complete current schema for a project can do so in one click from either the left FSSpine or the right ContextSurface.
- G2 — The user can also inspect a frozen `versions/v{N}.json` from the FSSpine.
- G3 — Both field-level (name / type / required / description / examples) and raw-JSON views are available without a separate flow.
- G4 — The viewer makes the difference between `description` (prompt) and `reviewed.notes` (AutoResearch input) visible at the bottom, so the user does not silently confuse the two.
- G5 — The component is **schema-shaped** so M9a (schema-first-class) and M9d (AutoResearch UI) can plug into the same component without redesign.

### Non-goals (NG)

- NG1 — No edit affordance of any kind in the sheet (red line: schema mutations go through chat / `write_schema`).
- NG2 — No version diff between v5 and v6 (defer to a future viewer milestone if the user asks).
- NG3 — No schema fork / import / cross-project reference (M9a/b).
- NG4 — No same-project multi-schema picker or A/B comparison (M9c).
- NG5 — No keyboard-only navigation through fields (Esc-to-close is in scope; Cmd-K palette is not).
- NG6 — No PDF / Markdown / arbitrary-file preview through the same sheet — viewer architecture allows this in the future but only `schema` and `version` `kind` ship now.

---

## 2. UX

### 2.1 Entry points

| Surface | Element | Action |
|---|---|---|
| Right rail (`ContextSurface.tsx`) | `schema.json` card title | click → open Quick-look for current project's schema |
| Right rail (`ContextSurface.tsx`) | `+ N more` row | click → same as above |
| Left FSSpine (`FSSpine.tsx`) | `schema.json` row | click → same as above |
| Left FSSpine (`FSSpine.tsx`) | `versions/v{N}` leaf | click → open Quick-look for that frozen version |

The right-rail `schema.json` card title row gets a subtle pointer-cursor; FSSpine `schema.json` and `versions/v{N}` rows get pointer-cursor on hover. No new icons / chevrons.

All other FSSpine nodes (`docs/`, `reviewed/`, `versions/` folder header, `README.md`) **stay inert in this spec**. Docs already have a click path through ContextSurface's doc list → ReviewMode; the rest have no canonical viewer yet.

### 2.2 Sheet layout

Center modal, portal'd to `<body>`, full-screen scrim:

```
┌───────────────────────────────────────────────────────────────┐
│  schema.json                              v6 · active     ✕  │
│  derived from: —                                              │
│  ───────────────────────────────────────────────────────────  │
│  [ fields (8) ]   [ raw json ]                                │
│  ───────────────────────────────────────────────────────────  │
│                                                                │
│   invoice_number     string     required                      │
│     The unique invoice identifier issued by the supplier.    │
│     examples · INV-2025-001, INV-2025-002                    │
│   ─────                                                        │
│   issuer             string     required                      │
│     …                                                          │
│                                                                │
│  ───────────────────────────────────────────────────────────  │
│  description goes into the prompt at publish time.            │
│  review notes (per-doc) feed AutoResearch only — they         │
│  propose description tweaks but never become prompt.          │
└───────────────────────────────────────────────────────────────┘
```

**Header line 1**: `schema.json` or `versions/v{N}` (the label matches the entry point); version badge (`v6 · active` for the live `schema.json` when there is an active frozen version; `v6 · frozen` for `versions/v6`; `v0 · draft` when no version has been frozen yet); a close `✕`.

**Header line 2 — lineage row**: `derived from: —` placeholder for now. M9b fills this in (`derived from: us-invoice / v6 / 2026-05-10`).

**Tabs**: `fields (N)` (default) and `raw json`.

**Fields tab**: vertical scroll list, one block per top-level field:
- Line 1: `<name>  <type>  [required]` — type rendered as italic monospace, `required` as a small all-caps pill if true.
- Line 2: `<description>` (full text, wraps; if empty, render `(no description)` in muted italic).
- Line 3 (only if `examples` present): `examples · v1, v2, v3` joined with `, `, capped at 6, then `… +N more`.
- Line 4 (only if `enum` present): `enum · a, b, c`.
- Line 5 — **review-notes hint slot, reserved but rendered as `—` for now**. The slot exists in the DOM so M9d wiring is a CSS / data swap, not a layout change.
- `array<object>` fields show `children: N` and a disclosure caret that toggles a nested block. Children render with the same `FieldCard` template recursively (each level indents 12px). No depth cap — `SchemaField.children` is self-referencing in the backend model and most real schemas are 1-2 deep; recursion is cheaper than a depth limit + fallback rendering path.

**Raw JSON tab**: pretty-printed JSON in a monospace block with syntax tint (ink / ochre for keys, moss for strings, rose for numbers — match `tokens.css` palette). A `copy` button top-right (this is read-out, not mutation — does not violate agent-native).

**Bottom hint**: the two-sentence explanation (the diff between `description` and `reviewed.notes`) renders in `--ink-4` muted style. No link / button; the goal is concept clarity, not navigation.

### 2.3 Open / close behaviour

- Open: click any entry point → sheet animates in (200ms fade + 8px translate).
- Close triggers: `Esc` key, click on scrim (outside sheet), click on `✕`.
- Project switch: `SchemaQuickLook.tsx` subscribes to `useProjects.selectedId`; on change it calls `quicklook.close()` (the open sheet was about the previous project's schema, leaving it open would be misleading).
- The sheet is **modal**: chat composer is not focusable while open. Rationale: user's attention is on reading; preserving chat focus has no value and the visual layering is confusing.

### 2.4 Empty / error states

- Project has no schema yet (`fields.length === 0`): sheet still opens, fields tab shows `no schema yet — type /init in the chat`, raw-json tab shows `{ "fields": [] }`. Lineage row stays `—`.
- Backend raw-json fetch fails: raw-json tab shows `failed to load raw json` muted text + a `retry` link. Field cards continue to work (they read from `useSchema`).
- Version not found (FSSpine click on a `v{N}` that was deleted out-of-band): sheet opens with `version not found` in the body. (This is an edge case; FSSpine listings come from the same workspace scan, so divergence requires a manual filesystem edit.)

---

## 3. Data flow

### 3.1 New Zustand store: `quicklook.ts`

```ts
// frontend/src/stores/quicklook.ts
type QuickLookTarget =
  | { kind: 'schema'; pid: string }
  | { kind: 'version'; pid: string; versionId: string }

interface QuickLookState {
  target: QuickLookTarget | null
  rawJson: { value: string | null; loading: boolean; error: string | null }

  openSchema(pid: string): void
  openVersion(pid: string, versionId: string): void
  close(): void
  loadRaw(): Promise<void>   // called on tab switch to 'raw json'
}
```

- `openSchema` / `openVersion` set `target`, reset `rawJson` to `{ value: null, loading: false, error: null }`.
- `loadRaw` is lazy — only called when the user switches to the raw-json tab. Once loaded, the value is cached for the lifetime of `target`; closing or switching target resets it.
- `close()` sets `target` to `null`; the portal returns `null`.

### 3.2 Field source (existing `useSchema`)

The fields tab reads from the existing `useSchema.byProject[pid]`. The store already provides `load()` / `invalidate()` hooks consumed by `useChat.handleToolResult` (post-M5), so the sheet sees up-to-date fields without its own fetch.

For `kind === 'version'`, the fields tab fetches the frozen list separately (see §3.4) and renders it without touching `useSchema`. We do **not** populate `useSchema` with a frozen version's fields — `useSchema` is the lab edit state.

### 3.3 Backend endpoints

Two new read-only endpoints, both in `backend/app/api/routes/lab/`:

```
GET /lab/projects/{pid}/schema/raw
  → 200 text/plain  pretty-printed JSON of schema.json
  → 404 schema_not_found  when schema.json missing on disk

GET /lab/projects/{pid}/versions/{vid}/raw
  → 200 text/plain  pretty-printed JSON of versions/{vid}.json
  → 200 application/json  { fields: SchemaField[], frozen_at, …passthrough }
                          when ?shape=fields (used by the fields tab for kind=version)
  → 404 version_not_found  when versions/{vid}.json missing
```

Why text/plain for raw: the response is shown verbatim in a `<pre>`. Pretty-print on the server side guarantees a single canonical formatting (2-space indent, sorted top-level keys consistent with workspace writes); the frontend doesn't re-stringify, so any future schema metadata (e.g. `frozen_at`, `freeze_reason`) shows up automatically.

`shape=fields` query param on the version endpoint returns the parsed `SchemaField[]` so the fields tab can render the same template as `kind=schema` without reimplementing parsing.

### 3.4 Schema-shaped header data

The header takes a `schemaId` and a `lineage` field. Right now:

- `schemaId`: synthesised on the frontend as `${pid}` (for `kind=schema`) or `${pid}/${versionId}` (for `kind=version`). Displayed in the header line 1's first slot.
- `lineage`: hardcoded to `null` → renders `—`. The DOM slot, store field, and CSS row are committed today so M9b just changes the data source.

When M9a lands, `schemaId` becomes a real workspace-global id read from the project's `active_schema_id` (or the frozen version's bookkeeping). The component contract does not change.

---

## 4. Architecture

### 4.1 Components

```
frontend/src/components/QuickLook/
├── SchemaQuickLook.tsx        # portal wrapper, scrim, escape handler
├── QuickLookHeader.tsx        # schemaId + version badge + lineage row + close
├── FieldsTab.tsx              # field cards (recursive for array<object>)
├── FieldCard.tsx              # one field block (name/type/desc/examples/enum/notes-slot)
├── RawJsonTab.tsx             # <pre> + copy button + load/error handling
└── styles.css                 # scoped styles using existing tokens
```

The sheet is mounted once in `App.tsx` (sibling to the existing shell), reads `quicklook.target` from the store, and renders `null` when target is `null`. No router involvement.

### 4.2 Touched files

- New: 6 files under `frontend/src/components/QuickLook/` + `frontend/src/stores/quicklook.ts`.
- New: `backend/app/api/routes/lab/raw.py` (or extend existing schema route file).
- Edited: `frontend/src/components/Context/ContextSurface.tsx` — make schema card title and `+ N more` row clickable, dispatch `openSchema(pid)`.
- Edited: `frontend/src/components/Spine/FSSpine.tsx` — wire `schema.json` and `versions/v{N}` rows to `openSchema` / `openVersion`. Other rows untouched.
- Edited: `frontend/src/App.tsx` — mount `<SchemaQuickLook />` once.
- Edited: `backend/app/api/__init__.py` (or wherever lab routers are aggregated) — register new routes.

### 4.3 Existing-store reuse

- `useProjects` — for `active_version_id` to compute the version badge.
- `useSchema` — fields for `kind=schema`.
- No use of `useDocs`, `useEval`, `useReview`, `useChat`.

---

## 5. Test plan

### Backend

- `tests/test_lab_schema_raw.py` — happy path returns pretty-printed JSON; 404 on missing schema; 404 on missing version; `shape=fields` returns parsed `SchemaField[]` JSON.

### Frontend (Vitest + RTL)

- `SchemaQuickLook.test.tsx` — opens on `openSchema`, closes on Esc / scrim / ✕ / project switch.
- `FieldsTab.test.tsx` — renders all fields (no MAX_VISIBLE truncation), shows `(no description)` placeholder, renders `array<object>` children when expanded, hides empty `examples` / `enum` lines.
- `RawJsonTab.test.tsx` — lazy load on tab switch, loading / error / success states, copy button writes to clipboard.
- `ContextSurface.click.test.tsx` — schema card title click dispatches `openSchema(pid)`; `+ N more` click dispatches `openSchema(pid)`.
- `FSSpine.click.test.tsx` — `schema.json` row dispatches `openSchema(pid)`; `versions/v6` row dispatches `openVersion(pid, 'v6')`; `docs/` row remains inert.

### E2E (Playwright)

One scenario in `frontend/tests/e2e/schema-quicklook.spec.ts`:

1. Open `us-invoice` project.
2. Click right-rail `schema.json` card title.
3. Assert sheet visible, 8 field rows in fields tab.
4. Switch to raw json tab, assert non-empty `<pre>`.
5. Press Esc, assert sheet closes.
6. Open FSSpine `versions/v6`, assert sheet header shows `versions/v6` and `frozen` badge.

---

## 6. Open questions / decisions deferred

- **Active-version badge label**: when `schema.json` differs from the active frozen version (e.g. user edited a description since `/publish`), should the badge say `v6 · active` or `v6 · drifted`? Decision: this milestone always shows `v6 · active` if `active_version_id` is set; drift detection requires hashing both files and is M9-adjacent. Filed as cross-cutting follow-up below.
- **Field reorder visualisation**: schema is a list, order matters for prompt. The sheet renders in array order; we do not show ordinal numbers. Decision: re-evaluate when M9 introduces multi-schema compare (ordering matters there).
- **Per-field copy button**: nice-to-have, defer. `copy` on the raw-json tab handles 95% of "I want to paste this somewhere".

---

## 7. M9 follow-ups (out of scope, filed in ROADMAP)

Filed under ROADMAP "What each milestone delivers" as proposed milestones:

- **M9a — schema-first-class**: lift `schema.json` to `workspace/schemas/<sid>/v{N}.json`; project references `sid`; migration tool for existing projects. Unblocks M9b and M9c.
- **M9b — schema fork**: `/fork <other-project>/<version>` slash-command + tool; clone-at-fork-time semantics (user's confirmed model: UK fork of US is a new schema, no live link); lineage display in Quick-look header.
- **M9c — schema compare**: same project can hold multiple candidate schemas; eval runs per schema; metrics panel shows per-schema columns; Quick-look gains a schema-picker.
- **M9d — autoresearch UI** (also addresses the description-vs-review-notes confusion at its root): review notes are surfaced as proposed description tweaks in a dedicated `autoresearch/` panel; Quick-look field cards' notes-hint slot becomes "`N notes propose updates · open`" linking to that panel.

The cross-cutting "drift detection" follow-up (when `schema.json` ≠ active version) folds into M9a's bookkeeping.
