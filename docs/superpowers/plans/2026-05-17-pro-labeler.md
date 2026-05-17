# M10 — Pro Labeler (Pro 老员工预标 → Boss 复核 → Flash 训练)

> **For agentic workers:** execute task-by-task. Each task is self-contained
> (files + code sketch + test command + commit message). Run the test step at
> the end of every task; commit only when green. Stop and report on repeated
> failures.

**Goal:** unblock `/improve` training by inserting a stronger LLM (Pro labeler,
e.g. `gemini-pro-latest`) that produces draft `reviewed/_pending/{filename}.json`
files for the human boss to verify. On save, the pending file is atomically
deleted and the conventional `reviewed/{filename}.json` is the only ground
truth — so `score()`, `/improve`, `/publish`, and `readiness_check` stay
unchanged (they glob `reviewed/*.json`; the `_pending/` subdir is naturally
excluded by `glob`).

**Three model roles, mapped to existing project slots:**

| Role | Disk slot | Existing? |
|---|---|---|
| Flash worker (prod extraction) | `extract_model` (active model) | yes |
| Pro labeler (draft labeling) | NEW `labeler_model` on `project.json` | no |
| Coach (runs `/improve`) | Claude SDK agent | yes |

**Architecture:** thin layer on top of existing extract path. New
`pre_label(slug, filenames?, labeler_model?)` tool reuses `extract_one`'s
prompt builder + response_schema + provider dispatch — only the destination
path differs (`reviewed/_pending/{filename}.json` instead of
`predictions/_draft/{filename}.json`). `save_reviewed` is extended to atomically
delete the matching pending file. A banner is added to ReviewOverlay surfacing
"Pro-labeled by {model}".

**Tech stack:** FastAPI + pydantic v2 + `claude_agent_sdk` (backend); React 19 +
TypeScript + Zustand + Vite (frontend). Backend test command:
`cd backend && uv run pytest <path> -v`. Frontend test command:
`cd frontend && npm test -- <pattern>`.

**Reference docs:**
- Blueprint plan-mode draft: `/Users/qinqiang02/.claude/plans/peppy-strolling-marshmallow.md`
- Predecessor: M9.3 (experiments axis), M9.5 (paste-attachments)
- INSIGHTS to respect: #4 (Gemini `additionalProperties`), #8 (`safe_slug`), #9 (frontend cross-store refresh)
- CLAUDE.md hard rules — `reviewed/` human-write-only, atomic writes, no AutoResearch auto-promote, task-type-agnostic chrome

**Scope boundary — explicitly OUT of scope:**
- Per-field uncertainty highlighting (`_uncertain_fields`) and "boss must confirm" UI — v1.5
- Self-consistency double-run for disagreement triage
- New slash command `/pro-label` — agent-driven NL only
- Doc-list pre-labeled vs. flash-draft visual differentiation (banner only)
- Pro labeler as cross-model disagree triage in `/improve`

---

## File map

**New files (backend):**
- `backend/app/tools/pre_label.py` — `pre_label` + `set_labeler_model` + `get_pending`
- `backend/app/api/routes/pre_label.py` — `POST .../pre_label`, `POST .../labeler_model`
- `backend/tests/unit/test_pre_label.py`
- `backend/tests/unit/test_set_labeler_model.py`
- `backend/tests/unit/test_reviewed_pending_cleanup.py`
- `backend/tests/unit/test_routes_pre_label.py` (combined route tests)

**Modified files (backend):**
- `backend/app/workspace/paths.py` — `pending_reviewed_dir`, `pending_reviewed_path`
- `backend/app/config.py` — `default_labeler_model` setting
- `backend/app/tools/projects.py` — `create_project` adds `labeler_model` to blob
- `backend/app/tools/reviewed.py` — `save_reviewed` cleans pending; add `get_pending`
- `backend/app/tools/__init__.py` — register 3 new MCP tools + `_EMERGE_TOOL_NAMES`
- `backend/app/api/routes/reviewed.py` — `GET .../pending/{filename}`
- `backend/app/main.py` — mount pre_label router
- `backend/app/tools/surface_state.py` — `has_pending` field on review state
- `backend/app/skills/emerge_extractor.md` — intent-hint section for Pro Labeler

