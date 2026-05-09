# M5 — UX Papercut Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land four dogfood-derived UX papercuts deferred from M4 — per-`jobId` `useJob` store, `useSchema` Zustand cache invalidated by `tool_result`, multi-entity score/readiness/FieldEditor, and click-a-field-to-jump-to-page in ReviewMode.

**Architecture:** Frontend-leaning. (1) Refactor `useJob` from a single global store into a `Map<jobId, JobSlice>` and abort the previous SSE on resubscribe. (2) Hoist ReviewMode's one-shot `fetchSchema` into a per-pid `useSchema` store, then invalidate it from `useChat`'s `handleToolResult` whenever `write_schema` / `accept_candidate` lands; same path also drops the manual `refreshProjects/refreshDocs` calls in `ChatPanel.onSubmit`. (3) Backend `score()` and `readiness_check` walk the full `entities` list (zip prediction[i] with reviewed[i] when same length), and `useReview` upgrades from `fields: dict` to `entities: dict[]` with FieldEditor rendering per-entity row groups. (4) Click-to-page reads the existing `_evidence` payload (already round-tripped by backend; no schema change) and calls `useReview.goPage`.

**Tech Stack:** TypeScript / React 19 / Zustand 5 / Vite / Vitest / Playwright (frontend); Python 3 / FastAPI / pydantic v2 / pytest / uv (backend). No new dependencies.

---

## Pre-flight

- Branch from `main` after the M1..M4 merge (commit `0aff9b6`).
- ROADMAP currently lists three of these as "M5 candidate" (multi-entity, useJob, evidence). Task 0 promotes M5 to a real status row.
- Frontend reviewed payload already carries `_evidence` end-to-end; the open follow-up's "round-trip" claim is satisfied by current code (`backend/app/schemas/reviewed.py:25`, `backend/app/tools/reviewed.py:27`, `frontend/src/stores/review.ts:60,85`). Theme 4 is therefore UX-only.

---

### Task 0: Add M5 row to ROADMAP

**Files:**
- Modify: `docs/superpowers/plans/ROADMAP.md`

- [ ] **Step 1: Add status-table row**

In the `## Status` table after the M4 row, append:

```markdown
| **M5** — UX papercut bundle (useJob isolate + schema invalidate + multi-entity + click-to-page) | `2026-05-09-m5-ux-papercut.md` | 🚧 in progress | (TBD) |
```

- [ ] **Step 2: Add M5 narrative under "What each milestone delivers"**

After the `### M4 — polish` block insert:

```markdown
### M5 — UX papercut bundle

**Goal:** absorb four follow-ups deferred from M4 — `useJob` per-`jobId` isolation, ReviewMode schema cache invalidated by chat events, multi-entity `score()` / `readiness` / `FieldEditor`, and click-a-field-to-jump-to-page in ReviewMode.

**Scope:** see `2026-05-09-m5-ux-papercut.md`. No new spec scope; closes follow-ups #1, #2, #3, #8 from "Open cross-cutting follow-ups".
```

- [ ] **Step 3: Commit plan + ROADMAP together**

```bash
git add docs/superpowers/plans/ROADMAP.md docs/superpowers/plans/2026-05-09-m5-ux-papercut.md
git commit -m "docs(plans): open M5 — UX papercut bundle"
```

---

## Theme 1 — `useJob` per-jobId isolation

### Task 1: Failing test for per-jobId state isolation

**Files:**
- Test: `frontend/tests/unit/jobs-store.test.ts` (new)

- [ ] **Step 1: Add the failing test**

```ts
// frontend/tests/unit/jobs-store.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'

import { useJob } from '../../src/stores/jobs'

vi.mock('../../src/lib/sse', () => ({
  streamSSE: async function* () {
    // never yields; resolves on abort
    await new Promise(() => {})
  },
}))

describe('useJob per-jobId isolation', () => {
  beforeEach(() => {
    useJob.getState().reset()
  })

  it('keeps separate slices for two different jobIds', async () => {
    void useJob.getState().subscribe('p_aaaaaaaaaaaa', 'job_a')
    void useJob.getState().subscribe('p_aaaaaaaaaaaa', 'job_b')
    const slice_a = useJob.getState().slice('job_a')
    const slice_b = useJob.getState().slice('job_b')
    expect(slice_a).not.toBe(slice_b)
    expect(slice_a?.jobId).toBe('job_a')
    expect(slice_b?.jobId).toBe('job_b')
  })

  it('aborts the previous SSE when re-subscribing the same jobId', async () => {
    void useJob.getState().subscribe('p_aaaaaaaaaaaa', 'job_a')
    const ctrl1 = useJob.getState().slice('job_a')?._abort
    expect(ctrl1).toBeDefined()
    void useJob.getState().subscribe('p_aaaaaaaaaaaa', 'job_a')
    expect(ctrl1?.signal.aborted).toBe(true)
  })
})
```

- [ ] **Step 2: Run the test — confirm it fails**

```bash
cd frontend && npm test -- jobs-store
```

Expected: `slice is not a function` / `subscribe signature mismatch`.

- [ ] **Step 3: Commit the failing test**

```bash
git add frontend/tests/unit/jobs-store.test.ts
git commit -m "test(jobs): per-jobId isolation + abort-on-resubscribe"
```

---

### Task 2: Refactor `useJob` to per-jobId Map

