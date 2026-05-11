# M7.2 — Metrics Panel (`/eval` → right-rail `metrics/`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended, per user memory) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `precision 0.94 / recall 0.91 / f1 0.92 / coverage 100%` placeholder in `ContextSurface`'s `metrics/` section with real data from the project's latest `metrics/eval_*.json` snapshot (the `score` tool already persists these), and refresh it whenever `/eval` completes. Resolves the 2026-05-10 🟡 Pending design-decisions entry "`metrics/` ContextSurface section uses placeholder data" and the matching open follow-up in `ROADMAP.md`.

**Architecture:** Three thin pieces, no new shapes:
1. **Backend read endpoint** `GET /lab/projects/{project_id}/evals/latest` — opens `metrics_dir(workspace, pid)`, returns the lexicographically-last `eval_*.json` parsed into a `ScoreResult` (the same Pydantic model `run_eval` returns), 404 when none exists. Filenames are `eval_YYYY-MM-DDTHH-MM-SSZ.json` so lex-sort == chronological — no separate sort key needed.
2. **`useEval` Zustand store** mirroring `useSchema`: `byProject[pid]: ScoreResult | null`, `loading[pid]`, `load(pid)` (cache-first), `refresh(pid)` (force fetch), `invalidate(pid)`, `reset()`.
3. **`ContextSurface` rewrite** — reads `useEval`, derives macro precision / macro recall / macro f1 / coverage from `per_field` + `n_reviewed`/`n_docs`, shows "no eval yet" empty state when null. Cross-store hook: `useChat.handleToolResult` calls `useEval.refresh(pid)` after a successful `mcp__emerge_tools__score` call (same pattern as `useSchema.invalidate` after `write_schema`).

**Tech Stack:** Backend FastAPI + pydantic v2 + `pytest` (`cd backend && uv run pytest -v`). Frontend Vite + React 19 + TypeScript + Zustand + vitest (`cd frontend && npx vitest run`). Build: `cd frontend && npm run build`. Live check: chrome-devtools-mcp against `:5173` (proxy → `:8080`).

**Verification context:** the existing `us-invoice` project (already has 5 reviewed docs + a `metrics/eval_*.json` from prior M7.1 dogfood runs — `ls backend/.workspace/p_4w6rzeuz9dfi/metrics/` should show ≥1 file) is the live target. The "before" screenshot (placeholder rows) is `docs/screenshots/2026-05-10-m7-empty-hero.png`'s right rail — the new "after" screenshot this plan asks for is `docs/screenshots/2026-05-11-m7-2-metrics-panel.png`.

**Out of scope (explicit non-goals):**
- The `FSSpine` `metrics/` tree row (the 2026-05-10 sibling 🟡 Pending entry). The spine tree is a separate UI surface with its own design question ("one file per run vs. rolling history?"); this plan only wires the right-rail summary card. The spine row stays deferred.
- Eval *history* — only the *latest* run is exposed. A future milestone can add `GET …/evals` (list) and a sparkline.
- `per_field` macro precision/recall computation in the backend. The endpoint returns the raw `ScoreResult` (which carries `per_field[].precision/.recall` already); the frontend adapter averages them for the right-rail display. Keeps backend dumb, leaves UI free to pick its summary.

---

## Live verification protocol (chrome-devtools-mcp)

Same protocol as M7.1 (the previous plan, §"Live verification protocol"). Condensed reminders for this plan:

- Assume `:8080` (backend uvicorn `--reload`) and `:5173` (Vite) are already running; the executor starts them if not.
- `navigate_page http://localhost:5173`. If it errors with *"browser is already running for … chrome-profile"*, run `pkill -f "chrome-devtools-mcp/chrome-profile"` and retry.
- `take_snapshot` to get `uid`s. Select the `us-invoice` project from the FS spine.
- **Submitting a slash command:** typing `/eval` opens the slash-command menu; plain `Enter` only selects the menu item. Press **Meta+Enter** (`press_key "Meta+Enter"`) to submit. Do NOT press Escape — that clears the textarea.
- `/eval` is slow (10 – 30 s): `wait_for "eval result"` (the `<EvalCard>` header) with `timeout: 60000`. After the EvalCard renders, the `metrics/` section in the right rail must update in the same render pass.
- `list_console_messages` after each scene — fail if there is any new `error` entry. The `[ContextSurface] metrics … placeholder` log this plan deletes must be **gone** from a fresh page load after T3.
- `take_screenshot` with `filePath` set to the exact path the step names.

---

## Task 1: Backend `GET /lab/projects/{pid}/evals/latest` endpoint