**New files (frontend):**
- `frontend/src/components/ReviewMode/PreLabelNotice.tsx`

**Modified files (frontend):**
- `frontend/src/types/review.ts` — `PendingPayload` type
- `frontend/src/lib/api.ts` — `getPending` fetch helper
- `frontend/src/stores/review.ts` — `open()` fallback to pending; `isPending`/`labelerModel` state
- `frontend/src/stores/chat.ts` — cross-store invalidate on `mcp__emerge_tools__pre_label`
- `frontend/src/components/ReviewMode/ReviewOverlay.tsx` — render banner between `ReviewBar` and `rev-body`

---

## Task 1 — Backend disk layout + config

**Files:**
- Modify: `backend/app/workspace/paths.py` (+ 2 helpers)
- Modify: `backend/app/config.py` (+ default_labeler_model)

**Steps:**

Append to `paths.py` (just after `reviewed_path`):

```python
def pending_reviewed_dir(workspace: Path, slug: str) -> Path:
    """Pro-labeler draft drop zone. Glob-invisible to `reviewed/*.json` —
    `score()` / `/improve` / `/publish` / `readiness_check` never see these
    files. Promotion to `reviewed/` happens in `save_reviewed` after the boss
    saves their corrections."""
    return reviewed_dir(workspace, slug) / "_pending"


def pending_reviewed_path(workspace: Path, slug: str, filename: str) -> Path:
    return pending_reviewed_dir(workspace, slug) / f"{filename}.json"
```

Append to `Settings` in `config.py`:

```python
default_labeler_model: str | None = None
```

(env var: `EMERGE_DEFAULT_LABELER_MODEL`.)

**Test command:** none yet (covered indirectly by Task 2).

**Commit message:** `feat(m10): add pending-reviewed paths + default_labeler_model setting`

---

## Task 2 — `labeler_model` in `project.json` defaults

**Files:**
- Modify: `backend/app/tools/projects.py:192–205`
- Modify: `backend/tests/unit/test_tool_projects.py` (one new assert)

**Steps:**

In `create_project`, blob construction (line ~192):

```python
blob = {
    # ... existing fields ...
    "extract_model": settings.default_extract_model,
    "extract_params": {"temperature": 0.0},
    "labeler_model": settings.default_labeler_model,  # NEW; may be None
    "published_ids": [],
}
```

Test addition:

```python
async def test_create_project_includes_labeler_model_slot(workspace: Path) -> None:
    out = await create_project(workspace, name="x")
    blob = json.loads((workspace / out["slug"] / "project.json").read_text())
    assert "labeler_model" in blob
    assert blob["labeler_model"] is None  # default unset
```

**Test:** `cd backend && uv run pytest tests/unit/test_tool_projects.py -v`

**Commit message:** `feat(m10): seed labeler_model slot in project.json`

---

## Task 3 — `pre_label` tool implementation

**Files:**
- New: `backend/app/tools/pre_label.py`
- New: `backend/tests/unit/test_pre_label.py`

**Code sketch (pre_label.py):**

```python
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.provider import get_provider_for_model
from app.provider.base import ContentBlock, Provider, TextBlock
from app.schemas.extraction import ExtractionOutput
from app.tools.extract import _EXTRACT_SYSTEM, _build_field_instructions, _build_response_schema
from app.tools.schema import _doc_to_block, read_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import (
    pending_reviewed_dir,
    pending_reviewed_path,
    project_json_path,
    reviewed_path,
)


class LabelerNotConfiguredError(ValueError):
    """Neither call-arg, project.json.labeler_model, nor env default is set."""


async def _resolve_labeler_model(
    workspace: Path, slug: str, override: str | None,
) -> str:
    if override:
        return override
    import json as _json
    pj = project_json_path(workspace, slug)
    if pj.exists():
        blob = _json.loads(pj.read_text())
        if blob.get("labeler_model"):
            return blob["labeler_model"]
    settings = get_settings()
    if settings.default_labeler_model:
        return settings.default_labeler_model
    raise LabelerNotConfiguredError("labeler_model not configured")


async def pre_label(
    workspace: Path,
    slug: str,
    *,
    filenames: list[str] | None = None,
    labeler_model: str | None = None,
    provider: Provider | None = None,
) -> dict[str, Any]:
    """Pro-labeler batch draft. Writes reviewed/_pending/{filename}.json per
    doc. Skips docs that already have reviewed/. Overwrites existing pending
    (re-run with a different labeler model allowed)."""
    await migrate_project_if_needed(workspace, slug)
    schema = await read_schema(workspace, slug)
    if not schema:
        raise ValueError("project has empty schema; nothing to pre-label")

    mid = await _resolve_labeler_model(workspace, slug, labeler_model)
    if provider is None:
        provider = get_provider_for_model(mid)

    if not filenames:
        # default: all docs without reviewed/
        from app.tools.docs import list_docs
        all_docs = await list_docs(workspace, slug)
        filenames = [d["filename"] for d in all_docs]

    processed: list[str] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    response_schema = _build_response_schema(schema)
    field_instructions = _build_field_instructions(schema)

    for fn in filenames:
        if reviewed_path(workspace, slug, fn).exists():
            skipped.append({"filename": fn, "reason": "already_reviewed"})
            continue
        try:
            user_blocks: list[ContentBlock] = [
                TextBlock(text=field_instructions),
                await _doc_to_block(workspace, slug, fn),
            ]
            result = await provider.extract(
                model_id=mid,
                system_prompt=_EXTRACT_SYSTEM,
                user_content=user_blocks,
                response_schema=response_schema,
            )
            output = ExtractionOutput(**result.raw_json)
            payload = output.model_dump(by_alias=True, exclude_none=True)
            payload["labeler_model"] = mid
            payload["created_at"] = datetime.now(timezone.utc).isoformat()
            async with project_lock(workspace, slug):
                pending_reviewed_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
                atomic_write_json(pending_reviewed_path(workspace, slug, fn), payload)
            processed.append(fn)
        except Exception as e:  # noqa: BLE001
            errors.append({
                "filename": fn,
                "error_code": "pre_label_failed",
                "error_message_en": str(e),
            })

    return {
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "labeler_model": mid,
    }


async def get_pending(
    workspace: Path, slug: str, filename: str,
) -> dict[str, Any] | None:
    p = pending_reviewed_path(workspace, slug, filename)
    if not p.exists():
        return None
    import json as _json
    return _json.loads(p.read_text())


async def set_labeler_model(
    workspace: Path, slug: str, model_id: str,
) -> None:
    import json as _json
    async with project_lock(workspace, slug):
        pj = project_json_path(workspace, slug)
        blob = _json.loads(pj.read_text())
        blob["labeler_model"] = model_id
        atomic_write_json(pj, blob)
```

**Test sketch:** mock `Provider`, seed schema + 2 docs, call `pre_label`. Verify:
- Success path writes `reviewed/_pending/{filename}.json` with `labeler_model`+`created_at`
- Already-reviewed doc is skipped
- Overwrite of existing pending allowed
- Labeler resolution priority: arg > project.json > env > raise
- Filenames=None defaults to all docs

**Test command:** `cd backend && uv run pytest tests/unit/test_pre_label.py -v`

**Commit message:** `feat(m10): add pre_label tool + labeler resolution`

---

## Task 4 — `save_reviewed` cleans pending; `get_pending`

**Files:**
- Modify: `backend/app/tools/reviewed.py`
- New: `backend/tests/unit/test_reviewed_pending_cleanup.py`

**Steps:**

End of `save_reviewed`, inside the `async with project_lock(...)` block, after `atomic_write_json`:

```python
# Pro-labeler draft becomes obsolete the moment human-verified ground truth
# is written. Atomic delete is safe inside project_lock.
pending = pending_reviewed_path(workspace, project_id, filename)
if pending.exists():
    try:
        pending.unlink()
    except FileNotFoundError:
        pass
```

Add import: `from app.workspace.paths import ..., pending_reviewed_path`.

Test sketch:
- `_stage_pending` writes `_pending/x.pdf.json` with `{labeler_model, entities}`
- Call `save_reviewed(...)` for same filename
- Assert: `reviewed/x.pdf.json` exists, `_pending/x.pdf.json` gone
- Save without pending file present: no error.

**Test command:** `cd backend && uv run pytest tests/unit/test_reviewed_pending_cleanup.py -v`

**Commit message:** `feat(m10): save_reviewed atomically deletes matching pending`

---

## Task 5 — MCP tool registration

**Files:**
- Modify: `backend/app/tools/__init__.py` — register `pre_label`, `get_pending`, `set_labeler_model`

**Steps:**

Add module import: `from app.tools import pre_label as pre_label_mod`.

Append three `@tool` decorated functions after `t_promote_attachment_to_docs`:

```python
@tool(
    "pre_label",
    "Pro-labeler batch draft. Calls the project's `labeler_model` (a stronger "
    "LLM, e.g. `gemini-pro-latest`) on each filename and writes a draft to "
    "`reviewed/_pending/{filename}.json` for the human boss to verify in "
    "Review mode. Skips docs that already have `reviewed/` (human-verified). "
    "Overwrites existing pending (re-run with a different model allowed). "
    "Pass `filenames=[]` (or omit) to label all unreviewed docs. Single call "
    "should cover ≤10 filenames — batch larger sets across multiple calls so "
    "chat feedback stays responsive. Returns "
    "`{processed, skipped, errors, labeler_model}`.",
    {"slug": str, "filenames": list, "labeler_model": str},
)
async def t_pre_label(args: dict[str, Any]) -> dict[str, Any]:
    out = await pre_label_mod.pre_label(
        workspace, args["slug"],
        filenames=args.get("filenames") or None,
        labeler_model=args.get("labeler_model") or None,
    )
    return {"content": [{"type": "text", "text": _json.dumps(out)}]}


@tool(
    "get_pending",
    "Get the pro-labeled pending draft for one doc or null if none exists. "
    "Distinct from `get_reviewed` (human-verified) — pending is awaiting "
    "human boss review.",
    {"slug": str, "filename": str},
)
async def t_get_pending(args: dict[str, Any]) -> dict[str, Any]:
    payload = await pre_label_mod.get_pending(
        workspace, args["slug"], args["filename"],
    )
    text = _json.dumps(payload) if isinstance(payload, dict) else "null"
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "set_labeler_model",
    "Update `project.json.labeler_model` — the model `pre_label` uses by "
    "default when no override is passed. Use when the user says \"换 pro 模型\" "
    "or \"用 X 当 pro\". No risk gate; the change is recoverable.",
    {"slug": str, "model_id": str},
)
async def t_set_labeler_model(args: dict[str, Any]) -> dict[str, Any]:
    await pre_label_mod.set_labeler_model(
        workspace, args["slug"], args["model_id"],
    )
    return {"content": [{"type": "text", "text": "ok"}]}
```

Add to tool list line ~833 and `_EMERGE_TOOL_NAMES` line ~890.

**Test sketch:** extend `tests/unit/test_tool_registration.py` (or wherever the registration assertion lives) to include the 3 new names.

**Test command:** `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`

**Commit message:** `feat(m10): register pre_label, get_pending, set_labeler_model MCP tools`

---

## Task 6 — HTTP route symmetry

**Files:**
- New: `backend/app/api/routes/pre_label.py`
- Modify: `backend/app/api/routes/reviewed.py` (+ `GET .../pending/{filename}`)
- Modify: `backend/app/main.py` (mount router)
- New: `backend/tests/unit/test_routes_pre_label.py`

**Code sketch (pre_label.py route):**

```python
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.routes._safety import safe_slug
from app.config import get_settings
from app.tools.pre_label import (
    LabelerNotConfiguredError,
    pre_label,
    set_labeler_model,
)
from app.workspace.paths import project_json_path


router = APIRouter()


def _project_or_404(slug: str) -> Path:
    safe_slug(slug)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, slug).exists():
        raise HTTPException(
            status_code=404, detail={"error_code": "project_not_found"},
        )
    return settings.workspace_root


class _PreLabelBody(BaseModel):
    filenames: Optional[list[str]] = None
    labeler_model: Optional[str] = None


@router.post("/lab/projects/{slug}/pre_label")
async def post_pre_label(slug: str, body: _PreLabelBody) -> dict:
    workspace = _project_or_404(slug)
    try:
        return await pre_label(
            workspace, slug,
            filenames=body.filenames,
            labeler_model=body.labeler_model,
        )
    except LabelerNotConfiguredError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "labeler_model_not_configured",
                "error_message_en": str(e),
            },
        )


class _LabelerModelBody(BaseModel):
    model_id: str


@router.post("/lab/projects/{slug}/labeler_model")
async def post_labeler_model(slug: str, body: _LabelerModelBody) -> dict:
    workspace = _project_or_404(slug)
    await set_labeler_model(workspace, slug, body.model_id)
    return {"ok": True}
```

In `reviewed.py` route, add:

```python
from app.tools.pre_label import get_pending


@router.get("/lab/projects/{slug}/pending/{filename:path}")
async def get_doc_pending(slug: str, filename: str) -> dict:
    safe_slug(slug)
    safe_filename(filename)
    settings = get_settings()
    payload = await get_pending(settings.workspace_root, slug, filename)
    if payload is None:
        raise HTTPException(status_code=404, detail="pending_not_found")
    return payload
```

In `main.py`, mount the new router alongside `reviewed_route`:

```python
from app.api.routes import pre_label as pre_label_route
...
app.include_router(pre_label_route.router)
```

**Test sketch:** use the FastAPI test client. Cover:
- POST .../pre_label returns 400 + error_code `labeler_model_not_configured` when no model
- GET .../pending/{filename} returns 404 when no pending file
- POST .../labeler_model persists `labeler_model` into project.json

(For the actual `pre_label` success path, stub the provider via `monkeypatch`.)

**Test command:** `cd backend && uv run pytest tests/unit/test_routes_pre_label.py -v`

**Commit message:** `feat(m10): http routes for pre_label, labeler_model, pending`

---

## Task 7 — `surface_state.has_pending`

**Files:**
- Modify: `backend/app/tools/surface_state.py` (~line 55–150)
- Modify: `backend/tests/unit/test_chat_review_context.py` or add a small assertion test

**Steps:**

Inside `_review_state`, before `return {...}`:

```python
from app.workspace.paths import pending_reviewed_path
has_pending = pending_reviewed_path(workspace, slug, filename).exists()
```

Add `"has_pending": has_pending` to the return dict (alongside `has_prediction`, `has_reviewed`). **Do not** change `review_status` enum values — UI uses the new flag separately.

Test sketch (smaller, can go into `test_chat_review_context.py` or new
`test_surface_state_pending.py`):

```python
async def test_surface_state_has_pending(workspace, monkeypatch) -> None:
    # seed project + doc + write a fake _pending/ file
    slug = ...
    fn = ...
    pending_reviewed_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    (pending_reviewed_path(workspace, slug, fn)).write_text('{"entities":[]}')
    out = await get_surface_state(workspace, surface="review", slug=slug, filename=fn)
    assert out["has_pending"] is True
    assert out["review_status"] in ("unprocessed", "pending")  # enum unchanged
```

**Test command:** `cd backend && uv run pytest tests/unit/test_chat_review_context.py -v` (or the new file)

**Commit message:** `feat(m10): surface_state exposes has_pending`

---

## Task 8 — Skill markdown intent hint

**Files:**
- Modify: `backend/app/skills/emerge_extractor.md`

Append a new section "## Pro labeler (pre-label)" after "## Experiment axis":

> ### Pro labeler (pre-label)
>
> A stronger, slower model (the "pro old-timer") can draft labels for the
> boss to verify. Use this when the user says "pro 先标一版" / "用大模型预标
> 这批" / "stand by N张" / "labeler 跑一遍". You call `pre_label(slug,
> filenames?, labeler_model?)` — it writes `reviewed/_pending/{filename}.json`
> per doc; boss verifies and saves in Review mode; `save_reviewed` atomically
> deletes the matching pending file.
>
> Workflow:
> 1. `pre_label(slug, filenames=[fn1, fn2, ...])` — single call should cover
>    ≤10 filenames; for larger batches, split across multiple calls so chat
>    feedback streams smoothly. Returns `{processed, skipped, errors,
>    labeler_model}`. Skipped docs are ones that already have `reviewed/`.
> 2. The user opens Review mode → top banner shows "Pro-labeled by {model} ·
>    please verify" — boss confirms / edits / saves.
> 3. If the user says "换 pro 模型" / "用 X 当 pro", call `set_labeler_model(slug,
>    model_id)`.
>
> Hard rule: `pre_label` is NOT a substitute for `extract` — its output goes
> into `reviewed/_pending/`, never `predictions/_draft/`, never `reviewed/`
> (those are agent-restricted human-write zones). Don't use it when the user
> wants flash extraction or A/B with an experiment.

Also append a bullet under "## Risk gates":

> - `pre_label` (Pro labeler): no confirm needed when the user explicitly asks
>   for pre-labeling. But for batches > 30, ask first — "用 pro 标 N 张大约要
>   花 X 分钟，确定吗？"

**Test:** none (markdown content).

**Commit message:** `docs(m10): emerge-extractor skill — pro labeler intent hints`

---

## Task 9 — Backend full suite green

After all backend tasks, run:

```bash
cd backend && uv run pytest -v
```

Must be green. Fix any regressions before moving to frontend.

**Commit message:** none (verification step, not a code change).

---

## Task 10 — Frontend types + API helper

**Files:**
- Modify: `frontend/src/types/review.ts`
- Modify: `frontend/src/lib/api.ts`

Append to `types/review.ts`:

```typescript
export interface PendingPayload {
  entities: Record<string, unknown>[]
  _evidence?: Record<string, number | null>[]
  labeler_model?: string
  created_at?: string
}
```

Append to `lib/api.ts`:

```typescript
export async function getPending(
  slug: string, filename: string,
): Promise<PendingPayload | null> {
  const r = await fetch(
    `/lab/projects/${encodeURIComponent(slug)}/pending/${encodeURIComponent(filename)}`,
  )
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getPending ${r.status}`)
  return r.json()
}
```

**Test command:** `cd frontend && npx tsc -b --noEmit` (skip if no test file; verify build).

**Commit message:** `feat(m10): frontend types + getPending fetch helper`

---

## Task 11 — Review store: pending fallback

**Files:**
- Modify: `frontend/src/stores/review.ts`

**Steps:**

Add to state shape:

```typescript
isPending: boolean
labelerModel: string | null
```

Initialize to `false` / `null` in initial state and in `open()` reset block,
and `close()`.

In `open()`, after the existing `Promise.all([getReviewed, getPrediction])`
block:

```typescript
const [reviewed, pred] = await Promise.all([
  getReviewed(projectId, filename),
  getPrediction(projectId, filename),
])
let pending = null
if (!reviewed) {
  pending = await getPending(projectId, filename)
}

const reviewedEnts = reviewed?.entities
const pendingEnts = pending?.entities
const predEnts = pred?.entities
const base = reviewedEnts ?? pendingEnts ?? predEnts ?? [{}]
const entities = base.map((src, i) => {
  const predEnt = (predEnts?.[i] ?? {}) as Record<string, unknown>
  const baseEnt = (src ?? {}) as Record<string, unknown>
  return reviewedEnts || pendingEnts
    ? { ...predEnt, ...baseEnt }
    : baseEnt
})
set({
  entities,
  evidence: reviewed?._evidence ?? pending?._evidence ?? pred?._evidence ?? null,
  notes: reviewed?._notes ?? {},
  isPending: !reviewed && !!pending,
  labelerModel: !reviewed && pending ? pending.labeler_model ?? null : null,
  loading: false,
})
```

After `save()` succeeds (saveReviewed call), reset `isPending: false, labelerModel: null` because the server-side pending file is now gone.

**Test command:** `cd frontend && npm test -- review` (if a store test exists; else just typecheck).

**Commit message:** `feat(m10): review store falls back to pending payload`

---

## Task 12 — PreLabelNotice banner

**Files:**
- New: `frontend/src/components/ReviewMode/PreLabelNotice.tsx`
- Modify: `frontend/src/components/ReviewMode/ReviewOverlay.tsx`

**Banner component:**

```tsx
import React from 'react'

interface Props {
  labelerModel: string | null
}

export default function PreLabelNotice({ labelerModel }: Props) {
  return (
    <div
      style={{
        borderLeft: '2px solid var(--ochre)',
        padding: '8px 16px',
        fontFamily: 'var(--mono)',
        fontSize: 12,
        color: 'var(--ink-7)',
        background: 'var(--paper-1)',
      }}
    >
      Pro-labeled by {labelerModel ?? 'unknown'} · please verify and save
    </div>
  )
}
```

In `ReviewOverlay.tsx`, between `ReviewBar` (~line 304–328) and `rev-body` (~line 336):

```tsx
{isPending && (
  <PreLabelNotice labelerModel={labelerModel} />
)}
```

Wire `isPending`, `labelerModel` from `useReview`.

**Test command:** `cd frontend && npx tsc -b --noEmit`

**Commit message:** `feat(m10): pre-label notice banner in ReviewOverlay`

---

## Task 13 — Cross-store refresh

**Files:**
- Modify: `frontend/src/stores/chat.ts` (`handleToolResult`)

Add a branch alongside existing `extract_batch`/`extract_one`:

```typescript
if (t === 'mcp__emerge_tools__pre_label') {
  void useDocs.getState().refresh(projectId)
  // Note: review store re-fetches pending on next open()/route; no global invalidate needed.
}
```

**Test command:** `cd frontend && npx tsc -b --noEmit`

**Commit message:** `feat(m10): chat store refreshes docs after pre_label`

---

## Task 14 — Frontend lint + typecheck

```bash
cd frontend && npm run lint && npx tsc -b --noEmit
```

(Find exact lint script via `package.json` if `npm run lint` doesn't exist.)

**Commit message:** none (verification).

---

## Task 15 — Smoke verification

If `EMERGE_DEFAULT_LABELER_MODEL` is set in env:

1. Start backend (8080) + frontend (5173).
2. New project, upload 3 invoices.
3. In chat: "pro 先帮我标一版".
4. Verify `pre_label` runs, returns `processed: [3 files]`.
5. Open first doc in Review mode → banner shows "Pro-labeled by {model}".
6. Edit one field, save → banner gone, `reviewed/{file}.json` exists,
   `reviewed/_pending/{file}.json` gone.
7. `/eval` → ground truth includes this doc.

If `EMERGE_DEFAULT_LABELER_MODEL` is NOT set:

1. POST `/lab/projects/{slug}/pre_label` (no body) → expect 400 +
   `labeler_model_not_configured`.
2. Grep for `PreLabelNotice` and verify the component renders correctly when
   passed mock `labelerModel`.
3. Report "needs human smoke verify" in the final summary.

**Reverse verification (always do):**

1. `pre_label` 3 docs without verifying.
2. `score()` / `list_reviewed` → must return `n_reviewed: 0` (pending excluded).
3. `readiness_check` → must report 0 reviewed.

---

## Critical files to modify (recap)

**Backend**
- `backend/app/workspace/paths.py` (+ pending helpers)
- `backend/app/tools/projects.py` (+ labeler_model in blob)
- `backend/app/config.py` (+ default_labeler_model)
- `backend/app/tools/pre_label.py` (NEW)
- `backend/app/tools/reviewed.py` (save_reviewed pending cleanup; reuses get_pending from pre_label)
- `backend/app/tools/__init__.py` (register 3 new tools)
- `backend/app/api/routes/pre_label.py` (NEW)
- `backend/app/api/routes/reviewed.py` (+ GET /pending)
- `backend/app/main.py` (mount pre_label router)
- `backend/app/tools/surface_state.py` (+ has_pending)
- `backend/app/skills/emerge_extractor.md` (+ Pro labeler section)

**Frontend**
- `frontend/src/types/review.ts` (+ PendingPayload)
- `frontend/src/lib/api.ts` (+ getPending)
- `frontend/src/stores/review.ts` (+ isPending / labelerModel + open fallback)
- `frontend/src/stores/chat.ts` (+ pre_label refresh hook)
- `frontend/src/components/ReviewMode/PreLabelNotice.tsx` (NEW)
- `frontend/src/components/ReviewMode/ReviewOverlay.tsx` (+ banner mount)