**Files:**
- Modify: `frontend/src/stores/jobs.ts`

- [ ] **Step 1: Replace store with Map-keyed slices**

Replace the current single-state `useJob` with:

```ts
import { create } from 'zustand'

import { jobEventsUrl, pauseJob, resumeJob, cancelJob, acceptCandidate } from '../lib/api'
import { streamSSE } from '../lib/sse'
import type { JobEvent, JobStatus, TurnEvent } from '../types/job'

export interface JobSlice {
  jobId: string
  projectId: string
  status: JobStatus
  turns: TurnEvent[]
  bestTurn: TurnEvent | null
  endedReason: string | null
  err: string | null
  _abort: AbortController | null
}

interface State {
  byId: Record<string, JobSlice>
  slice: (jobId: string) => JobSlice | null
  subscribe: (projectId: string, jobId: string) => Promise<void>
  pause: (jobId: string) => Promise<void>
  resume: (jobId: string) => Promise<void>
  cancel: (jobId: string) => Promise<void>
  accept: (jobId: string, turn: number) => Promise<void>
  reset: () => void
}

const empty = (jobId: string, projectId: string): JobSlice => ({
  jobId,
  projectId,
  status: 'running',
  turns: [],
  bestTurn: null,
  endedReason: null,
  err: null,
  _abort: null,
})

function patch(set: any, jobId: string, patch: Partial<JobSlice>) {
  set((s: State) => {
    const cur = s.byId[jobId]
    if (!cur) return s
    return { byId: { ...s.byId, [jobId]: { ...cur, ...patch } } }
  })
}

export const useJob = create<State>((set, get) => ({
  byId: {},
  slice: (jobId) => get().byId[jobId] ?? null,
  reset: () => {
    for (const slice of Object.values(get().byId)) slice._abort?.abort()
    set({ byId: {} })
  },
  subscribe: async (projectId, jobId) => {
    // Abort any in-flight SSE for the same jobId before opening a new one.
    const prev = get().byId[jobId]
    prev?._abort?.abort()
    const ctrl = new AbortController()
    set((s) => ({ byId: { ...s.byId, [jobId]: { ...empty(jobId, projectId), _abort: ctrl } } }))
    try {
      for await (const ev of streamSSE(jobEventsUrl(projectId, jobId), { method: 'GET', signal: ctrl.signal })) {
        if (ev.event !== 'job_event') continue
        const data = ev.data as JobEvent
        if (data.type === 'turn') {
          set((s) => {
            const cur = s.byId[jobId]
            if (!cur) return s
            const turns = [...cur.turns, data]
            const best = data.saved && (!cur.bestTurn || data.macro_f1 > cur.bestTurn.macro_f1) ? data : cur.bestTurn
            return { byId: { ...s.byId, [jobId]: { ...cur, turns, bestTurn: best } } }
          })
        } else if (data.type === 'paused') {
          patch(set, jobId, { status: 'paused' })
        } else if (data.type === 'resumed') {
          patch(set, jobId, { status: 'running' })
        } else if (data.type === 'ended') {
          const reason = data.reason ?? null
          const status: JobStatus = reason === 'cancelled' ? 'cancelled' : reason === 'error' ? 'error' : 'done'
          patch(set, jobId, { status, endedReason: reason })
        }
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') return
      patch(set, jobId, { err: String(e), status: 'error' })
    }
  },
  pause: async (jobId) => { await pauseJob(jobId) },
  resume: async (jobId) => { await resumeJob(jobId) },
  cancel: async (jobId) => { await cancelJob(jobId) },
  accept: async (jobId, turn) => {
    const slice = get().byId[jobId]
    if (!slice) return
    await acceptCandidate(slice.projectId, jobId, turn)
  },
}))
```

- [ ] **Step 2: Verify `streamSSE` honors `signal`**

Open `frontend/src/lib/sse.ts`. If the existing signature does not accept `RequestInit['signal']`, extend it now:

```ts
export async function* streamSSE(url: string, init: RequestInit & { signal?: AbortSignal }): AsyncIterable<{ event: string; data: unknown }> {
  const res = await fetch(url, init)
  // ...existing body...
}
```

The existing fetch call in `sse.ts` already accepts a `RequestInit`; passing `{ ...init, signal }` through is sufficient. If the file already forwards `init` verbatim, no change.

- [ ] **Step 3: Run the failing test from Task 1**

```bash
cd frontend && npm test -- jobs-store
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/jobs.ts frontend/src/lib/sse.ts
git commit -m "refactor(jobs): per-jobId state Map with abort-on-resubscribe"
```

---

### Task 3: Wire `JobProgressCard` to per-jobId selector

**Files:**
- Modify: `frontend/src/components/Chat/JobProgressCard.tsx`
- Modify: `frontend/src/components/Chat/MessageList.tsx` (or wherever `JobProgressCard` is mounted)
- Test: `frontend/tests/unit/JobProgressCard.test.tsx`

- [ ] **Step 1: Update `JobProgressCard` props + usage**

The card must take `jobId` as a prop and read its slice via `useJob(s => s.byId[jobId])`. Replace the current `useJob()` global call:

```tsx
interface Props { jobId: string }

export default function JobProgressCard({ jobId }: Props) {
  const slice = useJob((s) => s.byId[jobId])
  const { pause, resume, cancel, accept } = useJob()
  if (!slice) return null
  // ...render slice.turns / slice.status / slice.bestTurn unchanged...
  // Replace bare pause()/resume()/cancel()/accept(turn) with
  //   pause(jobId), resume(jobId), cancel(jobId), accept(jobId, turn)
}
```

