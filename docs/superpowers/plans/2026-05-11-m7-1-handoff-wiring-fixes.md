# M7.1 — Design-Handoff Wiring & Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended, per user memory) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps found while verifying the M7 scenes on 2026-05-11: structured result cards (`EvalCard`, `PublishStage` checklist) don't render because their adapters don't match the real tool output; the publish panel labels a raw `project_id`; the key-reveal card has stray Chinese labels; the improve job card under-communicates; and the `/publish` agent hits a `Skill` tool error.

**Architecture:** Mostly surgical fixes — one backend serialization fix (`t_score` must emit JSON, not a Python `repr`), three frontend adapter/component fixes, one agent-prompt dedup, and one diagnostic task for the `Skill` error. No new components, no new endpoints, no store-shape changes. Live-verify each fix against the `us-invoice` project (already has 5 reviewed docs + frozen `v4`) via **chrome-devtools-mcp** — see the "Live verification protocol" section below.

**Tech Stack:** Backend FastAPI + `claude_agent_sdk` `@tool`; frontend Vite + React 19 + TypeScript + Zustand. Backend tests `cd backend && uv run pytest -v`. Frontend build `cd frontend && npm run build`; playwright `cd frontend && npx playwright test`.

**Verification context:** the verification screenshots are in `docs/screenshots/2026-05-10-m7-{eval-card,publish-check,publish-key,improve,improve-banner,empty-hero}.png` and the design-decisions log entry from 2026-05-11 has the full findings. The handoff source of truth is `docs/design/emerge-api/project/{app.jsx,review.jsx,index.html}`; read `docs/design-decisions.md` before changing any UI and append after.

**Out of scope (deliberate-looking deviations — leave as-is unless a future handoff says otherwise):**
- `PublishStage` renders inline in the conversation (`.pub-stage.inline`, `position:relative`) instead of the full-bleed `position:absolute; inset:0` overlay the M7 plan described. Keeping conversation context visible is arguably better; not changing it here.
- `mint key →` injects a chat message (`"yes, mint the key now"`) and lets the agent run `issue_api_key`, rather than calling `useApiKey.mintAndReveal()` directly. Agent-native; not changing it here.
- `new project…` in the FS spine calls `useProjects.getState().select(null)` to show the empty hero (where `/init` or a doc-drop makes the agent call `create_project`). That's the intended flow, not a no-op.

---

## Live verification protocol (chrome-devtools-mcp)

Every task below has automated gates (`cd backend && uv run pytest -v`, `cd frontend && npm run build`, `npx playwright test` where noted) — **keep those, they're CI**. On top of that, the "live check" steps must be done with **chrome-devtools-mcp** (not "run the dev server and eyeball it"). It's more reliable for this app and produces the exact screenshots the steps ask for. A dispatched subagent has the MCP tools available.

Assume the backend (`:8080`) and Vite (`:5173`) dev servers are already running (the executor starts them if not: `cd backend && uv run uvicorn app.main:app --reload --port 8080 --host 127.0.0.1` and `cd frontend && npm run dev`). Per-scene loop:

1. `navigate_page` → `http://localhost:5173` (first call auto-launches the browser). If it errors with *"browser is already running for … chrome-profile"* (a stale browser from a prior session holds the profile lock), run `pkill -f "chrome-devtools-mcp/chrome-profile"` and retry — it spawns a fresh one.
2. `take_snapshot` to get element `uid`s; `click` / `fill` by `uid`. After a project is selected, the topbar shows `~/projects/<name>/ · v<n> · …`.
3. **Submitting a slash command is non-obvious:** typing `/eval` opens the slash-command menu, and plain **Enter selects the menu item** (inserts `/eval ` into the textarea) — it does *not* submit. Press **Meta+Enter** (`press_key "Meta+Enter"`) to submit a slash command. Do **not** press Escape — that *clears* the textarea.
4. Agent-driven commands (`/eval`, `/publish`, `/improve`) are slow (10 s – 3 min): use `wait_for` on a specific result string with a generous `timeout` (e.g. 180000 ms), never a fixed `sleep`. Useful anchors: `"eval result"` (EvalCard header), `"Ready to mint a key"` / `"Your API is live"` (PublishStage), `"running · turn"` (ImproveBanner). Be aware `wait_for` matches *any* occurrence — `"DONE"` will false-positive on a tool pill; pick distinctive text.
5. After each scene, `list_console_messages` — fail the check if there's any new `error` (the pre-existing `404` for a missing static asset and the `[ContextSurface] metrics … placeholder` `log` are expected baseline noise).
6. `take_screenshot` with `filePath` set to the exact path the step names.
7. **Before screenshotting the publish *key* stage:** the one-time plaintext key is in the DOM and the repo's hard rule forbids persisting secrets — first `evaluate_script` to replace it: find the text node matching `/^ek_[A-Za-z0-9]{20,}$/` inside `.pub-stage` and overwrite its `textContent` with `ek_••••••••••••••••••••••••••••••`, *then* `take_screenshot`. (Minting a key during a live check creates a real, live key — note it in the task's commit message / hand-off so the user can revoke it.)
8. Long-running jobs (`/improve`): when the check is done, cancel the job via the `JobProgressCard` `cancel` button (`take_snapshot` → `click` its `uid`) so you don't leave a runaway autoresearch loop.

