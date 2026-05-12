# M9.0 — Schema Quick-look Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ship a read-only Quick-look modal sheet so users can see the full `schema.json` or a frozen `versions/v{N}.json` in one click from FSSpine or ContextSurface — `description`, `examples`, `enum`, and raw JSON all visible, no truncation, no edit affordance.

**Architecture:** new `frontend/src/components/QuickLook/` module (5 files), one new Zustand store `quicklook.ts`, two new read-only backend endpoints on the existing `schema.py` router. Entry points wire into `ContextSurface.tsx` and `FSSpine.tsx`. Sheet is schema-shaped (header takes `schemaId`, reserves a `lineage` row and per-field `notes-hint` slot) so M9a/M9b/M9d can plug in without redesign.

**Tech Stack:** FastAPI + pydantic v2 (backend); React 19 + TypeScript + Zustand + Vite + Vitest + RTL + Playwright (frontend). CSS tokens from `frontend/src/theme/tokens.css` (`--ink-*`, `--paper-*`, `--ochre`, `--moss`, `--rose`).

**Reference docs:**
- Spec: `docs/superpowers/specs/2026-05-12-schema-quicklook-design.md` — read this first
- Parent spec: `docs/superpowers/specs/2026-05-08-agent-native-design.md`
- Codebase rules: `/CLAUDE.md` (hard rules: no edit in sheet; copy button is the only mutation-shaped affordance and it's read-out only)

**Conventions used in this plan:**
- Backend test command: `cd backend && uv run pytest <path> -v`
- Frontend unit-test command: `cd frontend && npm test -- <pattern>`  (uses `vitest run`)
- Frontend e2e command: `cd frontend && npm run e2e -- <pattern>`
- Frontend unit tests live under `frontend/tests/unit/`, e2e under `frontend/tests/e2e/`
- Every task ends in a single `git commit`. Commit prefix follows repo convention seen in `git log` (`feat:`, `feat(ql):`, `test:`, `chore:`)

---

## Task 1: Backend — `GET /lab/projects/{pid}/schema/raw`

**Files:**
- Modify: `backend/app/api/routes/schema.py` (append new endpoint after `accept_candidate`)
- Test: `backend/tests/unit/test_schema_raw_endpoints.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_schema_raw_endpoints.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workspace.paths import schema_path


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    # Re-import settings so the env override takes
    from app.config import get_settings
    get_settings.cache_clear()  # type: ignore[attr-defined]
    return TestClient(app)


def _write_schema(tmp_path: Path, pid: str, fields: list[dict]) -> None:
    pdir = tmp_path / pid
    pdir.mkdir(parents=True, exist_ok=True)
    schema_path(tmp_path, pid).write_text(json.dumps(fields))


def test_schema_raw_returns_pretty_printed_text(client: TestClient, tmp_path: Path) -> None:
    fields = [
        {"name": "invoice_number", "type": "string", "description": "Invoice ID", "required": True},
        {"name": "total_amount", "type": "number", "description": "Total"},
    ]
    _write_schema(tmp_path, "p_test", fields)

    resp = client.get("/lab/projects/p_test/schema/raw")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    # pretty-printed: contains newlines + 2-space indent
    assert "\n" in body
    assert '  "name": "invoice_number"' in body
    # round-trippable
    assert json.loads(body) == fields


def test_schema_raw_returns_404_when_missing(client: TestClient) -> None:
    resp = client.get("/lab/projects/p_missing/schema/raw")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "schema_not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_schema_raw_endpoints.py::test_schema_raw_returns_pretty_printed_text -v`

Expected: FAIL with `404 Not Found` (endpoint doesn't exist).

- [ ] **Step 3: Implement the endpoint**

Append to `backend/app/api/routes/schema.py`:

```python
import json as _json  # alias to avoid shadowing if used; existing `import json` is fine — just reuse
from fastapi.responses import PlainTextResponse
from app.workspace.paths import schema_path, version_path


@router.get("/lab/projects/{project_id}/schema/raw", response_class=PlainTextResponse)
async def get_project_schema_raw(project_id: str) -> PlainTextResponse:
    safe_project_id(project_id)
    settings = get_settings()
    sp = schema_path(settings.workspace_root, project_id)
    if not sp.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "schema_not_found"},
        )
    parsed = json.loads(sp.read_text())
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    return PlainTextResponse(pretty, media_type="text/plain; charset=utf-8")
```

Note: `json`, `HTTPException`, `safe_project_id`, and `get_settings` are already imported. Add only the `PlainTextResponse` import and the `schema_path, version_path` import (you'll use `version_path` in Task 2).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_schema_raw_endpoints.py -v`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/schema.py backend/tests/unit/test_schema_raw_endpoints.py
git commit -m "feat(ql): GET /lab/projects/{pid}/schema/raw returns pretty-printed schema.json"
```

---

## Task 2: Backend — `GET /lab/projects/{pid}/versions/{vid}/raw[?shape=fields]`

**Files:**
- Modify: `backend/app/api/routes/schema.py`
- Test: `backend/tests/unit/test_schema_raw_endpoints.py` (extend)

The version endpoint supports two response shapes:
- default (text/plain): pretty-printed raw `versions/v{N}.json`
- `?shape=fields` (application/json): parses the version, returns `{ "fields": [...], "frozen_at": "...", ... }` passthrough so the Fields tab can render version data without a separate parser.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_schema_raw_endpoints.py`:

```python
def _write_version(tmp_path: Path, pid: str, n: int, blob: dict) -> None:
    vdir = tmp_path / pid / "versions"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / f"v{n}.json").write_text(json.dumps(blob))


def test_version_raw_returns_pretty_printed_text(client: TestClient, tmp_path: Path) -> None:
    blob = {
        "fields": [{"name": "x", "type": "string", "description": "x field"}],
        "frozen_at": "2026-05-10T00:00:00+00:00",
    }
    _write_version(tmp_path, "p_test", 6, blob)

    resp = client.get("/lab/projects/p_test/versions/v6/raw")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert json.loads(resp.text) == blob


def test_version_raw_shape_fields_returns_json(client: TestClient, tmp_path: Path) -> None:
    blob = {
        "fields": [{"name": "x", "type": "string", "description": "x field"}],
        "frozen_at": "2026-05-10T00:00:00+00:00",
    }
    _write_version(tmp_path, "p_test", 6, blob)

    resp = client.get("/lab/projects/p_test/versions/v6/raw?shape=fields")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    payload = resp.json()
    assert payload["fields"] == blob["fields"]
    assert payload["frozen_at"] == blob["frozen_at"]


def test_version_raw_returns_404_when_missing(client: TestClient) -> None:
    resp = client.get("/lab/projects/p_x/versions/v99/raw")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "version_not_found"


def test_version_raw_rejects_malformed_version_id(client: TestClient) -> None:
    resp = client.get("/lab/projects/p_x/versions/notaversion/raw")
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "invalid_version_id"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_schema_raw_endpoints.py -v -k "version"`

Expected: 4 failures (404 / 400 expected codes, endpoint missing).

- [ ] **Step 3: Implement the endpoint**

Append to `backend/app/api/routes/schema.py`:

```python
from fastapi import Query
from app.workspace.paths import parse_version_id


@router.get("/lab/projects/{project_id}/versions/{version_id}/raw")
async def get_project_version_raw(
    project_id: str,
    version_id: str,
    shape: str | None = Query(default=None),
):
    safe_project_id(project_id)
    n = parse_version_id(version_id)
    if n is None:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_version_id"},
        )
    settings = get_settings()
    vp = version_path(settings.workspace_root, project_id, n)
    if not vp.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "version_not_found"},
        )
    parsed = json.loads(vp.read_text())
    if shape == "fields":
        # passthrough: the frozen file is the source of truth; the Fields tab
        # consumes `fields[]` directly and ignores extra keys it doesn't know.
        return parsed
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    return PlainTextResponse(pretty, media_type="text/plain; charset=utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_schema_raw_endpoints.py -v`

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/schema.py backend/tests/unit/test_schema_raw_endpoints.py
git commit -m "feat(ql): GET /lab/projects/{pid}/versions/{vid}/raw with optional shape=fields"
```

---

## Task 3: Frontend — `useQuickLook` store

**Files:**
- Create: `frontend/src/stores/quicklook.ts`
- Test: `frontend/tests/unit/quicklook-store.test.ts` (new)

The store holds the open/closed target and the lazy-loaded raw JSON. No global side effects on open (`useSchema` already has the fields for `kind=schema`); raw JSON loads on tab switch.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/quicklook-store.test.ts`:

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useQuickLook } from '../../src/stores/quicklook'

describe('useQuickLook store', () => {
  beforeEach(() => {
    useQuickLook.getState().close()
  })

  it('opens schema target', () => {
    useQuickLook.getState().openSchema('p_test')
    expect(useQuickLook.getState().target).toEqual({ kind: 'schema', pid: 'p_test' })
    expect(useQuickLook.getState().rawJson).toEqual({ value: null, loading: false, error: null })
  })

  it('opens version target', () => {
    useQuickLook.getState().openVersion('p_test', 'v6')
    expect(useQuickLook.getState().target).toEqual({ kind: 'version', pid: 'p_test', versionId: 'v6' })
  })

  it('close clears target and rawJson', () => {
    useQuickLook.getState().openSchema('p_test')
    useQuickLook.getState().close()
    expect(useQuickLook.getState().target).toBeNull()
    expect(useQuickLook.getState().rawJson.value).toBeNull()
  })

  it('opening a different target resets rawJson cache', () => {
    useQuickLook.getState().openSchema('p_a')
    // Simulate a loaded raw value:
    useQuickLook.setState({ rawJson: { value: '[]', loading: false, error: null } })
    useQuickLook.getState().openSchema('p_b')
    expect(useQuickLook.getState().rawJson.value).toBeNull()
  })

  it('loadRaw fetches schema/raw and stores text on success', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('[\n  "x"\n]', { status: 200, headers: { 'content-type': 'text/plain' } }),
    )
    useQuickLook.getState().openSchema('p_test')
    await useQuickLook.getState().loadRaw()
    expect(fetchSpy).toHaveBeenCalledWith('/lab/projects/p_test/schema/raw')
    expect(useQuickLook.getState().rawJson).toEqual({ value: '[\n  "x"\n]', loading: false, error: null })
    fetchSpy.mockRestore()
  })

  it('loadRaw fetches versions/{vid}/raw for version target', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('{}', { status: 200, headers: { 'content-type': 'text/plain' } }),
    )
    useQuickLook.getState().openVersion('p_test', 'v6')
    await useQuickLook.getState().loadRaw()
    expect(fetchSpy).toHaveBeenCalledWith('/lab/projects/p_test/versions/v6/raw')
    fetchSpy.mockRestore()
  })

  it('loadRaw records error on non-2xx', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('{"detail":{"error_code":"schema_not_found"}}', {
        status: 404,
        headers: { 'content-type': 'application/json' },
      }),
    )
    useQuickLook.getState().openSchema('p_test')
    await useQuickLook.getState().loadRaw()
    expect(useQuickLook.getState().rawJson.error).toBe('schema_not_found')
    expect(useQuickLook.getState().rawJson.value).toBeNull()
    fetchSpy.mockRestore()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- quicklook-store`

Expected: FAIL with "Cannot find module .../stores/quicklook".

- [ ] **Step 3: Implement the store**

Create `frontend/src/stores/quicklook.ts`:

```typescript
import { create } from 'zustand'