- [ ] **Step 2: Update mount site to pass `jobId`**

In `MessageList.tsx` (or `ChatPanel.tsx` — whichever currently renders the card) find the existing `<JobProgressCard />` mount. The job id is already available on the spawning `tool_call` event's parsed result (`start_job` returns `{ job_id }` in `tool_result`). Render one card per discovered `job_id`:

```tsx
const jobIds = events
  .filter((e) => e.type === 'tool_call' && e.tool_name === 'mcp__emerge_tools__start_job')
  .map((e) => {
    if (typeof e.tool_result === 'string') {
      try { return (JSON.parse(e.tool_result) as { job_id?: string }).job_id ?? null } catch { return null }
    }
    return (e.tool_result as { job_id?: string } | null)?.job_id ?? null
  })
  .filter(Boolean) as string[]

return (
  <>
    {/* ...existing render... */}
    {jobIds.map((jid) => <JobProgressCard key={jid} jobId={jid} />)}
  </>
)
```

- [ ] **Step 3: Update existing `JobProgressCard.test.tsx` to pass `jobId` prop and seed `byId`**

Replace any `useJob.setState({ turns: [...] })` with:

```tsx
useJob.setState({
  byId: {
    job_x: {
      jobId: 'job_x',
      projectId: 'p_aaaaaaaaaaaa',
      status: 'running',
      turns: [{ turn: 1, macro_f1: 0.4, saved: true } as TurnEvent],
      bestTurn: null,
      endedReason: null,
      err: null,
      _abort: null,
    },
  },
})
```

- [ ] **Step 4: Run frontend tests**

```bash
cd frontend && npm test
```

Expected: 19 files PASS, 91+ tests PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/JobProgressCard.tsx frontend/src/components/Chat/MessageList.tsx frontend/tests/unit/JobProgressCard.test.tsx
git commit -m "feat(chat): JobProgressCard renders per-jobId, multi-card safe"
```

---

## Theme 2 — `useSchema` cache + tool_result invalidation

### Task 4: Failing test for `useSchema` invalidation

**Files:**
- Test: `frontend/tests/unit/schema-store.test.ts` (new)

- [ ] **Step 1: Write the failing test**

```ts
// frontend/tests/unit/schema-store.test.ts
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'

import { useSchema } from '../../src/stores/schema'

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  useSchema.getState().reset()
})
afterEach(() => { vi.unstubAllGlobals() })

describe('useSchema', () => {
  it('caches per project_id and skips network on hit', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => [{ name: 'x', type: 'string', description: '' }] })
    await useSchema.getState().load('p_a')
    await useSchema.getState().load('p_a')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('invalidate(pid) re-fetches on next load', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => [{ name: 'x', type: 'string', description: '' }] })
    await useSchema.getState().load('p_a')
    useSchema.getState().invalidate('p_a')
    await useSchema.getState().load('p_a')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
```

- [ ] **Step 2: Run — confirm fails (file does not exist)**

```bash
cd frontend && npm test -- schema-store
```

Expected: import error.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/unit/schema-store.test.ts
git commit -m "test(schema): cache + invalidate contract"
```

---

### Task 5: Implement `useSchema` store

**Files:**
- Create: `frontend/src/stores/schema.ts`

- [ ] **Step 1: Implement the store**

```ts
import { create } from 'zustand'

export interface SchemaField {
  name: string
  type: string
  description: string
  enum?: string[] | null
}

interface State {
  byProject: Record<string, SchemaField[]>
  loading: Record<string, boolean>
  load: (projectId: string) => Promise<SchemaField[]>
  invalidate: (projectId: string) => void
  reset: () => void
}

export const useSchema = create<State>((set, get) => ({
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
    const cached = get().byProject[projectId]
    if (cached) return cached
    if (get().loading[projectId]) {
      // dedupe in-flight
      return new Promise((resolve) => {
        const unsub = useSchema.subscribe((s) => {
          if (s.byProject[projectId]) {
            unsub()
            resolve(s.byProject[projectId])
          }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    try {
      const r = await fetch(`/lab/projects/${projectId}/schema`)
      const fields: SchemaField[] = r.ok ? await r.json() : []
      set((s) => ({
        byProject: { ...s.byProject, [projectId]: fields },
        loading: { ...s.loading, [projectId]: false },
      }))
      return fields
    } catch {
      set((s) => ({ loading: { ...s.loading, [projectId]: false } }))
      return []
    }
  },
}))
```

- [ ] **Step 2: Run the failing test**

```bash
cd frontend && npm test -- schema-store
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/schema.ts
git commit -m "feat(schema): per-project schema store with invalidate"
```

---

### Task 6: ReviewMode reads from `useSchema`

**Files:**
- Modify: `frontend/src/components/ReviewMode/ReviewMode.tsx`

- [ ] **Step 1: Replace local `fetchSchema` with the store**

Delete the inline `interface SchemaField`, the inline `fetchSchema` function, and the `useState<SchemaField[]>` + `useEffect` pair. Replace with:

```tsx
import { useEffect } from 'react'
import { ChevronLeft } from 'lucide-react'

import { useReview } from '../../stores/review'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'

import FieldEditor from './FieldEditor'
import PdfViewer from './PdfViewer'

export default function ReviewMode() {
  const { activeProjectId, activeDocId, /* ...rest unchanged... */ } = useReview()
  const { byProject } = useDocs()
  const schema = useSchema((s) => (activeProjectId ? s.byProject[activeProjectId] ?? [] : []))
  const loadSchema = useSchema((s) => s.load)

  useEffect(() => {
    if (!activeProjectId) return
    void loadSchema(activeProjectId)
  }, [activeProjectId, loadSchema])

  // ...rest of render unchanged, passing `schema` to FieldEditor...
}
```

- [ ] **Step 2: Run frontend tests**

```bash
cd frontend && npm test
```

Expected: all suites PASS. (Existing ReviewMode-touching tests use `useReview` directly; this refactor doesn't break them.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ReviewMode/ReviewMode.tsx
git commit -m "refactor(review): ReviewMode reads schema from useSchema store"
```

---

### Task 7: `useChat` invalidates stores on relevant `tool_result`

**Files:**
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/components/Chat/ChatPanel.tsx`
- Test: `frontend/tests/unit/chat-tool-result-invalidation.test.ts` (new)

- [ ] **Step 1: Failing test — invalidation hooks fire on `tool_result`**

```ts
// frontend/tests/unit/chat-tool-result-invalidation.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'

import { _testUtils } from '../../src/stores/chat'
import { useChat } from '../../src/stores/chat'
import { useSchema } from '../../src/stores/schema'
import { useDocs } from '../../src/stores/docs'

beforeEach(() => {
  useChat.getState().reset()
  useSchema.getState().reset()
})

describe('handleToolResult side effects', () => {
  it('invalidates useSchema when write_schema completes', () => {
    useChat.setState({ events: [{
      type: 'tool_call', tool_use_id: 't1', tool_name: 'mcp__emerge_tools__write_schema',
      tool_input: {}, tool_result: null, ok: true,
    }]})
    useSchema.setState({ byProject: { p_a: [{ name: 'x', type: 'string', description: '' }] } })
    _testUtils.handleToolResult({ tool_use_id: 't1', result_text: '{"ok":true}', ok: true }, 'p_a', null)
    expect(useSchema.getState().byProject['p_a']).toBeUndefined()
  })

  it('refreshes useDocs when upload_doc completes', async () => {
    const refresh = vi.spyOn(useDocs.getState(), 'refresh').mockResolvedValue()
    useChat.setState({ events: [{
      type: 'tool_call', tool_use_id: 't2', tool_name: 'mcp__emerge_tools__upload_doc',
      tool_input: {}, tool_result: null, ok: true,
    }]})
    _testUtils.handleToolResult({ tool_use_id: 't2', result_text: '{"doc_id":"d_x"}', ok: true }, 'p_a', null)
    expect(refresh).toHaveBeenCalledWith('p_a')
  })
})
```

- [ ] **Step 2: Run — confirm fails**

```bash
cd frontend && npm test -- chat-tool-result-invalidation
```

Expected: assertions FAIL (no invalidation wired yet).

- [ ] **Step 3: Add invalidation in `handleToolResult`**

In `frontend/src/stores/chat.ts`, after the existing `useChat.setState` that attaches `resultPayload` to the matched `tool_call` event (around line 138), append:

```ts
import { useSchema } from './schema'
import { useDocs } from './docs'
import { useProjects } from './projects'

// ...inside handleToolResult, after the existing setState block...
if (parent?.type === 'tool_call' && d.ok) {
  const t = parent.tool_name
  if (t === 'mcp__emerge_tools__write_schema' || t === 'mcp__emerge_tools__accept_candidate') {
    useSchema.getState().invalidate(projectId)
  }
  if (t === 'mcp__emerge_tools__upload_doc' || t === 'mcp__emerge_tools__save_reviewed') {
    void useDocs.getState().refresh(projectId)
  }
  if (t === 'mcp__emerge_tools__create_project') {
    void useProjects.getState().refresh()
  }
}
```

- [ ] **Step 4: Drop the `ChatPanel.onSubmit` cross-store hack**

In `frontend/src/components/Chat/ChatPanel.tsx`, remove the trailing `await refreshProjects()` and `if (selectedId) await refreshDocs(selectedId)` from the `onSubmit` handler — the chat store now owns this. Drop the now-unused `refresh: refreshProjects` and `{ refresh: refreshDocs }` destructures.

- [ ] **Step 5: Run frontend tests**

```bash
cd frontend && npm test
```

Expected: PASS, including the new invalidation test.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/chat.ts frontend/src/components/Chat/ChatPanel.tsx frontend/tests/unit/chat-tool-result-invalidation.test.ts
git commit -m "feat(chat): tool_result invalidates schema/docs/projects stores"
```

---

## Theme 3 — Multi-entity score / readiness / FieldEditor

### Task 8: Backend `score()` walks all entities

**Files:**
- Modify: `backend/app/tools/score.py:50-92`
- Test: `backend/tests/unit/test_tool_score.py`

- [ ] **Step 1: Failing test — multi-entity grading**

Append to `backend/tests/unit/test_tool_score.py`:

```python
def test_score_grades_all_entities():
    """When a doc has 2 reviewed entities and 2 prediction entities, both rows count."""
    schema = [SchemaField(name="invoice_number", type="string", description="x")]
    predictions = {"d_a": [
        {"invoice_number": "A1"},
        {"invoice_number": "B2"},
    ]}
    reviewed = {"d_a": [
        {"invoice_number": "A1"},   # match
        {"invoice_number": "B-WRONG"},  # miss
    ]}
    result = score(schema, predictions, reviewed)
    by_field = {f.field: f for f in result.per_field}
    assert by_field["invoice_number"].tp == 1
    assert by_field["invoice_number"].fp == 1
    assert by_field["invoice_number"].fn == 1
    assert by_field["invoice_number"].support == 2
```

- [ ] **Step 2: Run — confirm fails**

```bash
cd backend && uv run pytest tests/unit/test_tool_score.py::test_score_grades_all_entities -v
```

Expected: `tp == 0` (only entity[0] is graded).

- [ ] **Step 3: Replace single-entity grading with zip-walk**

In `backend/app/tools/score.py`, replace the `for doc_id, reviewed_entities in reviewed.items():` loop body:

```python
    for doc_id, reviewed_entities in reviewed.items():
        if doc_id not in predictions:
            errors.append(f"doc {doc_id} has reviewed but no prediction")
            continue
        prediction_entities = predictions[doc_id]
        # Multi-entity: pair by index. Mismatched lengths surface as errors
        # the user sees in the readiness checklist (Task 9).
        if len(prediction_entities) != len(reviewed_entities):
            errors.append(
                f"doc {doc_id}: predicted {len(prediction_entities)} entities, "
                f"reviewed {len(reviewed_entities)} — grading the overlap only"
            )
        n_reviewed_graded += 1
        pair_count = min(len(prediction_entities), len(reviewed_entities))
        for i in range(pair_count):
            reviewed_entity = reviewed_entities[i]
            prediction_entity = prediction_entities[i]
            for field in schema:
                reviewed_value = reviewed_entity.get(field.name)
                prediction_value = prediction_entity.get(field.name)
                reviewed_absent = _absent(reviewed_value)
                prediction_absent = _absent(prediction_value)

                if reviewed_absent and prediction_absent:
                    continue

                field_counts = counts[field.name]
                if not reviewed_absent:
                    field_counts["support"] += 1

                if not reviewed_absent and not prediction_absent:
                    if _eq(reviewed_value, prediction_value):
                        field_counts["tp"] += 1
                    else:
                        field_counts["fp"] += 1
                        field_counts["fn"] += 1
                elif reviewed_absent and not prediction_absent:
                    field_counts["fp"] += 1
                elif not reviewed_absent and prediction_absent:
                    field_counts["fn"] += 1
```

- [ ] **Step 4: Run the new test + full score module**

```bash
cd backend && uv run pytest tests/unit/test_tool_score.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run full backend suite (regression check)**

```bash
cd backend && uv run pytest -q
```

Expected: 292 passed (291 + 1 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/score.py backend/tests/unit/test_tool_score.py
git commit -m "feat(score): grade all entities, not just entities[0]"
```

---

### Task 9: Backend `readiness_check` walks all entities

**Files:**
- Modify: `backend/app/tools/publish.py` — locate `readiness_check` (`grep -n 'def readiness_check' backend/app/tools/publish.py`)
- Test: `backend/tests/unit/test_tool_publish_readiness.py`

- [ ] **Step 1: Failing test**

Append to `backend/tests/unit/test_tool_publish_readiness.py`:

```python
def test_readiness_reports_multi_entity_completeness(tmp_path: Path) -> None:
    """When a reviewed doc has 2 entities, readiness counts coverage across both."""
    pid = "p_aaaaaaaaaaaa"
    _seed_project(tmp_path, pid, schema=[
        {"name": "invoice_number", "type": "string", "description": "x"},
    ])
    # one reviewed doc with two entities, the second missing the field
    _write_reviewed(tmp_path, pid, "d_a", entities=[
        {"invoice_number": "A1"},
        {"invoice_number": ""},
    ])
    result = readiness_check(tmp_path, pid)
    # entities-level support: 1 of 2 has the field populated
    assert result["entities_total"] == 2
    assert result["entities_with_field_coverage"] == 1
```

(Use the existing test helpers in that file; if `_seed_project` / `_write_reviewed` don't exist, factor them out from the closest existing test in the same module.)

- [ ] **Step 2: Run — confirm fails**

```bash
cd backend && uv run pytest tests/unit/test_tool_publish_readiness.py::test_readiness_reports_multi_entity_completeness -v
```

Expected: `KeyError: 'entities_total'` or assertion failure.

- [ ] **Step 3: Update `readiness_check` to iterate all entities**

In `backend/app/tools/publish.py` `readiness_check`, locate the loop over reviewed docs. Where it currently reads `entity = reviewed["entities"][0]`, replace with iteration:

```python
    entities_total = 0
    entities_with_field_coverage = 0
    for doc_blob in reviewed_docs:
        for entity in doc_blob.get("entities", []):
            entities_total += 1
            # An entity counts as "field-covered" if it populates at least one
            # required schema field. Adjust to your existing readiness rule.
            if any(not _absent(entity.get(f["name"])) for f in schema):
                entities_with_field_coverage += 1
    result["entities_total"] = entities_total
    result["entities_with_field_coverage"] = entities_with_field_coverage
```

(Keep the existing per-doc readiness fields; just add these two and replace any prior `entities[0]`-only logic that drove them.)

- [ ] **Step 4: Run readiness tests**

```bash
cd backend && uv run pytest tests/unit/test_tool_publish_readiness.py -v
```

Expected: PASS.

- [ ] **Step 5: Full backend suite**

```bash
cd backend && uv run pytest -q
```

Expected: 293 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/publish.py backend/tests/unit/test_tool_publish_readiness.py
git commit -m "feat(readiness): aggregate field coverage across all entities"
```

---

### Task 10: `useReview` upgrades to `entities: dict[]`

**Files:**
- Modify: `frontend/src/stores/review.ts`
- Test: `frontend/tests/unit/review-store.test.ts` (new)

- [ ] **Step 1: Failing test**

```ts
// frontend/tests/unit/review-store.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'

import { useReview } from '../../src/stores/review'

beforeEach(() => useReview.getState().close())

vi.mock('../../src/lib/api', () => ({
  getReviewed: vi.fn().mockResolvedValue({ entities: [{ a: 1 }, { a: 2 }], source: 'manual' }),
  getPrediction: vi.fn(),
  saveReviewed: vi.fn().mockResolvedValue(undefined),
}))

describe('useReview multi-entity', () => {
  it('open() loads all entities from reviewed payload', async () => {
    await useReview.getState().open('p_a', 'd_a')
    expect(useReview.getState().entities).toEqual([{ a: 1 }, { a: 2 }])
  })

  it('setField(idx, name, value) updates the specified entity only', async () => {
    await useReview.getState().open('p_a', 'd_a')
    useReview.getState().setField(1, 'a', 99)
    expect(useReview.getState().entities[0]).toEqual({ a: 1 })
    expect(useReview.getState().entities[1]).toEqual({ a: 99 })
  })

  it('addEntity() / removeEntity(idx) mutate the array', async () => {
    await useReview.getState().open('p_a', 'd_a')
    useReview.getState().addEntity()
    expect(useReview.getState().entities.length).toBe(3)
    useReview.getState().removeEntity(0)
    expect(useReview.getState().entities).toEqual([{ a: 2 }, {}])
  })
})
```

- [ ] **Step 2: Run — confirm fails**

```bash
cd frontend && npm test -- review-store
```

Expected: `entities` is undefined / `setField` signature mismatch.

- [ ] **Step 3: Refactor `review.ts`**

Replace the single `fields: FieldsValue` and `setField(name, value)` with:

```ts
type FieldsValue = Record<string, unknown>

interface State {
  activeProjectId: string | null
  activeDocId: string | null
  page: number
  pageCount: number
  loading: boolean
  saving: boolean
  err: string | null
  entities: FieldsValue[]                       // was: fields: FieldsValue
  evidence: Record<string, number | null>[] | null
  notes: Record<string, string>
  open: (projectId: string, docId: string) => Promise<void>
  close: () => void
  setField: (entityIdx: number, name: string, value: unknown) => void
  setNote: (name: string, note: string) => void
  addEntity: () => void
  removeEntity: (idx: number) => void
  goPage: (page: number) => void
  setPageCount: (n: number) => void
  save: () => Promise<void>
}
```

Update `open` to set `entities: reviewed.entities ?? []` (falling back to `pred?.entities ?? [{}]` so a fresh extraction with one entity still renders one row).

Update `setField`:

```ts
setField: (entityIdx, name, value) => set((s) => {
  const next = s.entities.slice()
  const cur = next[entityIdx] ?? {}
  next[entityIdx] = { ...cur, [name]: value }
  return { entities: next }
}),
addEntity: () => set((s) => ({ entities: [...s.entities, {}] })),
removeEntity: (idx) => set((s) => ({
  entities: s.entities.length > 1 ? s.entities.filter((_, i) => i !== idx) : s.entities,
})),
```

Update `save` to send `entities: get().entities` instead of `entities: [fields]`.

- [ ] **Step 4: Run review-store test**

```bash
cd frontend && npm test -- review-store
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/review.ts frontend/tests/unit/review-store.test.ts
git commit -m "feat(review): store entities array, support add/remove rows"
```

---

### Task 11: `FieldEditor` renders per-entity row groups

**Files:**
- Modify: `frontend/src/components/ReviewMode/FieldEditor.tsx`
- Modify: `frontend/src/components/ReviewMode/ReviewMode.tsx`
- Test: `frontend/tests/unit/FieldEditor.test.tsx`

- [ ] **Step 1: New `FieldEditor` props**

```tsx
interface Props {
  schema: SchemaField[]
  entities: Record<string, unknown>[]    // was: values
  notes?: Record<string, string>
  onChange: (entityIdx: number, name: string, value: unknown) => void
  onSetNote?: (name: string, note: string) => void
  onAddEntity: () => void
  onRemoveEntity: (idx: number) => void
  onSave: () => void
  saving: boolean
}
```

- [ ] **Step 2: Render row-grouped UI**

```tsx
return (
  <div className="flex flex-col h-full">
    <header className="px-4 py-3 border-b border-subtle font-heading text-sm uppercase tracking-wide text-fg-muted flex items-center gap-2">
      Fields
      <span className="text-fg-muted">·</span>
      <span className="text-fg-secondary">{entities.length} {entities.length === 1 ? 'entity' : 'entities'}</span>
      <button
        type="button"
        onClick={onAddEntity}
        className="ml-auto px-2 py-1 text-xs border border-subtle rounded hover:bg-subtle"
        aria-label="add entity"
      >+ entity</button>
    </header>
    <div className="flex-1 overflow-auto px-4 py-3 space-y-6">
      {entities.map((values, entityIdx) => (
        <section key={entityIdx} className="border border-subtle rounded p-3 space-y-3 relative">
          {entities.length > 1 && (
            <header className="flex items-center gap-2">
              <span className="font-mono text-xs text-fg-muted">entity #{entityIdx + 1}</span>
              <button
                type="button"
                onClick={() => onRemoveEntity(entityIdx)}
                aria-label={`remove entity ${entityIdx + 1}`}
                className="ml-auto px-2 py-0.5 text-xs border border-subtle rounded text-accent-danger hover:bg-subtle"
              >−</button>
            </header>
          )}
          {schema.map((f) => {
            // ...existing per-field render, but substitute:
            //   onClick / onChange handlers must call onChange(entityIdx, f.name, ...)
            //   `current` reads `values[f.name]` (note: `values` is now scoped to this entity)
            //   replace `id={`f-${f.name}`}` with `id={`f-${entityIdx}-${f.name}`}`
            //   replace `htmlFor={`f-${f.name}`}` similarly
            // ...
          })}
        </section>
      ))}
    </div>
    <footer className="px-4 py-3 border-t border-subtle">
      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className="px-4 py-2 bg-accent-primary text-canvas font-heading text-sm uppercase tracking-wide rounded hover:opacity-90 disabled:opacity-50"
      >
        {saving ? 'saving…' : 'save reviewed'}
      </button>
    </footer>
  </div>
)
```

- [ ] **Step 3: Update `ReviewMode.tsx` to pass new props**

```tsx
const { activeProjectId, activeDocId, entities, notes, setField, setNote, addEntity, removeEntity, save, close, saving, err } = useReview()
// ...
<FieldEditor
  schema={schema}
  entities={entities}
  notes={notes}
  onChange={setField}
  onSetNote={setNote}
  onAddEntity={addEntity}
  onRemoveEntity={removeEntity}
  onSave={save}
  saving={saving}
/>
```

- [ ] **Step 4: Update `FieldEditor.test.tsx` and `e2e/review-mode.spec.ts`**

In the unit tests, replace the `values={{ ... }}` prop with `entities={[{ ... }]}`. Update each `onChange` mock assertion to expect `(0, name, value)` instead of `(name, value)`. Add one new test:

```tsx
it('renders one row per entity and add/remove buttons', () => {
  render(<FieldEditor schema={[{ name: 'a', type: 'string', description: '' }]}
    entities={[{ a: 'x' }, { a: 'y' }]}
    onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
    onSave={() => {}} saving={false} />)
  expect(screen.getAllByText(/entity #/).length).toBe(2)
  expect(screen.getByLabelText('add entity')).toBeInTheDocument()
  expect(screen.getAllByLabelText(/remove entity/).length).toBe(2)
})
```

- [ ] **Step 5: Run frontend tests**

```bash
cd frontend && npm test
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ReviewMode/FieldEditor.tsx frontend/src/components/ReviewMode/ReviewMode.tsx frontend/tests/unit/FieldEditor.test.tsx frontend/tests/e2e/review-mode.spec.ts
git commit -m "feat(review): FieldEditor renders per-entity row groups"
```

---

### Task 12: Smoke verify multi-entity end-to-end

**Files:**
- Modify: `backend/tests/integration/test_lab_reviewed.py` (or create `test_lab_reviewed_multi.py`)

- [ ] **Step 1: Integration test — POST + GET round-trips multi-entity**

```python
def test_post_get_reviewed_multi_entity(tmp_workspace, client):
    pid, did = _seed_project_with_doc(tmp_workspace, client)
    body = {
        "entities": [
            {"invoice_number": "A1"},
            {"invoice_number": "B2"},
        ],
        "source": "manual",
    }
    r = client.post(f"/lab/projects/{pid}/reviewed/{did}", json=body)
    assert r.status_code == 200
    g = client.get(f"/lab/projects/{pid}/reviewed/{did}")
    assert g.status_code == 200
    assert g.json()["entities"] == body["entities"]
```

- [ ] **Step 2: Run + commit**

```bash
cd backend && uv run pytest tests/integration/test_lab_reviewed.py -v
git add backend/tests/integration/test_lab_reviewed.py
git commit -m "test(reviewed): integration round-trip preserves multi-entity"
```

---

## Theme 4 — Click-a-field-to-jump-to-page

### Task 13: ReviewMode click-to-page wiring

**Files:**
- Modify: `frontend/src/components/ReviewMode/FieldEditor.tsx` — accept new optional `evidenceForEntity?: Record<string, number | null>` prop and `onJumpToPage?: (page: number) => void`
- Modify: `frontend/src/components/ReviewMode/ReviewMode.tsx`
- Test: `frontend/tests/unit/FieldEditor.test.tsx`

- [ ] **Step 1: Failing test — clicking a field with evidence calls onJumpToPage**

```tsx
it('clicking a label with evidence page jumps to that page', async () => {
  const jump = vi.fn()
  render(<FieldEditor schema={[{ name: 'a', type: 'string', description: '' }]}
    entities={[{ a: 'x' }]}
    evidenceForEntity={{ a: 3 }}
    onChange={() => {}} onAddEntity={() => {}} onRemoveEntity={() => {}}
    onJumpToPage={jump}
    onSave={() => {}} saving={false} />)
  await userEvent.click(screen.getByText(/p3/))
  expect(jump).toHaveBeenCalledWith(3)
})
```

- [ ] **Step 2: Run — confirm fails**

```bash
cd frontend && npm test -- FieldEditor
```

Expected: no `p3` text rendered.

- [ ] **Step 3: Render evidence badge + click handler in FieldEditor**

Inside the per-field block, after `labelEl`, render:

```tsx
{evidenceForEntity?.[f.name] != null && (
  <button
    type="button"
    onClick={() => onJumpToPage?.(evidenceForEntity[f.name] as number)}
    className="ml-2 inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono border border-subtle rounded text-fg-muted hover:bg-subtle"
    aria-label={`jump to page ${evidenceForEntity[f.name]}`}
  >
    p{evidenceForEntity[f.name]}
  </button>
)}
```

Note: `FieldEditor` now takes one entity's worth of evidence per `<section>` it renders. In the row-grouped render from Task 11, pass `evidenceForEntity={evidence?.[entityIdx] ?? undefined}`.

- [ ] **Step 4: Wire `ReviewMode` to pass `evidence` and `onJumpToPage`**

```tsx
const { entities, evidence, goPage /* ... */ } = useReview()
// ...
<FieldEditor
  // ...existing props...
  evidence={evidence}                  // pass full array; FieldEditor slices per row
  onJumpToPage={goPage}
/>
```

(Adjust the `FieldEditor` `Props` type from Task 11 to accept `evidence?: (Record<string, number | null> | undefined)[] | null` and slice it per entity in the map.)

- [ ] **Step 5: Run frontend tests**

```bash
cd frontend && npm test
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ReviewMode/FieldEditor.tsx frontend/src/components/ReviewMode/ReviewMode.tsx frontend/tests/unit/FieldEditor.test.tsx
git commit -m "feat(review): click field evidence badge to jump pages"
```

---

### Task 14: Playwright e2e — click-to-page

**Files:**
- Modify: `frontend/tests/e2e/review-mode.spec.ts`

- [ ] **Step 1: Add e2e**

```ts
test('field with _evidence shows pX badge and jumps page on click', async ({ page }) => {
  // assumes seed loads a doc with _evidence: [{ invoice_number: 2 }]
  await page.goto('/')
  await page.getByRole('button', { name: /us-invoice/i }).click()
  await page.getByRole('button', { name: /Boeing Distribution.*Invoice.pdf/i }).click()
  await expect(page.getByLabel('jump to page 2')).toBeVisible()
  await page.getByLabel('jump to page 2').click()
  await expect(page.getByText('2 / 2')).toBeVisible()  // page indicator switched
})
```

- [ ] **Step 2: Run e2e**

```bash
cd frontend && npm run e2e -- --project=chromium tests/e2e/review-mode.spec.ts
```

Expected: PASS.

If the seeded doc doesn't already have `_evidence`, generate it once in a helper (`tests/e2e_seed.py` exposes `seed_reviewed`, mirror it client-side) — but only if the existing seeded fixture lacks evidence. Run `curl http://127.0.0.1:8000/lab/projects/<pid>/reviewed/<did>` first to check.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/review-mode.spec.ts
git commit -m "test(review): e2e click evidence badge jumps page"
```

---

## Wrap-up

### Task 15: Final acceptance sweep

**Files:** none new.

- [ ] **Step 1: Both suites green**

```bash
cd backend && uv run pytest -q
cd frontend && npm test
cd frontend && npm run e2e
```

Expected: backend PASS, frontend unit PASS, e2e PASS.

- [ ] **Step 2: Manual chrome-devtools smoke**

Start backend + frontend; open `http://127.0.0.1:5173`; for an existing project:
1. Toggle theme — confirm dark/light still works.
2. `/improve` (if API keys configured) — confirm two consecutive runs each render their own JobProgressCard with separate turn lists.
3. Open a reviewed doc — confirm fields show `pN` evidence badges where `_evidence` is present, clicking jumps the page.
4. Run `/improve` then accept; without leaving the page, open ReviewMode — fields reflect the new schema (no manual refresh needed).
5. For a doc with two reviewed entities, ReviewMode shows two stacked `entity #N` row groups; saving round-trips both rows.

- [ ] **Step 3: Update ROADMAP**

Flip M5 row to `✅ shipped` and append the commit range. Move the four addressed bullets out of "Open cross-cutting follow-ups" or strike them through with a "(M5)" tag.

- [ ] **Step 4: Final commit**

```bash
git add docs/superpowers/plans/ROADMAP.md
git commit -m "docs(roadmap): mark M5 shipped + close addressed follow-ups"
```

---

## Out of scope for M5

These remain "Open cross-cutting follow-ups" after M5 ships:
- Plaintext API key chat-jsonl redaction (security, single-user lab risk-accepted)
- `/v1` audit log
- Per-tool retry endpoint `/lab/chat/retry-tool`
- Export bundle non-ASCII filename
- `_keys.json` workspace-wide flock

These are ROADMAP-tracked. None block M5; pick them up post-M5 in priority order (redaction first if the hosted target moves up).