**Files:**
- Modify: `backend/app/api/routes/eval.py` — add a `@router.get` handler next to the existing `post_eval`
- Test: `backend/tests/integration/test_lab_eval.py` — append cases for the new endpoint

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/integration/test_lab_eval.py`:

```python
async def test_get_evals_latest_returns_score(workspace: Path) -> None:
    pid = await create_project(workspace, name="latest")
    await write_schema(
        workspace,
        pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number")],
        reason="test",
        allow_structural=True,
    )
    doc_id = await upload_doc(workspace, pid, b"png", "sample.png")
    atomic_write_json(
        predictions_draft_dir(workspace, pid) / f"{doc_id}.json",
        {"entities": [{"invoice_no": "INV-1"}]},
    )
    await save_reviewed(
        workspace, pid, doc_id,
        entities=[{"invoice_no": "INV-1"}], source=ReviewedSource.MANUAL,
    )

    client = TestClient(app)
    # No eval yet → 404
    r0 = client.get(f"/lab/projects/{pid}/evals/latest")
    assert r0.status_code == 404
    assert r0.json()["detail"] == "eval_not_found"

    # Run /eval once
    assert client.post(f"/lab/projects/{pid}/eval").status_code == 200

    # Latest reflects the run
    r1 = client.get(f"/lab/projects/{pid}/evals/latest")
    assert r1.status_code == 200
    body = r1.json()
    assert body["macro_f1"] == 1.0
    assert body["n_reviewed"] == 1
    assert isinstance(body["per_field"], list) and body["per_field"][0]["field"] == "invoice_no"
    assert isinstance(body["ts"], str) and body["ts"].startswith("20")


async def test_get_evals_latest_picks_lex_last(workspace: Path) -> None:
    """Two eval files on disk → endpoint returns the lex-greatest filename
    (which equals the most-recent ts since filenames are
    `eval_YYYY-MM-DDTHH-MM-SSZ.json`)."""
    pid = await create_project(workspace, name="lex")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="x")],
        reason="test", allow_structural=True,
    )
    md = metrics_dir(workspace, pid)
    md.mkdir(parents=True, exist_ok=True)
    earlier = {"n_docs": 1, "n_reviewed": 1, "macro_f1": 0.50,
               "per_field": [{"field": "x", "tp": 1, "fp": 1, "fn": 1, "support": 2,
                              "precision": 0.50, "recall": 0.50, "f1": 0.50}],
               "errors": [], "ts": "2026-05-10T00-00-00Z", "schema_field_count": 1}
    later = {**earlier, "macro_f1": 0.97, "ts": "2026-05-11T00-00-00Z"}
    later["per_field"] = [{"field": "x", "tp": 1, "fp": 0, "fn": 0, "support": 1,
                           "precision": 1.0, "recall": 0.97, "f1": 0.97}]
    atomic_write_json(md / "eval_2026-05-10T00-00-00Z.json", earlier)
    atomic_write_json(md / "eval_2026-05-11T00-00-00Z.json", later)

    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/evals/latest")
    assert r.status_code == 200
    assert r.json()["macro_f1"] == 0.97
    assert r.json()["ts"] == "2026-05-11T00-00-00Z"


def test_get_evals_latest_400_on_bad_pid() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_INVALIDPATH/evals/latest")
    assert r.status_code == 400


def test_get_evals_latest_404_on_missing_project() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_abcdefghijkl/evals/latest")
    assert r.status_code == 404
    assert r.json()["detail"] == "project_not_found"
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && uv run pytest tests/integration/test_lab_eval.py -v`
Expected: the four new tests fail with 404 / no route, plus pre-existing tests still pass.

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/routes/eval.py`, add the import for `metrics_dir` and the new handler:

```python
import json

from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.schemas.score import ScoreResult
from app.tools.score import run_eval
from app.workspace.paths import metrics_dir, project_json_path, schema_path


router = APIRouter()


@router.post("/lab/projects/{project_id}/eval")
async def post_eval(project_id: str) -> dict:
    safe_project_id(project_id)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, project_id).exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    if not schema_path(settings.workspace_root, project_id).exists():
        raise HTTPException(status_code=404, detail="schema_not_found")
    result = await run_eval(settings.workspace_root, project_id)
    return result.model_dump(mode="json")


@router.get("/lab/projects/{project_id}/evals/latest")
async def get_eval_latest(project_id: str) -> dict:
    """Return the most-recent persisted `metrics/eval_*.json`.

    Filenames are `eval_YYYY-MM-DDTHH-MM-SSZ.json` → lex-sort == time-sort.
    Returns 404 with `eval_not_found` when the metrics dir is empty/missing
    so the frontend can render an "no eval yet" empty state instead of an error.
    """
    safe_project_id(project_id)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, project_id).exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    md = metrics_dir(settings.workspace_root, project_id)
    if not md.exists():
        raise HTTPException(status_code=404, detail="eval_not_found")
    candidates = sorted(md.glob("eval_*.json"))
    if not candidates:
        raise HTTPException(status_code=404, detail="eval_not_found")
    blob = json.loads(candidates[-1].read_text())
    # Round-trip through the model to enforce the contract — if a legacy file
    # is on disk with a stale shape, this raises and the test catches it.
    return ScoreResult(**blob).model_dump(mode="json")
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd backend && uv run pytest tests/integration/test_lab_eval.py -v`
Expected: green (new + existing).