The 2026-05-11 verification screenshots (`docs/screenshots/2026-05-10-m7-*.png`) are the visual "before"; the new ones this plan asks for are the "after".

---

## Task 1: Fix `t_score` to emit valid JSON (so `EvalCard` renders)

**Root cause:** `backend/app/tools/__init__.py` `t_score` returns `{"content": [{"type": "text", "text": str(result.model_dump(mode='json'))}]}`. `str(dict)` is a Python `repr` (single quotes, `True`/`None`), not JSON. The frontend stores the tool result as that raw string and `adaptScoreResult` does `JSON.parse(raw)` → throws → returns `null` → `EvalCardAdapter` falls back to a plain collapsed `ToolCall`, and the agent fills the gap with its own markdown table. `t_readiness_check` two functions below already does it right (`_json.dumps(out)`).

**Files:**
- Modify: `backend/app/tools/__init__.py:191-193` (`t_score`)
- Modify: `backend/app/tools/__init__.py:184` (the sibling tool a few lines up — `return {"content": [{"type": "text", "text": str(payload)}]}` — same `str()`-instead-of-`json.dumps()` bug; fix it the same way **only if** `payload` is a dict/list. If `payload` is already a plain string, leave it.)
- Test: `backend/tests/test_tools_score.py` (create if absent; otherwise add to the existing score-tool test module — grep `tests/` for `t_score` / `run_eval` first)

- [ ] **Step 1: Confirm the bug & the current shape**

Run: `cd backend && uv run python -c "
import asyncio, json
from app.tools.score import run_eval
from app.workspace.paths import workspace_root
# adjust workspace import if the helper differs — grep app/workspace/paths.py for the root accessor
import app.config as cfg
ws = cfg.WORKSPACE_ROOT if hasattr(cfg,'WORKSPACE_ROOT') else None
print('inspect ScoreResult fields:')
from app.schemas.score import ScoreResult, FieldScore
print(ScoreResult.model_fields.keys())
print(FieldScore.model_fields.keys())
"`
Expected: `ScoreResult` has `n_docs, n_reviewed, macro_f1, per_field, errors, ts, schema_field_count`; `FieldScore` has `field, tp, fp, fn, support, precision, recall, f1`. (If field names differ, the frontend adapter in Task 2 Step 3b — `adaptScoreResult` — must match whatever is real; note them.)

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_tools_score.py  (or append to the existing module)
import json
from app.tools import build_emerge_tools  # adjust to the actual factory name — grep app/tools/__init__.py for the exported builder

def test_score_tool_returns_json_text(tmp_workspace_with_reviewed_project):
    # tmp_workspace_with_reviewed_project: a fixture that creates a project with
    # schema + ≥3 reviewed docs + draft predictions. Reuse an existing fixture if one
    # exists (grep conftest.py); otherwise build the minimal one inline.
    pid = tmp_workspace_with_reviewed_project.project_id
    tools = build_emerge_tools(tmp_workspace_with_reviewed_project.workspace)
    t_score = next(t for t in tools if getattr(t, 'name', None) == 'score' or t.__name__ == 't_score')
    out = await_or_run(t_score({"project_id": pid}))  # if the tool is async, await it
    text = out["content"][0]["text"]
    parsed = json.loads(text)            # must NOT raise
    assert isinstance(parsed["macro_f1"], (int, float))
    assert isinstance(parsed["per_field"], list)
    assert {"field", "precision", "recall", "f1", "support"} <= set(parsed["per_field"][0].keys())