export type QuickLookTarget =
  | { kind: 'schema'; pid: string }
  | { kind: 'version'; pid: string; versionId: string }

interface RawJsonSlot {
  value: string | null
  loading: boolean
  error: string | null
}

interface QuickLookState {
  target: QuickLookTarget | null
  rawJson: RawJsonSlot

  openSchema: (pid: string) => void
  openVersion: (pid: string, versionId: string) => void
  close: () => void
  loadRaw: () => Promise<void>
}

const EMPTY_RAW: RawJsonSlot = { value: null, loading: false, error: null }

export const useQuickLook = create<QuickLookState>((set, get) => ({
  target: null,
  rawJson: EMPTY_RAW,

  openSchema: pid => set({ target: { kind: 'schema', pid }, rawJson: EMPTY_RAW }),
  openVersion: (pid, versionId) =>
    set({ target: { kind: 'version', pid, versionId }, rawJson: EMPTY_RAW }),
  close: () => set({ target: null, rawJson: EMPTY_RAW }),

  loadRaw: async () => {
    const t = get().target
    if (!t) return
    set({ rawJson: { value: null, loading: true, error: null } })
    const url =
      t.kind === 'schema'
        ? `/lab/projects/${t.pid}/schema/raw`
        : `/lab/projects/${t.pid}/versions/${t.versionId}/raw`
    try {
      const resp = await fetch(url)
      if (!resp.ok) {
        let code = `http_${resp.status}`
        try {
          const j = await resp.json()
          code = j?.detail?.error_code ?? code
        } catch { /* not json */ }
        set({ rawJson: { value: null, loading: false, error: code } })
        return
      }
      const text = await resp.text()
      // Guard against a stale response if the user changed targets while the fetch was in flight.
      if (get().target !== t) return
      set({ rawJson: { value: text, loading: false, error: null } })
    } catch (e) {
      set({ rawJson: { value: null, loading: false, error: (e as Error).message ?? 'fetch_failed' } })
    }
  },
}))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- quicklook-store`

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/quicklook.ts frontend/tests/unit/quicklook-store.test.ts
git commit -m "feat(ql): add useQuickLook store with lazy raw-json loading"
```

---

## Task 4: Frontend — `FieldCard` component

**Files:**
- Create: `frontend/src/components/QuickLook/FieldCard.tsx`
- Create: `frontend/src/components/QuickLook/styles.css`
- Test: `frontend/tests/unit/FieldCard.test.tsx` (new)

Recursive field renderer. Handles primitive types, `enum`, `examples` truncation at 6, `array<object>` children with a disclosure caret, and the reserved `notes-hint` slot rendered as `—` for now.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/FieldCard.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import FieldCard from '../../src/components/QuickLook/FieldCard'
import type { SchemaField } from '../../src/lib/api'  // existing type

const F = (over: Partial<SchemaField>): SchemaField => ({
  name: 'x',
  type: 'string',
  description: 'desc',
  ...over,
} as SchemaField)