- [ ] **Step 5: Full backend suite**

Run: `cd backend && uv run pytest -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/eval.py backend/tests/integration/test_lab_eval.py
git commit -m "feat(api): GET /lab/projects/:id/evals/latest reads most-recent metrics/eval_*.json"
```

---

## Task 2: Frontend `useEval` store

**Files:**
- Create: `frontend/src/stores/eval.ts`
- Modify: `frontend/src/lib/api.ts` — add `getLatestEval` helper
- Test: `frontend/tests/unit/eval-store.test.ts`

- [ ] **Step 1: Add the API helper**

In `frontend/src/lib/api.ts`, after the existing `listProjectDocs` block:

```ts
export interface FieldScore {
  field: string
  tp: number
  fp: number
  fn: number
  support: number
  precision: number
  recall: number
  f1: number
}

export interface EvalSnapshot {
  n_docs: number
  n_reviewed: number
  macro_f1: number
  per_field: FieldScore[]
  errors: string[]
  ts: string
  schema_field_count: number
}

export async function getLatestEval(projectId: string): Promise<EvalSnapshot | null> {
  const r = await fetch(`/lab/projects/${projectId}/evals/latest`)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getLatestEval ${r.status}`)
  return r.json()
}
```

(Field names match `backend/app/schemas/score.py` exactly — `tp/fp/fn/support/precision/recall/f1` on `FieldScore`; `n_docs/n_reviewed/macro_f1/per_field/errors/ts/schema_field_count` on `ScoreResult`.)

- [ ] **Step 2: Write the failing store tests**

```ts
// frontend/tests/unit/eval-store.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useEval } from '../../src/stores/eval'

const fetchMock = vi.fn()

const SNAPSHOT = {
  n_docs: 6, n_reviewed: 5, macro_f1: 0.971, errors: [],
  ts: '2026-05-11T07-04-00Z', schema_field_count: 7,
  per_field: [
    { field: 'invoice_number', tp: 5, fp: 0, fn: 0, support: 5, precision: 1, recall: 1, f1: 1 },
    { field: 'customer_name', tp: 4, fp: 0, fn: 1, support: 5, precision: 1, recall: 0.8, f1: 0.889 },
  ],
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  useEval.getState().reset()
})
afterEach(() => { vi.unstubAllGlobals() })

describe('useEval', () => {
  it('caches per project_id and skips network on hit', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => SNAPSHOT })
    await useEval.getState().load('p_a')
    await useEval.getState().load('p_a')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(useEval.getState().byProject['p_a']?.macro_f1).toBeCloseTo(0.971)
  })

  it('refresh(pid) bypasses cache and re-fetches', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => SNAPSHOT })
    await useEval.getState().load('p_a')
    await useEval.getState().refresh('p_a')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('stores null when backend returns 404 (no eval yet)', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: 'eval_not_found' }) })
    await useEval.getState().load('p_a')
    expect(useEval.getState().byProject['p_a']).toBeNull()
    // Second load still re-tries (null is "known empty" — but a follow-up
    // refresh after /eval should not be required to set the key first).
    await useEval.getState().load('p_a')
    expect(fetchMock).toHaveBeenCalledTimes(1)  // null counts as cached
  })

  it('invalidate(pid) clears the slice', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => SNAPSHOT })
    await useEval.getState().load('p_a')
    useEval.getState().invalidate('p_a')
    expect(useEval.getState().byProject['p_a']).toBeUndefined()
  })
})
```

- [ ] **Step 3: Run — expect FAIL** (`useEval` not exported)

Run: `cd frontend && npx vitest run tests/unit/eval-store.test.ts`
Expected: FAIL — import error.

- [ ] **Step 4: Implement the store**

```ts
// frontend/src/stores/eval.ts
import { create } from 'zustand'

import { getLatestEval, type EvalSnapshot } from '../lib/api'

interface State {
  // null = fetched, no eval on disk yet; undefined = not fetched yet.
  byProject: Record<string, EvalSnapshot | null>
  loading: Record<string, boolean>
  load: (projectId: string) => Promise<EvalSnapshot | null>
  refresh: (projectId: string) => Promise<EvalSnapshot | null>
  invalidate: (projectId: string) => void
  reset: () => void
}

async function fetchSlice(projectId: string): Promise<EvalSnapshot | null> {
  try {
    return await getLatestEval(projectId)
  } catch {
    return null
  }
}