```

- [ ] **Step 3: Run it — expect FAIL**

Run: `cd backend && uv run pytest tests/test_tools_score.py -v`
Expected: FAIL — `json.loads` raises `JSONDecodeError` on the Python-repr string.

- [ ] **Step 4: Fix `t_score`**

In `backend/app/tools/__init__.py`, `t_score`:

```python
    async def t_score(args: dict[str, Any]) -> dict[str, Any]:
        result = await score_mod.run_eval(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": _json.dumps(result.model_dump(mode="json"))}]}
```

(`_json` is already imported at the top of the file — it's used by `t_readiness_check`. If the alias is different, use whatever that file already imports `json` as.)

Also inspect line ~184 (`return {"content": [{"type": "text", "text": str(payload)}]}`): if `payload` there is a dict/list, change to `_json.dumps(payload)`. If it's already a string, leave it. Note which tool that is in the commit message.

- [ ] **Step 5: Run the test — expect PASS**

Run: `cd backend && uv run pytest tests/test_tools_score.py -v`
Expected: PASS.

- [ ] **Step 6: Full backend suite**

Run: `cd backend && uv run pytest -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/tools/__init__.py backend/tests/test_tools_score.py
git commit -m "fix(tools): score tool emits json.dumps not python repr (unblocks EvalCard render)"
```

---

## Task 2: Make `EvalCard` & `PublishStage` checklist adapters robust to string input + readiness label humanizer

**Root cause (eval):** even with Task 1, `adaptScoreResult` only reads `scored_at` (the backend field is `ts`) so the timestamp shows "just now" — minor. **Root cause (readiness):** `t_readiness_check` already emits valid JSON, but the frontend stores `tool_result` as the *raw string* (see `frontend/src/stores/chat.ts:100` — `let resultPayload: unknown = d.result_text`, only transformed for `issue_api_key`), and `adaptReadiness` does `if (!result || typeof result !== 'object') return null` — so a JSON *string* yields `null` → `PublishStage` shows the "no checks required" placeholder. Also the backend readiness checks carry `key` (`schema_non_empty`) but no human `label`, so even when parsed the rows read as snake_case.

**Files:**
- Modify: `frontend/src/components/Chat/EvalCard.tsx` — `parseScoreResult` (already JSON.parses strings — good) + `adaptScoreResult` (read `ts` as the timestamp fallback)
- Modify: `frontend/src/components/Publish/PublishStage.tsx` — `adaptReadiness` (JSON.parse string input; add a `key`→`label` humanizer)
- Test: `frontend/src/components/Publish/PublishStage.test.tsx` and `frontend/src/components/Chat/EvalCard.test.tsx` (create if absent — grep `frontend/src` for existing `*.test.tsx` to match the test runner setup, likely vitest)

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/components/Publish/PublishStage.test.tsx
import { describe, it, expect } from 'vitest'
import { adaptReadiness } from './PublishStage'

const READINESS_JSON = JSON.stringify({
  checks: [
    { key: 'schema_non_empty', status: 'pass', detail: '7 fields' },
    { key: 'reviewed_and_f1', status: 'pass', detail: 'macro_f1=0.970 (threshold 0.7); n_reviewed=5' },
    { key: 'contract_diff_compat', status: 'fail', detail: 'breaking changes vs v4: removed=[currency]' },
  ],
  soft_warnings: [],
  hard_pass: false,
  macro_f1: 0.97,
  n_reviewed: 5,
})

describe('adaptReadiness', () => {
  it('parses a JSON string and humanizes keys', () => {
    const out = adaptReadiness(READINESS_JSON)
    expect(out).not.toBeNull()
    expect(out!).toHaveLength(3)
    expect(out![0]).toMatchObject({ key: 'schema_non_empty', label: 'Schema non-empty', ok: true, detail: '7 fields' })
    expect(out![2]).toMatchObject({ key: 'contract_diff_compat', label: 'Contract diff compat', ok: false })
  })
  it('also accepts an already-parsed object', () => {
    expect(adaptReadiness(JSON.parse(READINESS_JSON))).toHaveLength(3)
  })
  it('returns null for garbage', () => {
    expect(adaptReadiness('not json')).toBeNull()
    expect(adaptReadiness(42)).toBeNull()
  })
})
```

```tsx
// frontend/src/components/Chat/EvalCard.test.tsx
import { describe, it, expect } from 'vitest'
import { adaptScoreResult } from './EvalCard'

const SCORE_JSON = JSON.stringify({
  n_docs: 6, n_reviewed: 5, macro_f1: 0.971, errors: [], ts: '2026-05-11T07-04-00Z', schema_field_count: 7,
  per_field: [
    { field: 'invoice_number', tp: 5, fp: 0, fn: 0, support: 5, precision: 1, recall: 1, f1: 1 },
    { field: 'customer_name', tp: 4, fp: 0, fn: 1, support: 5, precision: 1, recall: 0.8, f1: 0.889 },
  ],
})

describe('adaptScoreResult', () => {
  it('parses the score JSON string from the tool result', () => {
    const out = adaptScoreResult(SCORE_JSON)
    expect(out).not.toBeNull()
    expect(out!.overall).toBeCloseTo(0.971)
    expect(out!.rows).toHaveLength(2)
    expect(out!.rows[1]).toMatchObject({ f: 'customer_name', p: 1, r: 0.8, f1: 0.889 })
    expect(out!.scoredAt).toBe('2026-05-11T07-04-00Z')   // reads `ts`, not just `scored_at`
  })
})
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd frontend && npx vitest run src/components/Publish/PublishStage.test.tsx src/components/Chat/EvalCard.test.tsx`
Expected: FAIL — `adaptReadiness('json string')` returns `null`; `adaptScoreResult(...).scoredAt` is `'just now'`.

- [ ] **Step 3a: Fix `adaptReadiness`** in `frontend/src/components/Publish/PublishStage.tsx`

```ts
const READINESS_LABELS: Record<string, string> = {
  schema_non_empty: 'Schema non-empty',
  reviewed_and_f1: 'Reviewed & F1',
  reviewed_fields_in_schema: 'Reviewed fields in schema',
  no_running_jobs: 'No running jobs',
  contract_diff_compat: 'Contract diff compat',
}

function humanizeKey(key: string): string {
  return READINESS_LABELS[key]
    ?? key.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())
}

export function adaptReadiness(result: unknown): CheckItem[] | null {
  let obj: unknown = result
  if (typeof result === 'string') {
    try { obj = JSON.parse(result) } catch { return null }
  }
  if (!obj || typeof obj !== 'object') return null
  const checks = (obj as Record<string, unknown>).checks
  if (!Array.isArray(checks)) return null
  return checks.map((c: Record<string, unknown>) => ({
    key: String(c.key ?? c.label ?? '?'),
    label: c.label != null ? String(c.label) : humanizeKey(String(c.key ?? '?')),
    ok: c.status === 'pass',
    detail: c.detail != null ? String(c.detail) : undefined,
  }))
}
```

- [ ] **Step 3b: Fix `adaptScoreResult`** in `frontend/src/components/Chat/EvalCard.tsx`

In the `ScoreResult` interface add `ts?: string`. In `adaptScoreResult`, change the `scoredAt` line:

```ts
  const scoredAt =
    (typeof sr.scored_at === 'string' && sr.scored_at) ||
    (typeof sr.ts === 'string' && sr.ts) ||
    'just now'
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd frontend && npx vitest run src/components/Publish/PublishStage.test.tsx src/components/Chat/EvalCard.test.tsx`
Expected: PASS.

- [ ] **Step 5: Build**

Run: `cd frontend && npm run build`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Publish/PublishStage.tsx frontend/src/components/Chat/EvalCard.tsx frontend/src/components/Publish/PublishStage.test.tsx frontend/src/components/Chat/EvalCard.test.tsx
git commit -m "fix(m7): readiness/score adapters parse string tool_result; humanize readiness labels"
```

---

## Task 3: `PublishStage` eyebrow shows the project *name*, not the raw `project_id`

**Root cause:** `frontend/src/components/Chat/MessageList.tsx` — `PublishStageCheckAdapter` passes `projectName={String(projectId)}` where `projectId = event.tool_input?.project_id` (e.g. `p_4w6rzeuz9dfi`, and the CSS upper-cases it to `P_4W6RZEUZ9DFI`). `PublishStageKeyAdapter` passes `projectName={current.project_id}`. Design wants `READINESS · invoices/` / `KEY MINTED · invoices/v1` — i.e. the project's display name.

**Files:**
- Modify: `frontend/src/components/Chat/MessageList.tsx` — `PublishStageCheckAdapter`, `PublishStageKeyAdapter`
- Test: extend `frontend/src/components/Chat/MessageList.test.tsx` if it exists (grep first); otherwise a small render test for the two adapters, or skip the unit test and rely on the live check in Step 4.

- [ ] **Step 1: Add a helper that resolves id → name**

In `MessageList.tsx`, near the top, after the existing imports:

```ts
function useProjectName(projectId: string): string {
  const projects = useProjects(s => s.projects)
  return projects.find(p => p.project_id === projectId)?.name ?? projectId
}
```

(`useProjects` is already imported in this file. `Project.name` exists — see `frontend/src/lib/api.ts` `Project` interface.)

- [ ] **Step 2: Use it in `PublishStageCheckAdapter`**

Replace the `projectId` lookup + `projectName` prop:

```tsx
function PublishStageCheckAdapter({ event }: { event: ToolCallEvent }) {
  const checklist = adaptReadiness(event.tool_result) ?? []
  const projectId = typeof (event.tool_input as Record<string, unknown>)?.project_id === 'string'
    ? (event.tool_input as Record<string, unknown>).project_id as string
    : 'project'
  const projectName = useProjectName(projectId)
  const send = useChat(s => s.send)
  const selectedId = useProjects(s => s.selectedId)

  const handleAdvance = () => { void send(selectedId ?? projectId, 'yes, mint the key now') }
  const handleClose = () => { /* inline card: chat history keeps the record */ }

  if (event.tool_result === undefined || event.tool_result === null) {
    return (
      <div className="border-l-2 border-ochre bg-paper px-3 py-1.5 font-mono text-sm flex items-center gap-2">
        <span className="text-ink-4">running readiness check...</span>
      </div>
    )
  }
  return (
    <PublishStage stage="check" projectName={projectName} checklist={checklist}
      onAdvance={handleAdvance} onClose={handleClose} />
  )
}
```

- [ ] **Step 3: Use it in `PublishStageKeyAdapter`**

In the `current && current.project_id === projectId` branch, change `projectName={current.project_id}` → `projectName={useProjectName(current.project_id)}`. (The redacted-trail branch below it doesn't render an eyebrow, so leave it.)

- [ ] **Step 4: Live check (chrome-devtools-mcp — see Live verification protocol)**

Navigate, select the `us-invoice` project, submit `/publish` (Meta+Enter), `wait_for "Ready to mint a key"`, `take_snapshot`: the check-stage eyebrow must read `READINESS · us-invoice` (not `READINESS · P_4W6RZEUZ9DFI`). `click` `mint key →`, `wait_for "Your API is live"`, snapshot: the key-stage eyebrow must read `KEY MINTED · us-invoice/v…`. Redact the plaintext key (protocol step 7), then `take_screenshot` → `docs/screenshots/2026-05-11-m7-1-publish-eyebrow.png`. `list_console_messages` → no new errors. (You'll mint a real key here — note it in the commit message so the user can revoke it.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/MessageList.tsx docs/screenshots/2026-05-11-m7-1-publish-eyebrow.png
git commit -m "fix(m7): publish-stage eyebrow shows project name not project_id"
```

---

## Task 4: De-Chinese the key-reveal card (`PublishStage` key stage)

**Root cause:** `frontend/src/components/Publish/PublishStage.tsx` — `CopyButton` has `title={copied ? '已复制' : '复制'}`; `KeyStage`'s close button has `aria-label="我已保存 - 关闭"`. Everything else in the app is English (the project is light-only English UI for now). Mixed CN/EN reads as unfinished.

**Files:**
- Modify: `frontend/src/components/Publish/PublishStage.tsx`

- [ ] **Step 1: Fix `CopyButton`**

```tsx
    <button
      type="button"
      aria-label="copy api key"
      title={copied ? 'Copied' : 'Copy'}
      onClick={handleCopy}
      className="pub-key-copy-btn"
    >
```

- [ ] **Step 2: Fix the close button in `KeyStage`**

The visible text already says `I've saved this key — close`; the `aria-label` just needs to stop being Chinese. Either drop the `aria-label` (the text content is a fine accessible name) or set it to match:

```tsx
        <button
          type="button"
          onClick={onClose}
          className="pub-btn-primary"
        >
          I've saved this key — close
        </button>
```

- [ ] **Step 3: Grep for any other stray CJK in components**

Run: `cd frontend/src && grep -rn '[\x{4e00}-\x{9fff}]' components/ || echo "none"`
(macOS `grep` may not support `\x{}` — alternatively: `grep -rnP '[\x{4e00}-\x{9fff}]' components/` or `rg '\p{Han}' frontend/src/components`.)
Expected after the fix: only comments / design-decisions references, no user-facing strings.

- [ ] **Step 4: Build + live check (chrome-devtools-mcp)**

`cd frontend && npm run build` (green). Then via chrome-devtools-mcp reach the key stage (`/publish` → `mint key →` → `wait_for "Your API is live"`), `take_snapshot`, and confirm the copy button's accessible name/title is English (`copy api key` / `Copy`) and the close button's `aria-label` is no longer Chinese. Redact the plaintext key, `take_screenshot` → `docs/screenshots/2026-05-11-m7-1-key-card-en.png`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Publish/PublishStage.tsx docs/screenshots/2026-05-11-m7-1-key-card-en.png
git commit -m "fix(m7): english-only labels in key-reveal card"
```

---

## Task 5: `JobProgressCard` — show baseline alongside best F1, and allow accept after cancel

**Root cause:** `frontend/src/components/Chat/JobProgressCard.tsx` renders `turn N · best f1 X (turn M)` with zero baseline context (the autoresearch baseline is `turns[0].macro_f1`; a user can't tell whether `best f1 0.83` is a win or a wash), and the "accept turn N" button only renders when `status === 'done'` — if the user cancels a run that already produced a good `bestTurn`, there's no way to keep it.

**Files:**
- Modify: `frontend/src/components/Chat/JobProgressCard.tsx`
- Test: `frontend/src/components/Chat/JobProgressCard.test.tsx` (create if absent)

- [ ] **Step 1: Failing test**

```tsx
// frontend/src/components/Chat/JobProgressCard.test.tsx
import { describe, it, expect } from 'vitest'
import { formatJobLine } from './JobProgressCard'  // extract a pure helper (Step 2)

describe('formatJobLine', () => {
  it('shows baseline and delta when a later turn improved', () => {
    const line = formatJobLine({
      turns: [{ turn: 0, macro_f1: 0.71, saved: true }, { turn: 4, macro_f1: 0.83, saved: true }],
      bestTurn: { turn: 4, macro_f1: 0.83, saved: true },
    } as any)
    expect(line).toContain('best f1 0.83')
    expect(line).toContain('turn 4')
    expect(line).toContain('baseline 0.71')
    expect(line).toMatch(/\+0\.12|Δ\s*\+0\.12/)
  })
  it('reads "baseline still best" when turn 0 is best', () => {
    const line = formatJobLine({
      turns: [{ turn: 0, macro_f1: 0.91, saved: true }],
      bestTurn: { turn: 0, macro_f1: 0.91, saved: true },
    } as any)
    expect(line).toContain('best f1 0.91')
  })
})
```

- [ ] **Step 2: Run — expect FAIL** (`formatJobLine` not exported)

Run: `cd frontend && npx vitest run src/components/Chat/JobProgressCard.test.tsx`
Expected: FAIL — import error.

- [ ] **Step 3: Extract `formatJobLine` and use it; add baseline; widen the accept condition**

In `JobProgressCard.tsx`:

```tsx
export function formatJobLine(slice: Pick<JobSlice, 'turns' | 'bestTurn'>): string {
  const { turns, bestTurn } = slice
  if (turns.length === 0) return 'starting...'
  const baseline = turns[0]?.macro_f1 ?? 0
  const best = bestTurn?.macro_f1 ?? baseline
  const bestTurnN = bestTurn?.turn ?? 0
  const delta = best - baseline
  const deltaStr = delta === 0 ? '±0.00' : `${delta > 0 ? '+' : ''}${delta.toFixed(2)}`
  return `turn ${turns.length - 1} · best f1 ${best.toFixed(2)} (turn ${bestTurnN}) · baseline ${baseline.toFixed(2)} (Δ ${deltaStr})`
}
```

Replace the `<div className="text-ink-3">…</div>` body with `{formatJobLine(slice)}`.

Then change the accept block so it also fires on `'cancelled'`, and never offers a regression as an "accept":

```tsx
{(status === 'done' || status === 'cancelled') && bestTurn && (
  bestTurn.turn === 0 || (bestTurn.macro_f1 <= (turns[0]?.macro_f1 ?? 0)) ? (
    <span className="ml-auto text-[10px] uppercase tracking-wide text-ink-4">
      baseline still best — schema unchanged
    </span>
  ) : (
    <button
      onClick={() => void accept(jobId, bestTurn.turn)}
      className="ml-auto inline-flex items-center gap-1 px-2 py-1 bg-ochre text-paper rounded uppercase tracking-wide text-[10px]"
      aria-label="accept candidate"
    >
      <Check size={12} /> accept turn {bestTurn.turn}
    </button>
  )
)}
```

(Put this inside the existing `{endedReason && (…)}` block — `endedReason` is set for both `done` and `cancelled`.)

- [ ] **Step 4: Run — expect PASS**

Run: `cd frontend && npx vitest run src/components/Chat/JobProgressCard.test.tsx`
Expected: PASS.

- [ ] **Step 5: Build + playwright + live check (chrome-devtools-mcp)**

`cd frontend && npm run build && npx playwright test` (update any selector that hard-codes the old `turn N · best f1 …` string). Then via chrome-devtools-mcp: select `us-invoice`, submit `/improve` (Meta+Enter), `wait_for "running · turn"`, let it run ~2 turns (`wait_for` on the job line advancing, or just a single ~120 s wait), then `take_snapshot`, find the `JobProgressCard` `cancel` button by `uid` and `click` it, `wait_for "ended (cancelled)"`. The job-card line must show `… best f1 X (turn N) · baseline Y (Δ …)` and either a `baseline still best` note or an `accept turn N` button (and it must NOT offer `accept` when best ≤ baseline). `take_screenshot` → `docs/screenshots/2026-05-11-m7-1-improve-jobcard.png`. `list_console_messages` → no new errors. (The job is cancelled by the check itself — protocol step 8 — so nothing is left running.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Chat/JobProgressCard.tsx frontend/src/components/Chat/JobProgressCard.test.tsx docs/screenshots/2026-05-11-m7-1-improve-jobcard.png
git commit -m "feat(m7): job card shows baseline+delta; accept best turn after cancel; never offer a regression"
```

---

## Task 6: Retire `ProposalCandidateCard` — commit to turn-level accept

**Decision (design owner, 2026-05-11):** the unit of "did this help" in autoresearch is the whole-schema macro F1 *at a given turn* (a turn changes a field description, re-extracts everything, re-scores). Per-field accept across turns is incoherent — a turn-N description was scored in the context of turn N's full schema. So the committed model is **turn-level accept** via the `JobProgressCard` "accept turn N" button (backend `acceptCandidate(projectId, jobId, turn)` → `versions/_candidate/`, already implemented; improved in Task 5). `ProposalCandidateCard` (per-field diff + accept/edit/dismiss) is from a pre-job-architecture sketch and is dead code in the current `/improve` flow (autoresearch runs server-side and never emits `propose_description` as a chat `tool_call`; no chat-exposed `@tool` named `propose_description` exists either — grep `backend/app/tools/__init__.py` to confirm). Delete it. Keep `ProposalDiff.tsx` — it'll be reused for the deferred "preview what turn N changed before you accept it" affordance (see Known-but-deferred).

**Files:**
- Delete: `frontend/src/components/Improve/ProposalCandidateCard.tsx`
- Modify: `frontend/src/components/Chat/MessageList.tsx` — remove the `ProposalCandidateCard` import, the `if (call.tool_name.endsWith('propose_description') && status === 'cand') return <ProposalCandidateCard event={call} />` branch, the now-unused `isProposalCandidate(e)` helper, and simplify `toolStatus` (drop the `if (isProposalCandidate(e)) return 'cand'` line — `'cand'` will no longer be produced from chat events).
- Keep: `frontend/src/components/Chat/ProposalDiff.tsx`, the `'cand'` member on `ToolStatus`, and the `.t-status.cand` CSS rule in `index.css` (cheap; reused by the follow-up).
- Test: if `frontend/src/components/Improve/ProposalCandidateCard.test.tsx` exists, delete it; if `MessageList.test.tsx` has a "renders proposal candidate" case, delete that case.

- [ ] **Step 1: Confirm `propose_description` is not a chat-exposed tool**

Run: `cd backend && grep -rn "propose_description" app/`
Expected: matches only inside the autoresearch *job runner* / proposer code paths (`app/jobs/`, `app/provider/`), **not** in `app/tools/__init__.py`'s `@tool` list. (If it IS a chat `@tool`, stop and reconsider — keep the card and instead just fix its `accept` wiring. It almost certainly isn't.)