describe('FieldCard', () => {
  it('renders name, type, description', () => {
    render(<FieldCard field={F({ name: 'invoice_number', description: 'the id' })} />)
    expect(screen.getByText('invoice_number')).toBeInTheDocument()
    expect(screen.getByText('string')).toBeInTheDocument()
    expect(screen.getByText('the id')).toBeInTheDocument()
  })

  it('shows required pill only when required=true', () => {
    const { rerender } = render(<FieldCard field={F({ required: true })} />)
    expect(screen.getByText('REQUIRED')).toBeInTheDocument()
    rerender(<FieldCard field={F({ required: false })} />)
    expect(screen.queryByText('REQUIRED')).not.toBeInTheDocument()
  })

  it('renders (no description) placeholder when description is empty', () => {
    render(<FieldCard field={F({ description: '' })} />)
    expect(screen.getByText('(no description)')).toBeInTheDocument()
  })

  it('renders examples joined by comma, capped at 6', () => {
    render(<FieldCard field={F({ examples: ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'] })} />)
    expect(screen.getByText(/examples · a, b, c, d, e, f/)).toBeInTheDocument()
    expect(screen.getByText(/\+ 2 more/)).toBeInTheDocument()
  })

  it('renders enum list when present', () => {
    render(<FieldCard field={F({ enum: ['draft', 'published'] })} />)
    expect(screen.getByText('enum · draft, published')).toBeInTheDocument()
  })

  it('reserves notes-hint slot rendered as em-dash placeholder', () => {
    render(<FieldCard field={F({})} />)
    expect(screen.getByTestId('field-notes-hint').textContent).toBe('—')
  })

  it('array<object> children are collapsed by default and expand on click', () => {
    const f = F({
      name: 'line_items',
      type: 'array<object>',
      children: [F({ name: 'sku', description: 'sku id' })],
    })
    render(<FieldCard field={f} />)
    // child not visible
    expect(screen.queryByText('sku')).not.toBeInTheDocument()
    // disclosure caret + children count
    expect(screen.getByText('children: 1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /expand line_items/i }))
    expect(screen.getByText('sku')).toBeInTheDocument()
  })

  it('children render recursively (no depth cap)', () => {
    const f = F({
      name: 'a',
      type: 'array<object>',
      children: [
        F({ name: 'b', type: 'array<object>', children: [F({ name: 'c' })] }),
      ],
    })
    render(<FieldCard field={f} defaultExpanded />)
    expect(screen.getByText('a')).toBeInTheDocument()
    expect(screen.getByText('b')).toBeInTheDocument()
    // c needs its parent expanded too — but defaultExpanded propagates
    expect(screen.getByText('c')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- FieldCard`

Expected: FAIL with "Cannot find module".

- [ ] **Step 3: Create stylesheet**

Create `frontend/src/components/QuickLook/styles.css`:

```css
/* Quick-look modal sheet. Centered portal with scrim. */

.ql-scrim {
  position: fixed; inset: 0;
  background: rgba(27, 26, 22, 0.32);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
  animation: ql-fade-in 200ms ease-out;
}

.ql-sheet {
  background: var(--paper);
  color: var(--ink);
  border: 1px solid var(--paper-3);
  border-radius: 8px;
  width: min(720px, 92vw);
  max-height: 86vh;
  display: flex; flex-direction: column;
  box-shadow: 0 12px 48px rgba(27, 26, 22, 0.18);
  animation: ql-slide-in 200ms ease-out;
}

@keyframes ql-fade-in { from { opacity: 0 } to { opacity: 1 } }
@keyframes ql-slide-in { from { opacity: 0; transform: translateY(8px) } to { opacity: 1; transform: translateY(0) } }

/* Header */
.ql-header { padding: 16px 20px 12px 20px; border-bottom: 1px solid var(--paper-3); }
.ql-header-row { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.ql-title { font-family: var(--mono, ui-monospace, monospace); font-size: 14px; color: var(--ink-2); }
.ql-badge { font-family: var(--mono, ui-monospace, monospace); font-size: 11px; color: var(--ink-4); letter-spacing: 0.04em; text-transform: lowercase; }
.ql-badge--active { color: var(--moss); }
.ql-badge--frozen { color: var(--ink-3); }
.ql-close { background: none; border: 0; cursor: pointer; font-size: 16px; color: var(--ink-3); padding: 4px; line-height: 1; }
.ql-close:hover { color: var(--ink); }
.ql-lineage { margin-top: 6px; font-family: var(--mono, ui-monospace, monospace); font-size: 11px; color: var(--ink-4); }

/* Tabs */
.ql-tabs { display: flex; gap: 4px; padding: 8px 20px 0 20px; border-bottom: 1px solid var(--paper-3); }
.ql-tab { background: none; border: 0; cursor: pointer; padding: 8px 12px; font-family: var(--mono, ui-monospace, monospace); font-size: 12px; color: var(--ink-4); border-bottom: 2px solid transparent; }
.ql-tab--active { color: var(--ink); border-bottom-color: var(--ochre); }

/* Body */
.ql-body { padding: 16px 20px; overflow-y: auto; flex: 1; }

/* Field cards */
.ql-field { padding: 10px 0; border-bottom: 1px dashed var(--paper-3); }
.ql-field:last-child { border-bottom: 0; }
.ql-field-head { display: flex; align-items: baseline; gap: 10px; }
.ql-field-name { font-family: var(--mono, ui-monospace, monospace); font-size: 13px; color: var(--ink); }
.ql-field-type { font-family: var(--mono, ui-monospace, monospace); font-size: 12px; color: var(--ink-4); font-style: italic; }
.ql-field-required { font-family: var(--mono, ui-monospace, monospace); font-size: 10px; color: var(--ochre); letter-spacing: 0.08em; }
.ql-field-desc { margin-top: 4px; font-size: 13px; color: var(--ink-2); line-height: 1.4; }
.ql-field-desc--empty { color: var(--ink-5); font-style: italic; }
.ql-field-examples, .ql-field-enum, .ql-field-notes { margin-top: 4px; font-family: var(--mono, ui-monospace, monospace); font-size: 11px; color: var(--ink-4); }
.ql-field-disclosure { background: none; border: 0; cursor: pointer; font-family: var(--mono, ui-monospace, monospace); font-size: 11px; color: var(--ink-3); padding: 4px 0 0 0; }
.ql-field-children { margin-top: 8px; padding-left: 12px; border-left: 1px solid var(--paper-3); }

/* Raw JSON tab */
.ql-raw { font-family: var(--mono, ui-monospace, monospace); font-size: 12px; background: var(--paper-2); padding: 12px; border-radius: 4px; white-space: pre; overflow-x: auto; }
.ql-raw-copy { float: right; background: none; border: 1px solid var(--paper-3); padding: 2px 8px; font-family: var(--mono, ui-monospace, monospace); font-size: 11px; cursor: pointer; color: var(--ink-3); }
.ql-raw-copy:hover { color: var(--ink); border-color: var(--ink-4); }
.ql-raw-error { color: var(--rose); font-family: var(--mono, ui-monospace, monospace); font-size: 12px; padding: 8px 0; }
.ql-raw-retry { background: none; border: 0; color: var(--ochre); cursor: pointer; font-family: var(--mono, ui-monospace, monospace); font-size: 12px; padding: 0; margin-left: 8px; }

/* Footer */
.ql-footer { padding: 12px 20px; border-top: 1px solid var(--paper-3); font-size: 12px; color: var(--ink-4); line-height: 1.4; }
```

- [ ] **Step 4: Implement `FieldCard.tsx`**

Create `frontend/src/components/QuickLook/FieldCard.tsx`:

```tsx
import { useState } from 'react'
import './styles.css'
import type { SchemaField } from '../../lib/api'

const EXAMPLES_VISIBLE = 6

interface Props {
  field: SchemaField
  defaultExpanded?: boolean
}

export default function FieldCard({ field, defaultExpanded = false }: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const hasChildren = field.type === 'array<object>' && Array.isArray(field.children) && field.children.length > 0

  const examplesVisible = (field.examples ?? []).slice(0, EXAMPLES_VISIBLE)
  const examplesExtra = (field.examples?.length ?? 0) - examplesVisible.length

  return (
    <div className="ql-field">
      <div className="ql-field-head">
        <span className="ql-field-name">{field.name}</span>
        <span className="ql-field-type">{field.type}</span>
        {field.required && <span className="ql-field-required">REQUIRED</span>}
      </div>

      <div className={`ql-field-desc${field.description ? '' : ' ql-field-desc--empty'}`}>
        {field.description || '(no description)'}
      </div>

      {examplesVisible.length > 0 && (
        <div className="ql-field-examples">
          examples · {examplesVisible.join(', ')}
          {examplesExtra > 0 ? ` … + ${examplesExtra} more` : ''}
        </div>
      )}

      {Array.isArray(field.enum) && field.enum.length > 0 && (
        <div className="ql-field-enum">enum · {field.enum.join(', ')}</div>
      )}

      <div className="ql-field-notes" data-testid="field-notes-hint">—</div>

      {hasChildren && (
        <>
          <button
            type="button"
            className="ql-field-disclosure"
            aria-label={`${expanded ? 'collapse' : 'expand'} ${field.name}`}
            onClick={() => setExpanded(v => !v)}
          >
            {expanded ? '▾' : '▸'} children: {field.children!.length}
          </button>
          {expanded && (
            <div className="ql-field-children">
              {field.children!.map(child => (
                <FieldCard key={child.name} field={child} defaultExpanded={defaultExpanded} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
```

Note: If `SchemaField` is not exported from `frontend/src/lib/api.ts`, check what type the existing `useSchema` store uses and import from there. The shape should match `backend/app/schemas/schema_field.py`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test -- FieldCard`

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/QuickLook/FieldCard.tsx frontend/src/components/QuickLook/styles.css frontend/tests/unit/FieldCard.test.tsx
git commit -m "feat(ql): FieldCard recursive renderer with examples/enum/notes-slot"
```

---

## Task 5: Frontend — `FieldsTab` component

**Files:**
- Create: `frontend/src/components/QuickLook/FieldsTab.tsx`
- Test: `frontend/tests/unit/FieldsTab.test.tsx` (new)

Renders the list of `FieldCard`s. Handles two data sources: `kind=schema` reads from `useSchema(pid)`; `kind=version` fetches `versions/{vid}/raw?shape=fields` on mount and renders the parsed `fields[]`.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/FieldsTab.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import FieldsTab from '../../src/components/QuickLook/FieldsTab'
import { useSchema } from '../../src/stores/schema'

describe('FieldsTab', () => {
  beforeEach(() => {
    useSchema.setState({ byProject: {} })
  })

  it('renders empty placeholder when project has no fields (schema kind)', () => {
    useSchema.setState({ byProject: { p_test: [] } })
    render(<FieldsTab target={{ kind: 'schema', pid: 'p_test' }} />)
    expect(screen.getByText(/no schema yet/i)).toBeInTheDocument()
  })

  it('renders all fields with no truncation (schema kind)', () => {
    const fields = Array.from({ length: 12 }, (_, i) => ({
      name: `field_${i}`,
      type: 'string' as const,
      description: '',
    }))
    useSchema.setState({ byProject: { p_test: fields } })
    render(<FieldsTab target={{ kind: 'schema', pid: 'p_test' }} />)
    for (let i = 0; i < 12; i++) {
      expect(screen.getByText(`field_${i}`)).toBeInTheDocument()
    }
  })

  it('fetches version fields on mount for version kind', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({ fields: [{ name: 'frozen_field', type: 'string', description: '' }] }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
    render(<FieldsTab target={{ kind: 'version', pid: 'p_test', versionId: 'v6' }} />)
    await waitFor(() => expect(screen.getByText('frozen_field')).toBeInTheDocument())
    expect(fetchSpy).toHaveBeenCalledWith('/lab/projects/p_test/versions/v6/raw?shape=fields')
    fetchSpy.mockRestore()
  })

  it('renders error message when version fetch fails', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('{"detail":{"error_code":"version_not_found"}}', { status: 404 }),
    )
    render(<FieldsTab target={{ kind: 'version', pid: 'p_test', versionId: 'v99' }} />)
    await waitFor(() => expect(screen.getByText(/version_not_found/i)).toBeInTheDocument())
    fetchSpy.mockRestore()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- FieldsTab`

Expected: FAIL with "Cannot find module".

- [ ] **Step 3: Implement `FieldsTab.tsx`**

Create `frontend/src/components/QuickLook/FieldsTab.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useSchema } from '../../stores/schema'
import FieldCard from './FieldCard'
import type { QuickLookTarget } from '../../stores/quicklook'
import type { SchemaField } from '../../lib/api'

interface Props {
  target: QuickLookTarget
}

export default function FieldsTab({ target }: Props) {
  if (target.kind === 'schema') return <SchemaFields pid={target.pid} />
  return <VersionFields pid={target.pid} versionId={target.versionId} />
}

function SchemaFields({ pid }: { pid: string }) {
  const fields = useSchema(useShallow(s => s.byProject[pid] ?? []))
  if (fields.length === 0) {
    return (
      <div className="ql-field ql-field-desc ql-field-desc--empty">
        no schema yet — type /init in the chat
      </div>
    )
  }
  return <FieldList fields={fields} />
}

function VersionFields({ pid, versionId }: { pid: string; versionId: string }) {
  const [state, setState] = useState<{ fields: SchemaField[] | null; error: string | null }>({
    fields: null,
    error: null,
  })

  useEffect(() => {
    let cancelled = false
    fetch(`/lab/projects/${pid}/versions/${versionId}/raw?shape=fields`)
      .then(async resp => {
        if (!resp.ok) {
          let code = `http_${resp.status}`
          try {
            const j = await resp.json()
            code = j?.detail?.error_code ?? code
          } catch { /* */ }
          if (!cancelled) setState({ fields: null, error: code })
          return
        }
        const blob = await resp.json()
        if (!cancelled) setState({ fields: blob.fields ?? [], error: null })
      })
      .catch(e => { if (!cancelled) setState({ fields: null, error: (e as Error).message }) })
    return () => { cancelled = true }
  }, [pid, versionId])

  if (state.error) return <div className="ql-raw-error">{state.error}</div>
  if (state.fields === null) return <div className="ql-field-desc ql-field-desc--empty">loading…</div>
  if (state.fields.length === 0) {
    return <div className="ql-field ql-field-desc ql-field-desc--empty">empty version</div>
  }
  return <FieldList fields={state.fields} />
}

function FieldList({ fields }: { fields: SchemaField[] }) {
  return (
    <>
      {fields.map(f => <FieldCard key={f.name} field={f} />)}
    </>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- FieldsTab`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/QuickLook/FieldsTab.tsx frontend/tests/unit/FieldsTab.test.tsx
git commit -m "feat(ql): FieldsTab reads useSchema for kind=schema, fetches frozen for kind=version"
```

---

## Task 6: Frontend — `RawJsonTab` component

**Files:**
- Create: `frontend/src/components/QuickLook/RawJsonTab.tsx`
- Test: `frontend/tests/unit/RawJsonTab.test.tsx` (new)

Calls `useQuickLook.loadRaw()` on mount (lazy — only mounted when user clicks the raw-json tab). Shows loading / error / value states. Has a `copy` button that writes to clipboard.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/RawJsonTab.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RawJsonTab from '../../src/components/QuickLook/RawJsonTab'
import { useQuickLook } from '../../src/stores/quicklook'

describe('RawJsonTab', () => {
  beforeEach(() => {
    useQuickLook.setState({
      target: { kind: 'schema', pid: 'p_test' },
      rawJson: { value: null, loading: false, error: null },
    })
  })

  it('shows loading state initially and resolves to value', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('[\n  {"name":"x"}\n]', { status: 200, headers: { 'content-type': 'text/plain' } }),
    )
    render(<RawJsonTab />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/"name":\s*"x"/)).toBeInTheDocument())
  })

  it('shows error message and retry link on failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('{"detail":{"error_code":"schema_not_found"}}', { status: 404 }),
    )
    render(<RawJsonTab />)
    await waitFor(() => expect(screen.getByText(/schema_not_found/i)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })

  it('copy button writes value to clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    useQuickLook.setState({
      target: { kind: 'schema', pid: 'p_test' },
      rawJson: { value: '[\n  "abc"\n]', loading: false, error: null },
    })
    render(<RawJsonTab />)
    await userEvent.click(screen.getByRole('button', { name: /copy/i }))
    expect(writeText).toHaveBeenCalledWith('[\n  "abc"\n]')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- RawJsonTab`

Expected: FAIL with "Cannot find module".

- [ ] **Step 3: Implement `RawJsonTab.tsx`**

Create `frontend/src/components/QuickLook/RawJsonTab.tsx`:

```tsx
import { useEffect } from 'react'
import { useQuickLook } from '../../stores/quicklook'

export default function RawJsonTab() {
  const rawJson = useQuickLook(s => s.rawJson)
  const loadRaw = useQuickLook(s => s.loadRaw)
  const target = useQuickLook(s => s.target)

  useEffect(() => {
    if (!target) return
    if (rawJson.value === null && !rawJson.loading && !rawJson.error) {
      void loadRaw()
    }
  }, [target, rawJson.value, rawJson.loading, rawJson.error, loadRaw])

  if (rawJson.error) {
    return (
      <div className="ql-raw-error">
        {rawJson.error}
        <button type="button" className="ql-raw-retry" onClick={() => loadRaw()}>retry</button>
      </div>
    )
  }
  if (rawJson.loading || rawJson.value === null) {
    return <div className="ql-field-desc ql-field-desc--empty">loading…</div>
  }
  return (
    <div>
      <button
        type="button"
        className="ql-raw-copy"
        onClick={() => navigator.clipboard?.writeText(rawJson.value ?? '')}
      >
        copy
      </button>
      <pre className="ql-raw">{rawJson.value}</pre>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- RawJsonTab`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/QuickLook/RawJsonTab.tsx frontend/tests/unit/RawJsonTab.test.tsx
git commit -m "feat(ql): RawJsonTab lazy-loads pretty-printed JSON with copy + retry"
```

---

## Task 7: Frontend — `QuickLookHeader` component

**Files:**
- Create: `frontend/src/components/QuickLook/QuickLookHeader.tsx`
- Test: `frontend/tests/unit/QuickLookHeader.test.tsx` (new)

Header shows `schema.json` or `versions/v{N}` title, version badge (`v6 · active` / `v6 · frozen` / `v0 · draft`), `derived from: —` lineage placeholder, and close `✕` button.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/QuickLookHeader.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import QuickLookHeader from '../../src/components/QuickLook/QuickLookHeader'

describe('QuickLookHeader', () => {
  it('renders schema.json title with active badge when activeVersionId is set', () => {
    render(<QuickLookHeader target={{ kind: 'schema', pid: 'p_test' }} activeVersionId="v6" onClose={() => {}} />)
    expect(screen.getByText('schema.json')).toBeInTheDocument()
    expect(screen.getByText(/v6 · active/)).toBeInTheDocument()
  })

  it('renders v0 · draft when no active version', () => {
    render(<QuickLookHeader target={{ kind: 'schema', pid: 'p_test' }} activeVersionId={null} onClose={() => {}} />)
    expect(screen.getByText(/v0 · draft/)).toBeInTheDocument()
  })

  it('renders versions/v6 title with frozen badge for version target', () => {
    render(
      <QuickLookHeader
        target={{ kind: 'version', pid: 'p_test', versionId: 'v6' }}
        activeVersionId="v6"
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('versions/v6')).toBeInTheDocument()
    expect(screen.getByText(/v6 · frozen/)).toBeInTheDocument()
  })

  it('lineage row shows em-dash placeholder', () => {
    render(<QuickLookHeader target={{ kind: 'schema', pid: 'p_test' }} activeVersionId={null} onClose={() => {}} />)
    expect(screen.getByText(/derived from: —/)).toBeInTheDocument()
  })

  it('close button invokes onClose', async () => {
    const onClose = vi.fn()
    render(<QuickLookHeader target={{ kind: 'schema', pid: 'p_test' }} activeVersionId={null} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- QuickLookHeader`

Expected: FAIL with "Cannot find module".

- [ ] **Step 3: Implement `QuickLookHeader.tsx`**

Create `frontend/src/components/QuickLook/QuickLookHeader.tsx`:

```tsx
import type { QuickLookTarget } from '../../stores/quicklook'

interface Props {
  target: QuickLookTarget
  activeVersionId: string | null
  onClose: () => void
}

export default function QuickLookHeader({ target, activeVersionId, onClose }: Props) {
  const title = target.kind === 'schema' ? 'schema.json' : `versions/${target.versionId}`

  let badge: { text: string; tone: 'active' | 'frozen' | 'draft' }
  if (target.kind === 'version') {
    badge = { text: `${target.versionId} · frozen`, tone: 'frozen' }
  } else if (activeVersionId) {
    badge = { text: `${activeVersionId} · active`, tone: 'active' }
  } else {
    badge = { text: 'v0 · draft', tone: 'draft' }
  }

  return (
    <div className="ql-header">
      <div className="ql-header-row">
        <span className="ql-title">{title}</span>
        <span className={`ql-badge ql-badge--${badge.tone}`}>{badge.text}</span>
        <button type="button" className="ql-close" aria-label="close" onClick={onClose}>✕</button>
      </div>
      <div className="ql-lineage">derived from: —</div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- QuickLookHeader`

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/QuickLook/QuickLookHeader.tsx frontend/tests/unit/QuickLookHeader.test.tsx
git commit -m "feat(ql): QuickLookHeader with version badge + lineage placeholder"
```

---

## Task 8: Frontend — `SchemaQuickLook` wrapper (portal, scrim, esc, tabs)

**Files:**
- Create: `frontend/src/components/QuickLook/SchemaQuickLook.tsx`
- Test: `frontend/tests/unit/SchemaQuickLook.test.tsx` (new)

The portal wrapper composes Header + Tabs + FieldsTab/RawJsonTab + footer hint. Handles Esc keydown, scrim click, and project-switch auto-close.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/SchemaQuickLook.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SchemaQuickLook from '../../src/components/QuickLook/SchemaQuickLook'
import { useQuickLook } from '../../src/stores/quicklook'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'

describe('SchemaQuickLook', () => {
  beforeEach(() => {
    useQuickLook.getState().close()
    useProjects.setState({ selectedId: 'p_test', projects: [
      { project_id: 'p_test', name: 'us-invoice', active_version_id: 'v6' } as any,
    ] })
    useSchema.setState({ byProject: { p_test: [
      { name: 'invoice_number', type: 'string', description: 'the id', required: true } as any,
    ] } })
  })

  it('renders nothing when target is null', () => {
    const { container } = render(<SchemaQuickLook />)
    expect(container.firstChild).toBeNull()
  })

  it('opens with fields tab by default', () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    expect(screen.getByText('schema.json')).toBeInTheDocument()
    expect(screen.getByText('invoice_number')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /fields/i })).toHaveClass('ql-tab--active')
  })

  it('Esc key closes the sheet', async () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    await userEvent.keyboard('{Escape}')
    expect(useQuickLook.getState().target).toBeNull()
  })

  it('scrim click closes the sheet', async () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    await userEvent.click(screen.getByTestId('ql-scrim'))
    expect(useQuickLook.getState().target).toBeNull()
  })

  it('click on sheet body does not close', async () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    await userEvent.click(screen.getByText('schema.json'))
    expect(useQuickLook.getState().target).not.toBeNull()
  })

  it('switching project closes the sheet', () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    useProjects.setState({ selectedId: 'p_other' })
    expect(useQuickLook.getState().target).toBeNull()
  })

  it('tab click switches between fields and raw json', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('[]', { status: 200, headers: { 'content-type': 'text/plain' } }),
    )
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    await userEvent.click(screen.getByRole('button', { name: /raw json/i }))
    expect(screen.getByRole('button', { name: /raw json/i })).toHaveClass('ql-tab--active')
  })

  it('footer renders the description-vs-notes hint', () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    expect(screen.getByText(/description goes into the prompt/i)).toBeInTheDocument()
    expect(screen.getByText(/feed AutoResearch/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- SchemaQuickLook`

Expected: FAIL with "Cannot find module".

- [ ] **Step 3: Implement `SchemaQuickLook.tsx`**

Create `frontend/src/components/QuickLook/SchemaQuickLook.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuickLook } from '../../stores/quicklook'
import { useProjects } from '../../stores/projects'
import QuickLookHeader from './QuickLookHeader'
import FieldsTab from './FieldsTab'
import RawJsonTab from './RawJsonTab'
import './styles.css'

type Tab = 'fields' | 'raw'

export default function SchemaQuickLook() {
  const target = useQuickLook(s => s.target)
  const close = useQuickLook(s => s.close)
  const selectedId = useProjects(s => s.selectedId)
  const projects = useProjects(s => s.projects)
  const [tab, setTab] = useState<Tab>('fields')

  // Reset tab when a new target opens.
  useEffect(() => { setTab('fields') }, [target])

  // Esc to close.
  useEffect(() => {
    if (!target) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [target, close])

  // Auto-close on project switch (the open sheet would be about the previous project).
  useEffect(() => {
    if (target && target.pid !== selectedId) close()
  }, [selectedId, target, close])

  if (!target) return null

  const activeVersionId = projects.find(p => p.project_id === target.pid)?.active_version_id ?? null

  // FieldsTab needs to know whether to render the version path; the kind on target is the source.
  // We always mount the header + tabs; only the body switches.

  return createPortal(
    <div
      className="ql-scrim"
      data-testid="ql-scrim"
      onClick={e => { if (e.target === e.currentTarget) close() }}
    >
      <div className="ql-sheet" role="dialog" aria-modal="true">
        <QuickLookHeader target={target} activeVersionId={activeVersionId} onClose={close} />

        <div className="ql-tabs">
          <button
            type="button"
            className={`ql-tab${tab === 'fields' ? ' ql-tab--active' : ''}`}
            onClick={() => setTab('fields')}
          >
            fields
          </button>
          <button
            type="button"
            className={`ql-tab${tab === 'raw' ? ' ql-tab--active' : ''}`}
            onClick={() => setTab('raw')}
          >
            raw json
          </button>
        </div>

        <div className="ql-body">
          {tab === 'fields' ? <FieldsTab target={target} /> : <RawJsonTab />}
        </div>

        <div className="ql-footer">
          description goes into the prompt at publish time. review notes (per-doc) feed
          AutoResearch only — they propose description tweaks but never become prompt.
        </div>
      </div>
    </div>,
    document.body,
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- SchemaQuickLook`

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/QuickLook/SchemaQuickLook.tsx frontend/tests/unit/SchemaQuickLook.test.tsx
git commit -m "feat(ql): SchemaQuickLook portal with esc/scrim close + tab switch"
```

---

## Task 9: Wire ContextSurface entry points

**Files:**
- Modify: `frontend/src/components/Context/ContextSurface.tsx`
- Test: `frontend/tests/unit/ContextSurface-quicklook.test.tsx` (new)

Make the right-rail `schema.json` card title row and the `+ N more` line clickable. Both dispatch `useQuickLook.openSchema(pid)`. Add pointer cursor + subtle hover style.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/ContextSurface-quicklook.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ContextSurface from '../../src/components/Context/ContextSurface'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'
import { useQuickLook } from '../../src/stores/quicklook'

const TEN_FIELDS = Array.from({ length: 10 }, (_, i) => ({
  name: `f_${i}`,
  type: 'string' as const,
  description: '',
}))

describe('ContextSurface → QuickLook wiring', () => {
  beforeEach(() => {
    useProjects.setState({
      selectedId: 'p_test',
      projects: [{ project_id: 'p_test', name: 'x', active_version_id: 'v6' } as any],
    })
    useSchema.setState({ byProject: { p_test: TEN_FIELDS } })
    useQuickLook.getState().close()
  })

  it('clicking schema.json card title opens QuickLook', async () => {
    render(<ContextSurface />)
    await userEvent.click(screen.getByText('schema.json'))
    expect(useQuickLook.getState().target).toEqual({ kind: 'schema', pid: 'p_test' })
  })

  it('clicking "+ N more" row opens QuickLook', async () => {
    render(<ContextSurface />)
    await userEvent.click(screen.getByText(/\+ 3 more/))
    expect(useQuickLook.getState().target).toEqual({ kind: 'schema', pid: 'p_test' })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ContextSurface-quicklook`

Expected: FAIL (clicks don't dispatch yet).

- [ ] **Step 3: Modify `ContextSurface.tsx`**

In `frontend/src/components/Context/ContextSurface.tsx`:

a. Add import near the top of the file (next to other store imports):

```typescript
import { useQuickLook } from '../../stores/quicklook'
```

b. Inside the component body, after the existing `useReview` line:

```typescript
const openQuickLook = useQuickLook(s => s.openSchema)
```

c. Make the schema header clickable. Replace the existing block:

```tsx
<div className="ctx-h">
  <span>schema.json</span>
  <span className="small">{schemaHint}</span>
</div>
```

with:

```tsx
<div
  className="ctx-h"
  onClick={() => openQuickLook(pid)}
  role="button"
  tabIndex={0}
  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') openQuickLook(pid) }}
  style={{ cursor: 'pointer' }}
>
  <span>schema.json</span>
  <span className="small">{schemaHint}</span>
</div>
```

d. Make the `+ N more` row clickable. Replace:

```tsx
{fields.length > MAX_VISIBLE_FIELDS && (
  <div className="schemaRow" style={{ color: 'var(--ink-5)', fontStyle: 'italic' }}>
    + {fields.length - MAX_VISIBLE_FIELDS} more
  </div>
)}
```

with:

```tsx
{fields.length > MAX_VISIBLE_FIELDS && (
  <div
    className="schemaRow"
    onClick={() => openQuickLook(pid)}
    role="button"
    tabIndex={0}
    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') openQuickLook(pid) }}
    style={{ color: 'var(--ink-5)', fontStyle: 'italic', cursor: 'pointer' }}
  >
    + {fields.length - MAX_VISIBLE_FIELDS} more
  </div>
)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- ContextSurface-quicklook`

Expected: 2 passed.

Also run the existing ContextSurface test to confirm no regression:

Run: `cd frontend && npm test -- ContextSurface`

Expected: all existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Context/ContextSurface.tsx frontend/tests/unit/ContextSurface-quicklook.test.tsx
git commit -m "feat(ql): ContextSurface schema card title + '+N more' dispatch openSchema"
```

---

## Task 10: Wire FSSpine entry points

**Files:**
- Modify: `frontend/src/components/Spine/FSSpine.tsx`
- Test: `frontend/tests/unit/FSSpine-quicklook.test.tsx` (new)

Make `schema.json` and `versions/v{N}` rows clickable. Other FSSpine rows untouched.

First, read the existing FSSpine to learn how the rows are rendered (the test will need to target the same DOM the implementation produces):

```bash
sed -n '1,200p' frontend/src/components/Spine/FSSpine.tsx
```

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/FSSpine-quicklook.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FSSpine from '../../src/components/Spine/FSSpine'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'
import { useQuickLook } from '../../src/stores/quicklook'

describe('FSSpine → QuickLook wiring', () => {
  beforeEach(() => {
    useProjects.setState({
      selectedId: 'p_test',
      projects: [{ project_id: 'p_test', name: 'us-invoice', active_version_id: 'v6' } as any],
    })
    useSchema.setState({ byProject: { p_test: [{ name: 'x', type: 'string', description: '' } as any] } })
    useQuickLook.getState().close()
  })

  it('clicking schema.json row opens schema QuickLook', async () => {
    render(<FSSpine />)
    await userEvent.click(screen.getByText('schema.json'))
    expect(useQuickLook.getState().target).toEqual({ kind: 'schema', pid: 'p_test' })
  })

  it('clicking a versions/vN leaf opens version QuickLook', async () => {
    render(<FSSpine />)
    // Find the 'v6' row inside the versions/ group
    const v6 = screen.getByText('v6')
    await userEvent.click(v6)
    expect(useQuickLook.getState().target).toEqual({ kind: 'version', pid: 'p_test', versionId: 'v6' })
  })

  it('clicking docs/ folder header does not open QuickLook', async () => {
    render(<FSSpine />)
    const docsRow = screen.queryByText('docs/')
    if (docsRow) await userEvent.click(docsRow)
    expect(useQuickLook.getState().target).toBeNull()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- FSSpine-quicklook`

Expected: FAIL — clicks don't dispatch yet, or DOM nodes don't carry the click handler.

- [ ] **Step 3: Modify `FSSpine.tsx`**

a. Add import:

```typescript
import { useQuickLook } from '../../stores/quicklook'
```

b. In the component body (near the top), grab both actions:

```typescript
const openSchema = useQuickLook(s => s.openSchema)
const openVersion = useQuickLook(s => s.openVersion)
```

c. Locate the row that renders `schema.json` (search the existing source for `'schema.json'` literal). Wrap its outer element so that on click it dispatches `openSchema(selectedId)`. Add `style={{ cursor: 'pointer' }}` and `role="button"` + `tabIndex={0}` + `onKeyDown` parity with the existing pattern in `ContextSurface`.

d. Locate the rows that render version leaves (the inner expansion of `versions/`; search for `version` / `v${n}` / the `frozen` label). For each version leaf row, add a click handler that calls `openVersion(selectedId, versionId)` where `versionId = "v" + n` (or read the existing variable name).

If the existing `FSSpine.tsx` does not currently render version leaves as separate DOM nodes (i.e. they are inside a single string), refactor that block to emit one `<div>` per version leaf so the click target is per-version. Keep the visual unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- FSSpine`

Expected: all FSSpine tests pass (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Spine/FSSpine.tsx frontend/tests/unit/FSSpine-quicklook.test.tsx
git commit -m "feat(ql): FSSpine schema.json + versions/vN rows dispatch openSchema/openVersion"
```

---

## Task 11: Mount `<SchemaQuickLook />` in `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx`

The component must be mounted once at the app root so its portal is always available regardless of which view is active.

- [ ] **Step 1: Read current App.tsx**

```bash
sed -n '1,60p' frontend/src/App.tsx
```

- [ ] **Step 2: Add the import and the mount**

Near the other component imports:

```typescript
import SchemaQuickLook from './components/QuickLook/SchemaQuickLook'
```

Inside the top-level rendered JSX (typically a `<>` fragment that wraps `<AppShell>` or similar), append `<SchemaQuickLook />` as a sibling — it renders `null` when no target is open, so position doesn't matter for layout:

```tsx
<>
  {/* … existing shell … */}
  <SchemaQuickLook />
</>
```

- [ ] **Step 3: Manual smoke**

Start the dev server:

```bash
cd backend && uv run uvicorn app.main:app --reload --port 8001 &
cd frontend && npm run dev
```

In the browser:
1. Open `us-invoice` project.
2. Click `schema.json` in the right-rail ContextSurface header → sheet opens with 8 field cards.
3. Switch to `raw json` tab → JSON renders, `copy` button works.
4. Press `Esc` → sheet closes.
5. Click `versions/v6` leaf in the left FSSpine → sheet opens, header shows `versions/v6` with `v6 · frozen` badge.
6. Click outside the sheet (scrim) → closes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(ql): mount <SchemaQuickLook /> at app root"
```

---

## Task 12: End-to-end Playwright test

**Files:**
- Create: `frontend/tests/e2e/schema-quicklook.spec.ts`

Mirror the manual smoke as an automated scenario against a seeded project.

- [ ] **Step 1: Read an existing e2e to learn the seed/setup pattern**

```bash
sed -n '1,80p' frontend/tests/e2e/walking-skeleton.spec.ts
sed -n '1,80p' frontend/tests/e2e/review-mode.spec.ts
```

The seed pattern (e.g. how a project is created, how `EMERGE_TEST_MODE=1` is set, where the workspace is rooted) will inform what setup the spec needs. Match the existing convention.

- [ ] **Step 2: Write the e2e spec**

Create `frontend/tests/e2e/schema-quicklook.spec.ts`:

```typescript
import { test, expect } from '@playwright/test'

// Adjust the seeding strategy to match what other e2e specs do — typically each
// spec creates its own project via the API or relies on a fixture that ensures
// a us-invoice-like project exists. The smoke below assumes a project exists
// with name 'us-invoice' and at least 2 schema fields (matching the dev fixture).

test('quick-look opens from ContextSurface and FSSpine', async ({ page }) => {
  await page.goto('/')
  await page.getByText('us-invoice').first().click()

  // Wait for ContextSurface to render the schema card.
  await expect(page.getByText('schema.json').first()).toBeVisible()

  // Entry 1: click ContextSurface header.
  await page.getByText('schema.json').first().click()
  await expect(page.locator('.ql-sheet')).toBeVisible()
  await expect(page.locator('.ql-field-name').first()).toBeVisible()

  // Switch to raw json tab.
  await page.getByRole('button', { name: 'raw json' }).click()
  await expect(page.locator('.ql-raw')).toBeVisible()

  // Close with Esc.
  await page.keyboard.press('Escape')
  await expect(page.locator('.ql-sheet')).not.toBeVisible()

  // Entry 2: open from FSSpine versions/v6 (skip if no published version).
  const v6 = page.getByText('v6').first()
  if (await v6.isVisible()) {
    await v6.click()
    await expect(page.locator('.ql-sheet')).toBeVisible()
    await expect(page.getByText('versions/v6')).toBeVisible()
    await expect(page.getByText(/v6 · frozen/)).toBeVisible()
    // Close with scrim click.
    await page.locator('[data-testid="ql-scrim"]').click({ position: { x: 10, y: 10 } })
    await expect(page.locator('.ql-sheet')).not.toBeVisible()
  }
})
```

If the existing e2es follow a stricter seeding pattern (a `test.beforeEach` that creates a fresh project via `POST /lab/projects` and uploads fixtures), adopt that pattern here too — do not assume the dev fixture is present in CI.

- [ ] **Step 3: Run the e2e**

```bash
cd frontend && npm run e2e -- schema-quicklook
```

Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/e2e/schema-quicklook.spec.ts
git commit -m "test(ql): e2e spec for QuickLook from ContextSurface and FSSpine"
```

---

## Task 13: Live verify + ROADMAP closeout

**Files:**
- Modify: `docs/superpowers/plans/ROADMAP.md` (flip M9.0 row + add commit range)
- Modify: `docs/design-decisions.md` (append a ✅ entry per the project's design-decisions cadence)

- [ ] **Step 1: Live verify on real workspace**

Start backend pointing at the real workspace (not a fresh tmp):

```bash
cd backend && uv run uvicorn app.main:app --reload --port 8001
```

In another shell, start the frontend:

```bash
cd frontend && npm run dev
```

Open `us-invoice` in the browser. Verify all three entry points open the sheet, fields tab shows all 8 fields with descriptions, raw json tab shows the actual `schema.json` content, copy button puts JSON on clipboard, Esc / scrim / ✕ all close it, and `versions/v6` opens the frozen version with a different badge.

Take a screenshot of the sheet open with us-invoice's schema and save to `docs/design/emerge-api/screenshots/quicklook-schema.png` (or wherever the project keeps verify screenshots — match existing convention).

- [ ] **Step 2: Run the full test suite (smoke for regression)**

```bash
cd backend && uv run pytest -v
```

Expected: all green, including the 6 new tests in `test_schema_raw_endpoints.py`.

```bash
cd frontend && npm test
```

Expected: all green, including the 5 new unit-test files.

- [ ] **Step 3: Update ROADMAP**

In `docs/superpowers/plans/ROADMAP.md`, flip the M9.0 row from `🔮 proposed` to `✅ shipped` and fill the range column. Then add a "M9.0 — schema quick-look" subsection under "What each milestone delivers" mirroring the format used by M8 / M7.2 (Goal / Scope / Decisions affirmed).

Sample row update:

```markdown
| **M9.0** — schema quick-look (read-only sheet from FSSpine + ContextSurface) | `2026-05-12-m9-0-schema-quicklook.md` | ✅ shipped | <range from git log> (13 task commits) |
```

Sample subsection (insert before the "Open cross-cutting follow-ups" heading):

```markdown
### M9.0 — schema quick-look

**Goal:** clickable read-only Quick-look sheet for `schema.json` and `versions/v{N}.json` from FSSpine and ContextSurface entry points; field cards + raw JSON + copy button; reserved lineage row and per-field notes-hint slot for forward-compat with M9a/M9b/M9d.

**Scope (see `2026-05-12-m9-0-schema-quicklook.md`):**
- T1-T2: backend — `GET /lab/projects/{pid}/schema/raw` (pretty-printed text/plain) and `GET /lab/projects/{pid}/versions/{vid}/raw[?shape=fields]`.
- T3: `useQuickLook` Zustand store with lazy `loadRaw()`.
- T4-T7: `FieldCard` (recursive, examples/enum/required pill/notes-slot), `FieldsTab`, `RawJsonTab`, `QuickLookHeader` (active/frozen/draft badge + lineage placeholder).
- T8: `SchemaQuickLook` portal wrapper — esc / scrim / ✕ close, project-switch auto-close, tab switch.
- T9-T10: entry-point wiring in `ContextSurface` (card title + `+ N more`) and `FSSpine` (`schema.json` + `versions/v{N}` leaves).
- T11: mounted at `App.tsx` root.
- T12: e2e covers both entry surfaces and the two close affordances.

**Decisions affirmed / out of scope:** no edit affordance in the sheet (hard rule); raw-json `copy` is read-out, not mutation; no version diff; no schema fork / picker (M9a-c); drift detection (`schema.json` ≠ active version hash) folds into M9a.
```

- [ ] **Step 4: Design-decisions entry**

In `docs/design-decisions.md`, append a ✅ entry dated `2026-05-12` resolving the "right rail schema preview truncated, no way to see full schema" papercut and pointing at this milestone. Match the entry style of M8's closeout entry (look at the latest entries for format).

- [ ] **Step 5: Commit closeout**

```bash
git add docs/superpowers/plans/ROADMAP.md docs/design-decisions.md docs/design/emerge-api/screenshots/quicklook-schema.png
git commit -m "docs(m9.0): flip ROADMAP to shipped + design-decisions ✅ entry"
```

---

## Self-Review (recorded for the implementer)

Run this checklist after Task 13 against the spec (`docs/superpowers/specs/2026-05-12-schema-quicklook-design.md`):

**Spec coverage:**
- G1 (one-click full schema from FSSpine or ContextSurface) — covered by T9, T10, T11.
- G2 (inspect frozen `versions/v{N}.json`) — covered by T10 (entry) + T2 (backend) + T5 (FieldsTab version branch) + T6 (RawJsonTab).
- G3 (field-level + raw-JSON in same flow) — T4 / T5 / T6 / T8.
- G4 (description vs review-notes hint) — T8 footer.
- G5 (schema-shaped: schemaId / lineage row / notes-slot) — T4 (notes slot), T7 (lineage row).

**Hard rule check:**
- No edit affordance anywhere in the sheet (T4/T5/T6/T7/T8 verified). ✅
- `copy` is read-out, not mutation. ✅
- No version diff, no fork, no multi-schema picker. ✅
- AutoResearch / counterexample hard rules untouched. ✅

**Naming consistency check:**
- Store: `useQuickLook`, `openSchema`, `openVersion`, `close`, `loadRaw`, `target`, `rawJson` — used identically across T3-T11. ✅
- CSS class prefix: `ql-` — used identically across styles.css and component files. ✅
- Component names: `SchemaQuickLook`, `QuickLookHeader`, `FieldCard`, `FieldsTab`, `RawJsonTab` — used identically across imports. ✅
- Endpoint paths: `/lab/projects/{pid}/schema/raw`, `/lab/projects/{pid}/versions/{vid}/raw` — used identically in backend (T1-T2), store (T3), version branch (T5). ✅
- `data-testid="ql-scrim"` used identically in T8 implementation and T8/T12 tests. ✅
- `data-testid="field-notes-hint"` used identically in T4 implementation and T4 test. ✅