export const useEval = create<State>((set, get) => ({
  byProject: {},
  loading: {},
  reset: () => set({ byProject: {}, loading: {} }),
  invalidate: (projectId) =>
    set((s) => {
      const next = { ...s.byProject }
      delete next[projectId]
      return { byProject: next }
    }),
  load: async (projectId) => {
    if (projectId in get().byProject) return get().byProject[projectId]
    if (get().loading[projectId]) {
      return new Promise((resolve) => {
        const unsub = useEval.subscribe((s) => {
          if (projectId in s.byProject) {
            unsub()
            resolve(s.byProject[projectId])
          }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    const snap = await fetchSlice(projectId)
    set((s) => ({
      byProject: { ...s.byProject, [projectId]: snap },
      loading: { ...s.loading, [projectId]: false },
    }))
    return snap
  },
  refresh: async (projectId) => {
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    const snap = await fetchSlice(projectId)
    set((s) => ({
      byProject: { ...s.byProject, [projectId]: snap },
      loading: { ...s.loading, [projectId]: false },
    }))
    return snap
  },
}))
```

(The `projectId in byProject` check — not `byProject[pid] != null` — is load-bearing: a 404 sets the slice to `null` and we want that to count as "cached, do not re-fetch on render." The store mirrors `useSchema`'s in-flight dedupe pattern but compares with `in` so `null` is a valid cached value.)

- [ ] **Step 5: Run — expect PASS**

Run: `cd frontend && npx vitest run tests/unit/eval-store.test.ts`
Expected: PASS.

- [ ] **Step 6: Build**

Run: `cd frontend && npm run build`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/stores/eval.ts frontend/tests/unit/eval-store.test.ts
git commit -m "feat(stores): useEval — fetch latest metrics/eval_*.json per project"
```

---

## Task 3: `ContextSurface` reads real metrics; placeholder + log removed

**Files:**
- Modify: `frontend/src/components/Context/ContextSurface.tsx`
- Test: `frontend/tests/unit/ContextSurface.test.tsx` (create — no existing test for this component)

**Display contract** (closes the 2026-05-10 design-decisions open question "What's the canonical metric set?"):
- 4 rows, same labels as the placeholder (keeps the visual rhythm): `precision · recall · f1 · coverage`.
- `precision` = macro precision = mean of `per_field[].precision`.
- `recall` = macro recall = mean of `per_field[].recall`.
- `f1` = `macro_f1` (already pre-computed by the backend).
- `coverage` = `n_reviewed / n_docs` as a percentage (rounded to whole %).
- Tone (`ok | mid | bad`): same thresholds as `EvalCard.toTone` — `≥0.85 ok / ≥0.65 mid / else bad`. Coverage uses the same scale (100% ok, ≥65% mid, else bad).
- Header right hint: `macro 0.97 · 5 reviewed` (replaces the static "latest eval").
- Empty state (no eval yet): one italic ink-4 row "no eval yet — type /eval in the chat", mirroring the schema empty state.

- [ ] **Step 1: Failing test**

```tsx
// frontend/tests/unit/ContextSurface.test.tsx
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import ContextSurface from '../../src/components/Context/ContextSurface'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'
import { useDocs } from '../../src/stores/docs'
import { useEval } from '../../src/stores/eval'

const PID = 'p_aaaaaaaaaaaa'

beforeEach(() => {
  useProjects.setState({
    selectedId: PID,
    projects: [{ project_id: PID, name: 'test', project_type: 'extraction', active_version_id: 'v1' }],
  })
  useSchema.setState({ byProject: { [PID]: [{ name: 'x', type: 'string', description: '' }] }, loading: {} })
  useDocs.setState({ byProject: { [PID]: [] }, loading: false })
  // Stub fetch so the effect's loadEval call resolves immediately.
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
  useEval.getState().reset()
})

describe('ContextSurface metrics section', () => {
  it('renders "no eval yet" when useEval slice is null', async () => {
    useEval.setState({ byProject: { [PID]: null }, loading: {} })
    render(<ContextSurface />)
    expect(await screen.findByText(/no eval yet/i)).toBeInTheDocument()
    expect(screen.queryByText('0.94')).not.toBeInTheDocument()  // placeholder gone
  })

  it('renders macro precision / recall / f1 / coverage from snapshot', () => {
    useEval.setState({
      byProject: {
        [PID]: {
          n_docs: 5, n_reviewed: 5, macro_f1: 0.92, errors: [],
          ts: '2026-05-11T07-04-00Z', schema_field_count: 2,
          per_field: [
            { field: 'a', tp: 5, fp: 0, fn: 0, support: 5, precision: 1.0, recall: 1.0, f1: 1.0 },
            { field: 'b', tp: 4, fp: 1, fn: 1, support: 5, precision: 0.8, recall: 0.8, f1: 0.8 },
          ],
        },
      },
      loading: {},
    })
    render(<ContextSurface />)
    // precision row: (1.0 + 0.8) / 2 = 0.90
    expect(screen.getByText('0.90')).toBeInTheDocument()
    // f1: macro_f1 from backend
    expect(screen.getByText('0.92')).toBeInTheDocument()
    // coverage: 5/5 = 100%
    expect(screen.getByText('100%')).toBeInTheDocument()
    // header hint: "macro 0.92 · 5 reviewed"
    expect(screen.getByText(/macro 0\.92 · 5 reviewed/i)).toBeInTheDocument()
  })

  it('does not log the placeholder-deferred message', () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {})
    useEval.setState({ byProject: { [PID]: null }, loading: {} })
    render(<ContextSurface />)
    expect(logSpy).not.toHaveBeenCalledWith(expect.stringMatching(/placeholder/))
    logSpy.mockRestore()
  })
})
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd frontend && npx vitest run tests/unit/ContextSurface.test.tsx`
Expected: FAIL — placeholder text still renders, log still fires.

- [ ] **Step 3: Rewrite the metrics section**

Replace the whole `ContextSurface.tsx` file (the schema + docs sections are unchanged; only the imports, the placeholder block, the effect, and the metrics section change). The full new file:

```tsx
// frontend/src/components/Context/ContextSurface.tsx
import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { useProjects } from '../../stores/projects'
import { useSchema } from '../../stores/schema'
import { useDocs } from '../../stores/docs'
import { useEval } from '../../stores/eval'
import { useReview } from '../../stores/review'
import { docStatus } from '../../types/review'
import type { DocSummary } from '../../types/review'
import type { EvalSnapshot } from '../../lib/api'

function toPillClass(doc: DocSummary): string {
  const s = docStatus(doc)
  if (s === 'reviewed') return 'rev'
  if (s === 'draft') return 'pen'
  return 'new'
}

function toPillLabel(doc: DocSummary): string {
  const s = docStatus(doc)
  if (s === 'reviewed') return 'reviewed'
  if (s === 'draft') return 'pending'
  return 'new'
}

type MetricTone = 'ok' | 'mid' | 'bad'

function toneFor(v: number): MetricTone {
  if (v >= 0.85) return 'ok'
  if (v >= 0.65) return 'mid'
  return 'bad'
}

interface MetricRow {
  k: string
  v: string
  tone: MetricTone
}

// Visible-for-test export — keeps the derivation pure for unit tests if we
// want to grow them later. (See ContextSurface.test.tsx for the rendered shape.)
export function deriveMetrics(snap: EvalSnapshot): { rows: MetricRow[]; hint: string } {
  const n = snap.per_field.length
  const macroP = n === 0 ? 0 : snap.per_field.reduce((a, f) => a + f.precision, 0) / n
  const macroR = n === 0 ? 0 : snap.per_field.reduce((a, f) => a + f.recall, 0) / n
  const macroF = snap.macro_f1
  const coverage = snap.n_docs === 0 ? 0 : snap.n_reviewed / snap.n_docs
  const rows: MetricRow[] = [
    { k: 'precision', v: macroP.toFixed(2), tone: toneFor(macroP) },
    { k: 'recall',    v: macroR.toFixed(2), tone: toneFor(macroR) },
    { k: 'f1',        v: macroF.toFixed(2), tone: toneFor(macroF) },
    { k: 'coverage',  v: `${Math.round(coverage * 100)}%`, tone: toneFor(coverage) },
  ]
  const hint = `macro ${macroF.toFixed(2)} · ${snap.n_reviewed} reviewed`
  return { rows, hint }
}

const MAX_VISIBLE_DOCS = 9
const MAX_VISIBLE_FIELDS = 7

export default function ContextSurface() {
  const { selectedId, projects } = useProjects()
  const pid = selectedId ?? ''

  const fields = useSchema(useShallow(s => s.byProject[pid] ?? []))
  const loadSchema = useSchema(s => s.load)

  const docs = useDocs(useShallow(s => s.byProject[pid] ?? []))
  const refreshDocs = useDocs(s => s.refresh)

  const evalSnap = useEval(s => (pid ? s.byProject[pid] : undefined))
  const loadEval = useEval(s => s.load)

  const { open: openReview } = useReview()
  const project = projects.find(p => p.project_id === pid) ?? null

  useEffect(() => {
    if (!pid) return
    void loadSchema(pid)
    void refreshDocs(pid)
    void loadEval(pid)
  }, [pid, loadSchema, refreshDocs, loadEval])

  const versionStr = project?.active_version_id
    ? `${project.active_version_id} frozen`
    : 'v0 draft'
  const schemaHint = `${fields.length} fields · ${versionStr}`

  const visibleDocs = docs.slice(0, MAX_VISIBLE_DOCS)
  const docsHint = `${visibleDocs.length} of ${docs.length} shown`

  if (!selectedId) {
    return (
      <div className="ctx">
        <div className="ctx-section">
          <p className="micro" style={{ paddingTop: 24, textAlign: 'center' }}>
            select a project to see context
          </p>
        </div>
      </div>
    )
  }

  // ── metrics derivation ───────────────────────────────────────────
  const metrics = evalSnap ? deriveMetrics(evalSnap) : null
  const metricsHint = metrics?.hint ?? 'latest eval'

  return (
    <div className="ctx">
      {/* ── section 1: schema.json ───────────────────────────────── */}
      <div className="ctx-section">
        <div className="ctx-h">
          <span>schema.json</span>
          <span className="small">{schemaHint}</span>
        </div>
        <div className="ctx-card">
          {fields.length === 0 ? (
            <div className="schemaRow" style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}>
              no schema yet — type /init in the chat
            </div>
          ) : (
            <>
              {fields.slice(0, MAX_VISIBLE_FIELDS).map(f => (
                <div key={f.name} className="schemaRow">
                  <span>{f.name}</span>
                  <span className="typ">{f.type}</span>
                </div>
              ))}
              {fields.length > MAX_VISIBLE_FIELDS && (
                <div className="schemaRow" style={{ color: 'var(--ink-5)', fontStyle: 'italic' }}>
                  + {fields.length - MAX_VISIBLE_FIELDS} more
                </div>
              )}
            </>
          )}
        </div>
        <p className="micro" style={{ marginTop: 8 }}>
          The schema becomes the agent's prompt at publish time. Edit through conversation.
        </p>
      </div>

      {/* ── section 2: docs/ ─────────────────────────────────────── */}
      <div className="ctx-section">
        <div className="ctx-h">
          <span>docs/</span>
          <span className="small">{docsHint}</span>
        </div>
        <div className="ctx-card" style={{ padding: '4px 0', gap: 0 }}>
          {docs.length === 0 ? (
            <div className="doc" style={{ color: 'var(--ink-4)', fontStyle: 'italic', cursor: 'default' }}>
              no docs yet — drop PDFs into the chat
            </div>
          ) : (
            visibleDocs.map(d => (
              <div
                key={d.doc_id}
                className="doc"
                onClick={() => openReview(pid, d.doc_id)}
                role="button"
                tabIndex={0}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') openReview(pid, d.doc_id) }}
              >
                <span className="nm">{d.filename}</span>
                <span className={`stat ${toPillClass(d)}`}>{toPillLabel(d)}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── section 3: metrics/ ──────────────────────────────────── */}
      <div className="ctx-section">
        <div className="ctx-h">
          <span>metrics/</span>
          <span className="small">{metricsHint}</span>
        </div>
        <div className="ctx-card">
          {metrics === null ? (
            <div className="metric" style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}>
              <span className="k">no eval yet — type /eval in the chat</span>
            </div>
          ) : (
            metrics.rows.map(m => (
              <div key={m.k} className="metric">
                <span className="k">{m.k}</span>
                <span className={`v ${m.tone}`}>{m.v}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
```

Key removals: the `PLACEHOLDER_METRICS` const at the top, and the second `useEffect` that logged `'[ContextSurface] metrics section uses placeholder data — useEval not wired yet'`.

- [ ] **Step 4: Run — expect PASS**

Run: `cd frontend && npx vitest run tests/unit/ContextSurface.test.tsx`
Expected: PASS.

- [ ] **Step 5: Build**

Run: `cd frontend && npm run build`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Context/ContextSurface.tsx frontend/tests/unit/ContextSurface.test.tsx
git commit -m "feat(m7.2): ContextSurface metrics/ section reads real useEval data; placeholder + log removed"
```

---

## Task 4: Refresh `useEval` after `/eval` completes (cross-store hook)

**Root cause:** `useChat.handleToolResult` already invalidates `useSchema` on `write_schema` and refreshes `useDocs` on upload/extract/save_reviewed. The new hook is symmetric — when `mcp__emerge_tools__score` completes with `ok: true`, the latest `metrics/eval_*.json` on disk has just been written by `run_eval`. Calling `useEval.refresh(pid)` re-fetches and the `ContextSurface` re-renders in the same SSE turn (the `EvalCard` already renders inline from the chat event; the right rail follows).

**Files:**
- Modify: `frontend/src/stores/chat.ts`
- Test: `frontend/tests/unit/chat-tool-result-invalidation.test.ts`

- [ ] **Step 1: Failing test**

Append to `frontend/tests/unit/chat-tool-result-invalidation.test.ts`:

```ts
import { useEval } from '../../src/stores/eval'

// (add to the existing describe block)
it('refreshes useEval when score completes', () => {
  const refresh = vi.spyOn(useEval.getState(), 'refresh').mockResolvedValue(null)
  useChat.setState({ events: [{
    type: 'tool_call', tool_use_id: 't6', tool_name: 'mcp__emerge_tools__score',
    tool_input: {}, tool_result: null, ok: true,
  }]})
  _testUtils.handleToolResult(
    { tool_use_id: 't6', result_text: '{"macro_f1":0.97,"per_field":[],"n_docs":5,"n_reviewed":5,"errors":[],"ts":"2026-05-11T07-04-00Z","schema_field_count":1}', ok: true },
    'p_a', null,
  )
  expect(refresh).toHaveBeenCalledWith('p_a')
  refresh.mockRestore()
})

it('does not refresh useEval when score fails', () => {
  const refresh = vi.spyOn(useEval.getState(), 'refresh').mockResolvedValue(null)
  useChat.setState({ events: [{
    type: 'tool_call', tool_use_id: 't7', tool_name: 'mcp__emerge_tools__score',
    tool_input: {}, tool_result: null, ok: false,
  }]})
  _testUtils.handleToolResult(
    { tool_use_id: 't7', result_text: 'err', ok: false },
    'p_a', null,
  )
  expect(refresh).not.toHaveBeenCalled()
  refresh.mockRestore()
})
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd frontend && npx vitest run tests/unit/chat-tool-result-invalidation.test.ts`
Expected: FAIL — `refresh` never called.

- [ ] **Step 3: Wire the cross-store hook**

In `frontend/src/stores/chat.ts`, add the import and the new branch inside `handleToolResult`:

```ts
import { useEval } from './eval'
```

In `handleToolResult`, inside the `if (parent?.type === 'tool_call' && d.ok)` block (the same block that already handles `write_schema`, `upload_doc`, etc.), append:

```ts
    if (t === 'mcp__emerge_tools__score') {
      void useEval.getState().refresh(projectId)
    }
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd frontend && npx vitest run tests/unit/chat-tool-result-invalidation.test.ts`
Expected: PASS (new cases + the existing ones).

- [ ] **Step 5: Full frontend vitest suite**

Run: `cd frontend && npx vitest run`
Expected: all green.

- [ ] **Step 6: Build**

Run: `cd frontend && npm run build`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/stores/chat.ts frontend/tests/unit/chat-tool-result-invalidation.test.ts
git commit -m "feat(m7.2): chat score tool_result refreshes useEval (metrics/ rail follows EvalCard)"
```

---

## Task 5: Live verification with chrome-devtools-mcp

The full backend + frontend builds + tests already passed in T1–T4. This task confirms the end-to-end flow against the real `us-invoice` project and produces the screenshots referenced by T6.

- [ ] **Step 1: Verify the backend endpoint with curl**

Run: `curl -sS http://localhost:8080/lab/projects/p_4w6rzeuz9dfi/evals/latest | jq '{macro_f1, n_reviewed, n_docs, ts, per_field_len: (.per_field|length)}'`
Expected: a JSON object with `macro_f1` (e.g. ~0.97), `n_reviewed` (5), `n_docs` (≥5), `ts` (recent), `per_field_len` (≥1). If 404 / `eval_not_found`, run `/eval` on the project first (next step).

(Project id `p_4w6rzeuz9dfi` is `us-invoice` from the M7.1 dogfood — if absent on a clean machine, pick whichever project under `backend/.workspace/` has a `metrics/eval_*.json` file; or pick any project with ≥1 reviewed doc and run `/eval` once via the lab UI to seed.)

- [ ] **Step 2: Live check — empty state then fresh `/eval`**

Via chrome-devtools-mcp:
1. `navigate_page http://localhost:5173`. `take_snapshot` and select `us-invoice` from the FS spine.
2. Reload the page (`navigate_page` to the same URL or use `evaluate_script "location.reload()"`) so `useEval` resets and re-fetches — the right rail's metrics card must now show the **real** numbers (no longer `0.94 / 0.91 / 0.92 / 100%`). Header hint should read like `macro 0.97 · 5 reviewed`. (If the project has no prior eval, the empty state shows "no eval yet — type /eval in the chat".)
3. `list_console_messages` — there must be **no** `[ContextSurface] metrics … placeholder` log. If it's still there, T3 didn't ship cleanly.
4. Submit `/eval` (Meta+Enter), `wait_for "eval result"` (timeout 60000). The `<EvalCard>` renders inline. The right rail's metrics card must update in the **same render** — re-snapshot and confirm the macro F1 in the rail matches `<EvalCard>`'s overall F1.
5. `take_screenshot filePath="docs/screenshots/2026-05-11-m7-2-metrics-panel.png"` — frame the full app so the right-rail metrics card + the eval-card in the conv are both visible.

- [ ] **Step 3: Live check — empty state on a project with no eval**

If you have a project with no `metrics/` dir (or seed one via `lab/projects` POST + `write_schema`, no `/eval` ever), navigate to it and confirm the rail shows the "no eval yet — type /eval in the chat" italic ink-4 row. `take_screenshot filePath="docs/screenshots/2026-05-11-m7-2-metrics-empty.png"`. (Optional — skip if no clean project is handy; the unit test covers this state.)

- [ ] **Step 4: Commit screenshots**

```bash
git add docs/screenshots/2026-05-11-m7-2-metrics-panel.png
# if you captured the empty state too:
git add docs/screenshots/2026-05-11-m7-2-metrics-empty.png 2>/dev/null || true
git commit -m "docs(m7.2): live-verified metrics panel screenshot"
```

---

## Task 6: Wrap-up — design-decisions log + ROADMAP closeout

- [ ] **Step 1: Append a resolution entry to `docs/design-decisions.md`**

Append below the M7.1 resolutions block. Use this skeleton (one ✅ entry that resolves the prior 🟡 Pending one — do **not** edit/delete the original; the file is append-only and the 🟡 entry stays as the historical record):

```markdown
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
- Live check: `docs/screenshots/2026-05-11-m7-2-metrics-panel.png`
```

- [ ] **Step 2: Update `docs/superpowers/plans/ROADMAP.md`**

Two edits in `ROADMAP.md`:

(a) Add a new row in the Status table (after the M7.1 row):

```
| **M7.2** — metrics panel (`/eval` → right-rail `metrics/`) | `2026-05-11-m7-2-metrics-panel.md` | ✅ shipped | <commit-range> |
```

(b) In "Open cross-cutting follow-ups", strike the `metrics tree section / /eval → right-panel metrics` bullet (wrap it in `~~…~~`) and add a one-line closure note pointing at this plan. Leave the `metrics tree section` (FSSpine row) part open — that's separate scope. So the resulting bullet reads something like:

> - ~~**metrics tree section / `/eval` → right-panel metrics**~~ — right-panel half closed by **M7.2** (`2026-05-11-m7-2-metrics-panel.md`, commits `<range>`). The FSSpine `metrics/` tree row is still open — different surface, different design question (one file per run vs. rolling history).

Add a "What each milestone delivers" subsection for M7.2 with a 2-3 sentence summary mirroring the M7.1 block.

- [ ] **Step 3: Commit**

```bash
git add docs/design-decisions.md docs/superpowers/plans/ROADMAP.md
git commit -m "docs(m7.2): decisions log + roadmap closeout"
```

---

## Self-Review

- **Spec coverage:**
  - The 2026-05-10 🟡 Pending `metrics/ ContextSurface section uses placeholder data` entry — closed by T3 (rewrite) + T6 (decisions log resolution).
  - The 2026-05-10 design open question "What's the canonical metric set?" — answered in T3's display contract: precision/recall/f1/coverage, same labels as the placeholder so the visual rhythm is preserved; macro precision/recall derived in the frontend adapter.
  - The 2026-05-10 design open question "Should this stay hidden when no eval has run, or show 'no eval yet'?" — answered: visible empty state matching the schema section's pattern.
  - The ROADMAP "metrics tree section / `/eval` → right-panel metrics" M7.2 candidate bullet — closed for the *right-panel* half (T1 + T2 + T3 + T4); the FSSpine `metrics/` tree row stays open by design and is called out explicitly in the out-of-scope section.
  - The console log "[ContextSurface] metrics … placeholder" — removed in T3 Step 3 (deleted the whole second `useEffect`) and verified gone in T5 Step 2.
- **Placeholder scan:** every code block is concrete. T1's tests reference real fixtures (`create_project`, `write_schema`, `upload_doc`, `save_reviewed`, `atomic_write_json`) that already exist in `backend/tests/integration/test_lab_eval.py`'s imports. T2/T3/T4's tests reference real store/component imports. T5's curl path uses a real workspace project id (`p_4w6rzeuz9dfi`) with a hedge for clean machines.
- **Type consistency:** `EvalSnapshot` (T2) exactly mirrors `ScoreResult` (`backend/app/schemas/score.py`) — same field names. `FieldScore.precision/recall/f1/support/tp/fp/fn/field` match between backend and frontend. `useEval.byProject[pid]` is `EvalSnapshot | null` everywhere (T2 store, T3 selector, T4 test setState). `deriveMetrics` (T3) takes `EvalSnapshot`, returns `{rows: MetricRow[], hint: string}`; `MetricRow` is `{k, v, tone}` — same shape the placeholder used so the `.metric .k / .v` CSS keeps working unchanged. Tone strings `'ok' | 'mid' | 'bad'` match the CSS classes already in `index.css` (`.v.ok / .v.mid / .v.bad`).