- [ ] **Step 2: Delete the component and its routing**

```bash
git rm frontend/src/components/Improve/ProposalCandidateCard.tsx
```
Then in `frontend/src/components/Chat/MessageList.tsx`: remove the import line `import ProposalCandidateCard from '../Improve/ProposalCandidateCard'`; in `ToolCallCard`, delete the `if (call.tool_name.endsWith('propose_description') && status === 'cand') { return <ProposalCandidateCard event={call} /> }` block; delete the `isProposalCandidate` function; in `toolStatus`, delete the `if (isProposalCandidate(e)) return 'cand'` line so it reads:

```tsx
function toolStatus(e: ToolCallEvent): ToolStatus {
  if (e.ok === false) return 'err'
  if (e.tool_result === undefined || e.tool_result === null) return 'run'
  return 'done'
}
```

- [ ] **Step 3: Build + grep for stragglers**

Run: `cd frontend && grep -rn "ProposalCandidateCard" src ; npm run build`
Expected: grep returns nothing; build is green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Chat/MessageList.tsx
git commit -m "refactor(m7): retire ProposalCandidateCard — turn-level accept is the committed model"
```

---

## Task 7: Stop the agent from re-emitting eval / readiness results as markdown tables

**Root cause:** with Tasks 1–2 done, `/eval` renders a real `<EvalCard>` and `/publish` renders a real `<PublishStage>` checklist — but the chat agent *also* prints a `📊 Eval Results — macro F1: …` heading + markdown table (eval) and a `Check | Status | Detail` markdown table (readiness). Double-render. The agent does this because the skill prompts tell it to format the tool output into a table. Fix the prompts to defer to the UI and just give a one-line takeaway.

**Files:**
- Inspect & modify: `backend/app/skills/emerge_extractor.md` (owns `/eval` — it scores against `reviewed/`), `backend/app/skills/emerge_publish.md` (owns `/publish`), and the base chat system prompt if it carries any "format tool results as a table" instruction — grep `backend/app/chat/` and `backend/app/skills/` for `markdown`, `table`, `📊`, `Eval Results`, `precision`, `| Check |`.

- [ ] **Step 1: Find the offending instructions**

Run: `cd backend && grep -rni 'table\|markdown\|📊\|eval results\|precision\|readiness report\|| check |' app/skills app/chat`
Expected: locate the lines in `emerge_extractor.md` / `emerge_publish.md` (and possibly the chat system prompt) that tell the model to render a results table.

- [ ] **Step 2: Rewrite those instructions**

Replace "format the score / readiness output as a markdown table" with something like (adapt wording to the file's voice):

> After calling `score`, the lab UI renders the full per-field precision/recall/F1 table from the tool result. **Do not reproduce that table in your reply.** Give one sentence: the macro F1 and which one or two fields are weakest, then suggest a next step (`/review` more docs, or tighten a description).

> After `readiness_check`, the lab UI renders the readiness checklist from the tool result. **Do not reproduce it as a table.** If `hard_pass` is true, say so in one line and tell the user the next frozen version number; if not, name the failing check(s) and what to fix.

- [ ] **Step 3: Live check (chrome-devtools-mcp)**

Restart the backend (skills are loaded at startup — restart to be safe). Then via chrome-devtools-mcp: select `us-invoice`, submit `/eval` (Meta+Enter), `wait_for "eval result"`, `take_snapshot` — the conversation must show the `<EvalCard>` (paper card, `field | P | R | F1 | nbar` rows, "eval result" header) and **no** `📊 Eval Results` markdown table from the agent. `take_screenshot` → `docs/screenshots/2026-05-11-m7-1-eval-card.png`. Then submit `/publish`, `wait_for "Ready to mint a key"`, snapshot — the `<PublishStage>` check panel must list the 5 real checks (Schema non-empty / Reviewed & F1 / Reviewed fields in schema / No running jobs / Contract diff compat) with human labels, and **no** `Check | Status | Detail` markdown table from the agent. `take_screenshot` → `docs/screenshots/2026-05-11-m7-1-publish-check.png`. `list_console_messages` → no new errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/skills/emerge_extractor.md backend/app/skills/emerge_publish.md docs/screenshots/2026-05-11-m7-1-eval-card.png docs/screenshots/2026-05-11-m7-1-publish-check.png
git commit -m "fix(skills): defer eval/readiness rendering to the UI cards; no markdown dup"
```

---

## Task 8: Diagnose & fix the `Skill ERR` at the start of `/publish` (investigation)

**Symptom:** the first thing the agent does on `/publish` is invoke the SDK `Skill` tool, and it errors — the conversation shows a `▸ Skill ERR` chip with no body. The agent recovers (proceeds without the skill) so the publish flow still works, but un-skilled. Likely the `emerge-publish` skill name the agent uses doesn't match how the skill is registered (the file on disk is `backend/app/skills/emerge_publish.md` — underscore — while the SDK Skill tool may expect `emerge-publish` or a name from `SKILL.md` frontmatter, and `app/skills/` only has `.md` files, not `SKILL.md` directories).

**This is an investigation task — do the diagnosis first, then write the fix as its own commit. Don't pre-commit to a fix until you've seen the error.**

**Files (likely):**
- `backend/app/skills/emerge_publish.md`, `emerge_extractor.md`, `emerge_autoresearch.md`
- `backend/app/chat/` — wherever skills are registered with the `ClaudeSDKClient` (grep for `skill`, `Skill`, `setting_sources`, `agents=`, `SKILL.md`)
- The intended skill names live in `CLAUDE.md` (mentions `emerge-extractor / emerge-autoresearch / emerge-publish`)

- [ ] **Step 1: Reproduce & capture the actual error**

Trigger `/publish` on `us-invoice` via chrome-devtools-mcp (the UI shows a `▸ Skill ERR` chip but with no body — the error text isn't surfaced there). Capture the real error from: (a) the backend server log (run it in the foreground / `tail` its log while reproducing), and/or (b) the chat JSONL for that conversation — find it under the workspace `chats/` (or per-project `chat/`) dir, locate the `tool_call` with `tool_name` like `Skill` and the paired `tool_result` event, and read its `result_text`. Note the exact error string **and** the skill name the agent passed to the `Skill` tool.

- [ ] **Step 2: Compare to how skills are registered**

Find where the SDK client is configured with skills (grep `backend/app/chat` for `skill` / `Skill` / `SKILL.md` / `setting_sources`). Determine whether the SDK expects: (a) a `skills/` dir of `<name>/SKILL.md` folders, (b) explicit registration of `app/skills/*.md` under specific names, or (c) something else. Cross-check the names the agent's slash-command prompts use (`/publish` → which skill?).

- [ ] **Step 3: Fix the mismatch**

Most likely one of:
- rename/relocate `app/skills/emerge_publish.md` → the structure the SDK expects (e.g. `app/skills/emerge-publish/SKILL.md`), and likewise for the other two skills; **or**
- fix the skill *name* the agent references so it matches the registered name; **or**
- register the skills explicitly if registration was missing.
Make whichever change is correct given Step 2. Keep `app/skills/__init__.py` consistent if it enumerates them.

- [ ] **Step 4: Verify**

Re-run `/publish` (and `/extract`, `/improve` — they reference the other two skills): no `Skill ERR` chip; the agent's behavior should reflect the skill content (e.g. the publish readiness narrative). Run `cd backend && uv run pytest -v`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/skills backend/app/chat
git commit -m "fix(skills): <describe the mismatch found> — Skill tool no longer errors on /publish"
```

---

## Task 9: Wrap-up — design-decisions log + roadmap

- [ ] **Step 1: Append to `docs/design-decisions.md`**

One entry per UI-shaped change above. Status ✅ Accepted, one-line "what changed / why", reference this plan file:
- publish-stage eyebrow shows project name not `project_id` (T3)
- english-only labels in the key-reveal card (T4)
- job card shows baseline + delta; accept-best-turn after cancel; never offers a regression (T5)
- **`ProposalCandidateCard` retired — autoresearch accept is turn-level, not per-field (T6)** — this is the load-bearing design decision; spell out the reasoning (per-turn macro F1 is the unit of "did this help"; a turn-N description was scored in turn N's full-schema context).
- agent no longer re-emits eval / readiness results as markdown tables; the UI cards are canonical (T7)

- [ ] **Step 2: Update `docs/superpowers/plans/ROADMAP.md`**

Add a row: `| **M7.1** — design-handoff wiring & polish | 2026-05-11-m7-1-handoff-wiring-fixes.md | ✅ shipped | <commit-range> |`. Resolve the M7 follow-up bullets that this plan closed; the eval→metrics one stays open (now an explicit M7.2 candidate — see Known-but-deferred). Add the two M7.2 candidates as new "Open cross-cutting follow-ups" rows (eval→metrics panel; per-turn-diff preview on accept).

- [ ] **Step 3: Commit**

```bash
git add docs/design-decisions.md docs/superpowers/plans/ROADMAP.md
git commit -m "docs(m7.1): decisions log + roadmap"
```

---

## Known-but-deferred (M7.2 candidates — out of this plan by decision, 2026-05-11)

- **`/eval` result → right-panel `metrics/` section.** Right now `ContextSurface` hard-codes `precision 0.94 / recall 0.91 / f1 0.92 / coverage 100%` and logs `metrics section uses placeholder data — useEval not wired yet`. Wiring the latest `score` result (or the `metrics/eval_*.json` snapshot the tool already persists) into a `useEval` store + that panel is the right fix, but it wants a tiny read endpoint (e.g. `GET /lab/projects/:id/evals/latest`) and a store — bigger than a polish task, and the M7 plan already logged "metrics tree section deferred until eval history is exposed via API". **Decision: defer to M7.2 / fold into a metrics-API milestone.**
- **"Preview what turn N changed before you accept it"** on the `JobProgressCard` accept affordance — i.e. when the user is about to `accept turn N`, show the field-description diffs that turn introduced (old → new), reusing `ProposalDiff.tsx`. Needs the autoresearch job/turn event (or the `versions/_candidate/` blob) to carry the per-turn schema delta — small server-side work. Deferred to M7.2; this is the proper home for the diff UI now that per-field streaming cards are retired (Task 6).

---

## Self-Review

- **Spec coverage:** every finding from the 2026-05-11 verification is either a task here (eval card not rendering → T1+T2; publish checklist placeholder → T2; eyebrow project_id → T3; CN/EN labels → T4; job card no baseline / no accept after cancel → T5; per-field candidate card unreachable → T6, resolved by retiring it + committing to turn-level accept; redundant markdown tables → T7; `Skill ERR` → T8) or explicitly deferred with a reason (eval→metrics panel, per-turn-diff-on-accept — both M7.2 candidates) or explicitly out-of-scope-by-design (inline publish panel, mint-via-agent, `new project…`).
- **Placeholder scan:** the only "investigate then fix" task is T8, which is *labelled* an investigation and gives concrete diagnostic steps + the likely fix shapes — not a blank "fix it". T1 Step 1's workspace-root import is hedged ("grep `app/workspace/paths.py`") because the exact accessor name wasn't verified; that's a 30-second lookup for the executor, not a hidden TODO.
- **Type consistency:** `CheckItem` (existing, has `key/label/ok/detail`) — `adaptReadiness` (T2) returns `CheckItem[]`; `humanizeKey` feeds `label`. `formatJobLine` (T5) takes `Pick<JobSlice,'turns'|'bestTurn'>`; `JobSlice.turns: TurnEvent[]`, `TurnEvent` has `turn/macro_f1/saved` (see `frontend/src/types/job.ts` — confirm `saved` is the field name; the jobs store reads `data.saved`). `useProjectName` (T3) returns the `Project.name` from `useProjects.projects`. `adaptScoreResult` (T2) reads `sr.ts` — added to the `ScoreResult` interface in the same step.
