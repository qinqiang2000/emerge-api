# M2A — Reviewed Examples + Review Mode UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user click a doc, see the PDF + extracted JSON side-by-side, correct values, and save the result as a reviewed example (ground truth). After this, every project has a `reviewed/` folder with one JSON per doc the user has confirmed.

**Architecture:** Three-pane shell stays as M1's default. Right pane (currently "DocPreview placeholder") becomes a **DocList** showing each project's docs with a status badge (`draft` / `reviewed`). Click a doc → app transitions into a **review mode** full-canvas takeover (left 60% = PDF viewer with page nav, right 40% = JSON field editor). Save → POST `/lab/projects/{pid}/reviewed/{did}` → write `reviewed/{did}.json` atomically → return to three-pane. Backend gets three new tools (`save_reviewed`, `list_reviewed`, `get_reviewed`) registered in MCP plus a non-agent HTTP route for the review-mode save (the agent doesn't need to mediate every value edit).

**Tech Stack:** No new tech. FastAPI + pydantic v2 on backend. Vite + React 19 + Zustand on frontend. PyMuPDF for PDF rendering already installed (used by `pdf_render_page`).

---

## Scope cuts (deferred to M2B)

M2A intentionally ships only the minimum review-loop. The following are deliberately out of scope, to land in M2B:

- **Inline comments** (`_notes`) — M2B
- **Type-derived controls** (enum chips, number stepper, date picker) — M2A uses plain text input for every field type. The schema field's `type` is shown next to the value as a chip but doesn't change the input.
- **`_source_page` click-to-page evidence trace** — M2A's PDF viewer has prev/next buttons only. No correlation between JSON click and PDF page.
- **Prev/Next doc nav inside review mode** — M2A: save returns to three-pane, user clicks the next doc from the doc list. M2B adds in-review nav.
- **Score / `/eval`** — separate plan M2B.

Reviewed examples written in M2A are **fully usable as ground truth** in M2B's eval — the JSON shape is the long-term contract.

---

## File structure

### Backend (`backend/`)

```
backend/app/
├── tools/
│   ├── reviewed.py          # save_reviewed, list_reviewed, get_reviewed (NEW)
│   ├── predictions.py       # get_prediction (NEW; for review mode load)
│   └── __init__.py          # MCP registration extended (MODIFIED)
├── workspace/
│   └── paths.py             # add reviewed_path, reviewed_dir (MODIFIED)
└── api/routes/
    ├── reviewed.py          # GET / POST /lab/projects/{pid}/reviewed/{did} (NEW)
    └── predictions.py       # GET /lab/projects/{pid}/predictions/_draft/{did} (NEW)

backend/tests/unit/test_paths.py            # add reviewed_path tests (MODIFIED)
backend/tests/unit/test_tool_reviewed.py    # NEW
backend/tests/unit/test_tool_predictions.py # NEW
backend/tests/unit/test_tool_registration.py # extended assertion (MODIFIED)
backend/tests/integration/test_lab_reviewed.py    # NEW
backend/tests/integration/test_lab_predictions.py # NEW
```

### Frontend (`frontend/src/`)

```
src/
├── types/
│   └── review.ts            # NEW — ReviewedDoc, DocStatus, FieldValue
├── lib/
│   └── api.ts               # add getPrediction/getReviewed/saveReviewed/listDocs (MODIFIED)
├── stores/
│   ├── review.ts            # NEW — Zustand store for active review session
│   └── docs.ts              # NEW — Zustand store for current project's doc list
├── components/
│   ├── DocList/
│   │   ├── DocList.tsx      # NEW — replaces DocPreview placeholder
│   │   └── DocItem.tsx      # NEW — one row with status badge
│   └── ReviewMode/
│       ├── ReviewMode.tsx   # NEW — full-canvas mode container
│       ├── PdfViewer.tsx    # NEW — PNG-per-page viewer with prev/next
│       └── FieldEditor.tsx  # NEW — per-field text input + save button
├── App.tsx                  # toggles between three-pane and review mode (MODIFIED)
└── components/DocPreview/DocPreview.tsx  # delete file (REMOVED)

tests/unit/DocList.test.tsx       # NEW
tests/unit/FieldEditor.test.tsx   # NEW
```

---

## Conventions

- Backend tests: `cd backend && uv run pytest -v`. asyncio_mode=auto already configured.
- Frontend tests: `cd frontend && npm run test`.
- All new backend code uses `Path` (not strings) for filesystem.
- All routes use the `safe_project_id` / `safe_doc_id` validators from `app/api/routes/_safety.py` — added in M1's path-traversal fix.
- File writes go through `atomic_write_json` + `project_lock`.
- Frontend uses semantic Tailwind tokens (`bg-canvas`/`text-fg-primary`/etc.) — never raw color classes (`bg-gray-100`).
- TDD: every backend task lands a failing test first.

---

## Task index

Phase 1: backend paths + tools (1–6)
Phase 2: backend routes (7–9)
Phase 3: frontend types + API (10–11)
Phase 4: frontend doc list (12–14)
Phase 5: frontend review mode (15–19)
Phase 6: integration polish + e2e (20–22)

---

## Phase 1 — Backend paths + tools

### Task 1: Path helpers for `reviewed/`

**Files:**
- Modify: `backend/app/workspace/paths.py`
- Modify: `backend/tests/unit/test_paths.py`

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/unit/test_paths.py` after the existing imports + tests:

```python
from app.workspace.paths import reviewed_dir, reviewed_path


def test_reviewed_dir(workspace: Path) -> None:
    assert reviewed_dir(workspace, "p_abc") == workspace / "p_abc" / "reviewed"


def test_reviewed_path(workspace: Path) -> None:
    assert reviewed_path(workspace, "p_abc", "d_xyz") == workspace / "p_abc" / "reviewed" / "d_xyz.json"
```

Also extend the existing wildcard import at the top:
```python
from app.workspace.paths import (
    project_dir,
    schema_path,
    project_json_path,
    docs_dir,
    doc_path,
    doc_meta_path,
    predictions_draft_dir,
    versions_dir,
    chats_dir,
    keys_path,
    job_locks_dir,
    reviewed_dir,
    reviewed_path,
)
```

- [ ] **Step 2: Run test to verify failures**

Run: `cd backend && uv run pytest tests/unit/test_paths.py -v`
Expected: ImportError on `reviewed_dir`/`reviewed_path`.

- [ ] **Step 3: Add the helpers**

Append to `backend/app/workspace/paths.py`:

```python
def reviewed_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "reviewed"


def reviewed_path(workspace: Path, project_id: str, doc_id: str) -> Path:
    return reviewed_dir(workspace, project_id) / f"{doc_id}.json"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && uv run pytest tests/unit/test_paths.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace/paths.py backend/tests/unit/test_paths.py
git commit -m "feat(workspace): reviewed_dir / reviewed_path helpers"
```

---

### Task 2: `Reviewed` schema model

**Files:**
- Create: `backend/app/schemas/reviewed.py`
- Create: `backend/tests/unit/test_reviewed_schema.py`

The reviewed-example JSON shape on disk is `{ entities: [...], _notes?: {field_name: str}, _evidence?: [...] }`. M2A only writes `entities`; `_notes` is M2B. We define the model with `_notes` already present so M2B doesn't need a migration.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_reviewed_schema.py
import pytest
from pydantic import ValidationError

from app.schemas.reviewed import Reviewed, ReviewedSource


def test_reviewed_minimal() -> None:
    r = Reviewed(entities=[{"invoice_no": "INV-1"}], source=ReviewedSource.MANUAL)
    assert r.entities == [{"invoice_no": "INV-1"}]
    assert r.source == ReviewedSource.MANUAL
    assert r.notes is None


def test_reviewed_with_notes() -> None:
    r = Reviewed(
        entities=[{"buyer_name": "ACME"}],
        source=ReviewedSource.MANUAL,
        notes={"buyer_name": "official: ACME Sdn Bhd"},
    )
    assert r.notes == {"buyer_name": "official: ACME Sdn Bhd"}


def test_reviewed_source_enum_values() -> None:
    assert ReviewedSource.MANUAL.value == "manual"
    assert ReviewedSource.FEEDBACK.value == "feedback"


def test_reviewed_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Reviewed(
            entities=[{}],
            source=ReviewedSource.MANUAL,
            unknown_field="x",
        )


def test_reviewed_serializes_with_notes_alias() -> None:
    r = Reviewed(
        entities=[{}],
        source=ReviewedSource.MANUAL,
        notes={"a": "b"},
    )
    blob = r.model_dump(by_alias=True, exclude_none=True)
    # `notes` aliased to `_notes` for the wire shape
    assert "_notes" in blob
    assert blob["_notes"] == {"a": "b"}
    assert "source" in blob
```

- [ ] **Step 2: Run test, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_reviewed_schema.py -v`
Expected: ImportError on `app.schemas.reviewed`.

- [ ] **Step 3: Implement Reviewed**

```python
# backend/app/schemas/reviewed.py
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ReviewedSource(str, Enum):
    MANUAL = "manual"
    FEEDBACK = "feedback"


class Reviewed(BaseModel):
    """Ground-truth reviewed extraction for a doc.

    On the wire: `notes` is serialized as `_notes`. The leading underscore
    keeps it visually grouped with `_evidence` in the JSON file but the
    Python attribute uses a regular name.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entities: list[dict[str, Any]]
    source: ReviewedSource = ReviewedSource.MANUAL
    notes: Optional[dict[str, str]] = Field(default=None, alias="_notes")
```

- [ ] **Step 4: Run tests, confirm 5 pass**

Run: `cd backend && uv run pytest tests/unit/test_reviewed_schema.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/reviewed.py backend/tests/unit/test_reviewed_schema.py
git commit -m "feat(schemas): Reviewed model with source enum + _notes alias"
```

---

### Task 3: `save_reviewed` tool

**Files:**
- Create: `backend/app/tools/reviewed.py`
- Create: `backend/tests/unit/test_tool_reviewed.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_tool_reviewed.py
import json
from pathlib import Path

from app.schemas.reviewed import ReviewedSource
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed


async def test_save_reviewed_writes_file(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await save_reviewed(
        workspace,
        pid,
        "d_test",
        entities=[{"invoice_no": "INV-1", "total_amount": 99.5}],
        source=ReviewedSource.MANUAL,
    )
    target = workspace / pid / "reviewed" / "d_test.json"
    assert target.exists()
    blob = json.loads(target.read_text())
    assert blob["entities"] == [{"invoice_no": "INV-1", "total_amount": 99.5}]
    assert blob["source"] == "manual"
    assert "_notes" not in blob   # default None excluded


async def test_save_reviewed_with_notes(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await save_reviewed(
        workspace,
        pid,
        "d_test",
        entities=[{"buyer_name": "ACME"}],
        source=ReviewedSource.MANUAL,
        notes={"buyer_name": "double-checked"},
    )
    blob = json.loads((workspace / pid / "reviewed" / "d_test.json").read_text())
    assert blob["_notes"] == {"buyer_name": "double-checked"}


async def test_save_reviewed_overwrites_existing(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await save_reviewed(
        workspace, pid, "d_test", entities=[{"a": 1}], source=ReviewedSource.MANUAL
    )
    await save_reviewed(
        workspace, pid, "d_test", entities=[{"a": 2}], source=ReviewedSource.MANUAL
    )
    blob = json.loads((workspace / pid / "reviewed" / "d_test.json").read_text())
    assert blob["entities"] == [{"a": 2}]


async def test_save_reviewed_creates_reviewed_dir(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    rd = workspace / pid / "reviewed"
    assert not rd.exists()  # not auto-created on project init
    await save_reviewed(
        workspace, pid, "d_test", entities=[{}], source=ReviewedSource.MANUAL
    )
    assert rd.is_dir()
```

- [ ] **Step 2: Run test, confirm ImportError**

Run: `cd backend && uv run pytest tests/unit/test_tool_reviewed.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement save_reviewed**

```python
# backend/app/tools/reviewed.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from app.schemas.reviewed import Reviewed, ReviewedSource
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import reviewed_dir, reviewed_path


async def save_reviewed(
    workspace: Path,
    project_id: str,
    doc_id: str,
    *,
    entities: list[dict[str, Any]],
    source: ReviewedSource = ReviewedSource.MANUAL,
    notes: Optional[dict[str, str]] = None,
) -> None:
    """Persist a corrected extraction as ground truth for a doc.

    Overwrites any existing reviewed file for the same (project, doc).
    """
    payload = Reviewed(entities=entities, source=source, notes=notes).model_dump(
        by_alias=True, exclude_none=True, mode="json"
    )
    async with project_lock(workspace, project_id):
        reviewed_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_json(reviewed_path(workspace, project_id, doc_id), payload)
```

- [ ] **Step 4: Run tests, confirm 4 pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_reviewed.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/reviewed.py backend/tests/unit/test_tool_reviewed.py
git commit -m "feat(tools): save_reviewed writes ground truth atomically"
```

---

### Task 4: `list_reviewed` and `get_reviewed`

**Files:**
- Modify: `backend/app/tools/reviewed.py`
- Modify: `backend/tests/unit/test_tool_reviewed.py`

- [ ] **Step 1: Append failing tests**

```python
# (append to backend/tests/unit/test_tool_reviewed.py)
from app.tools.reviewed import get_reviewed, list_reviewed


async def test_list_reviewed_empty(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    assert await list_reviewed(workspace, pid) == []


async def test_list_reviewed_returns_doc_ids(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await save_reviewed(
        workspace, pid, "d_aaa", entities=[{}], source=ReviewedSource.MANUAL
    )
    await save_reviewed(
        workspace, pid, "d_bbb", entities=[{}], source=ReviewedSource.MANUAL
    )
    items = await list_reviewed(workspace, pid)
    assert {it["doc_id"] for it in items} == {"d_aaa", "d_bbb"}


async def test_get_reviewed_returns_payload(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await save_reviewed(
        workspace,
        pid,
        "d_test",
        entities=[{"invoice_no": "INV-1"}],
        source=ReviewedSource.MANUAL,
        notes={"invoice_no": "verified"},
    )
    got = await get_reviewed(workspace, pid, "d_test")
    assert got is not None
    assert got["entities"] == [{"invoice_no": "INV-1"}]
    assert got["_notes"] == {"invoice_no": "verified"}


async def test_get_reviewed_returns_none_for_missing(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    assert await get_reviewed(workspace, pid, "d_unreviewed") is None
```

- [ ] **Step 2: Run, confirm failure**

Run: `cd backend && uv run pytest tests/unit/test_tool_reviewed.py -v`
Expected: ImportError on `list_reviewed` / `get_reviewed`.

- [ ] **Step 3: Append implementation**

Append to `backend/app/tools/reviewed.py`:

```python
import json


async def list_reviewed(workspace: Path, project_id: str) -> list[dict[str, Any]]:
    """List all reviewed examples for a project as `[{doc_id, entities, ...}]`."""
    rd = reviewed_dir(workspace, project_id)
    if not rd.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(rd.glob("*.json")):
        blob = json.loads(p.read_text())
        out.append({"doc_id": p.stem, **blob})
    return out


async def get_reviewed(
    workspace: Path,
    project_id: str,
    doc_id: str,
) -> Optional[dict[str, Any]]:
    """Return the reviewed payload for a doc or None if not yet reviewed."""
    p = reviewed_path(workspace, project_id, doc_id)
    if not p.exists():
        return None
    return json.loads(p.read_text())
```

- [ ] **Step 4: Run tests, confirm 8 pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_reviewed.py -v`
Expected: 8 passed (4 from Task 3 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/reviewed.py backend/tests/unit/test_tool_reviewed.py
git commit -m "feat(tools): list_reviewed + get_reviewed"
```

---

### Task 5: `get_prediction` tool (read draft predictions)

**Files:**
- Create: `backend/app/tools/predictions.py`
- Create: `backend/tests/unit/test_tool_predictions.py`

The review mode loads the latest draft prediction as the starting value for editing. This tool exposes that data; M2B's `score` will also use it.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_tool_predictions.py
import json
from pathlib import Path

from app.tools.projects import create_project
from app.tools.predictions import get_prediction
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir


async def test_get_prediction_returns_draft(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    pred = {"entities": [{"invoice_no": "X-1"}], "_evidence": [{"invoice_no": 1}]}
    pdir = predictions_draft_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pdir / "d_test.json", pred)
    got = await get_prediction(workspace, pid, "d_test")
    assert got == pred


async def test_get_prediction_returns_none_for_missing(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    assert await get_prediction(workspace, pid, "d_missing") is None
```

- [ ] **Step 2: Run, confirm ImportError**

Run: `cd backend && uv run pytest tests/unit/test_tool_predictions.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/tools/predictions.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.workspace.paths import predictions_draft_dir


async def get_prediction(
    workspace: Path,
    project_id: str,
    doc_id: str,
) -> Optional[dict[str, Any]]:
    """Return the latest draft prediction for a doc, or None."""
    p = predictions_draft_dir(workspace, project_id) / f"{doc_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())
```

- [ ] **Step 4: Run tests, confirm 2 pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_predictions.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/predictions.py backend/tests/unit/test_tool_predictions.py
git commit -m "feat(tools): get_prediction reads draft extraction"
```

---

### Task 6: Register new tools in MCP

**Files:**
- Modify: `backend/app/tools/__init__.py`
- Modify: `backend/tests/unit/test_tool_registration.py`

The agent gets `save_reviewed`, `list_reviewed`, `get_reviewed`, `get_prediction` so it can read/write reviewed examples directly (e.g. user says "改 buyer_name 为 ACME Sdn Bhd 并保存"). Note: the human review-mode UI uses HTTP routes (Task 7-9), not the agent.

- [ ] **Step 1: Modify `test_tool_registration.py`**

Edit the `expected` set to include the four new names:

```python
def test_build_emerge_mcp_lists_tools(workspace: Path, stub_provider: AsyncMock) -> None:
    server = build_emerge_mcp(workspace=workspace, provider=stub_provider)
    names = _extract_tool_names(server)
    expected = {
        "create_project",
        "upload_doc",
        "list_docs",
        "list_projects",
        "derive_schema",
        "read_schema",
        "write_schema",
        "extract_one",
        "extract_batch",
        "pdf_render_page",
        # M2A additions
        "save_reviewed",
        "list_reviewed",
        "get_reviewed",
        "get_prediction",
    }
    assert expected.issubset(names), (expected - names, names)
```

- [ ] **Step 2: Run test, confirm failure**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`
Expected: FAIL — missing 4 tool names.

- [ ] **Step 3: Register the new tools**

Modify `backend/app/tools/__init__.py`. Add imports near the top:

```python
from app.tools import predictions as predictions_mod
from app.tools import reviewed as reviewed_mod
from app.schemas.reviewed import ReviewedSource
```

Inside `build_emerge_mcp(...)` body, after the existing tool definitions and before `return create_sdk_mcp_server(...)`, add:

```python
    @tool(
        "save_reviewed",
        "Save a corrected extraction as ground truth for a doc.",
        {
            "project_id": str,
            "doc_id": str,
            "entities": list,
            "source": str,  # "manual" | "feedback"
            "notes": dict,  # optional; pass {} if none
        },
    )
    async def t_save_reviewed(args: dict[str, Any]) -> dict[str, Any]:
        await reviewed_mod.save_reviewed(
            workspace,
            args["project_id"],
            args["doc_id"],
            entities=args["entities"],
            source=ReviewedSource(args.get("source", "manual")),
            notes=args.get("notes") or None,
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "list_reviewed",
        "List all reviewed examples in a project.",
        {"project_id": str},
    )
    async def t_list_reviewed(args: dict[str, Any]) -> dict[str, Any]:
        items = await reviewed_mod.list_reviewed(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": str(items)}]}

    @tool(
        "get_reviewed",
        "Get the reviewed payload for one doc or null if not reviewed.",
        {"project_id": str, "doc_id": str},
    )
    async def t_get_reviewed(args: dict[str, Any]) -> dict[str, Any]:
        payload = await reviewed_mod.get_reviewed(
            workspace, args["project_id"], args["doc_id"]
        )
        return {"content": [{"type": "text", "text": str(payload)}]}

    @tool(
        "get_prediction",
        "Get the latest draft prediction for a doc or null if not extracted.",
        {"project_id": str, "doc_id": str},
    )
    async def t_get_prediction(args: dict[str, Any]) -> dict[str, Any]:
        payload = await predictions_mod.get_prediction(
            workspace, args["project_id"], args["doc_id"]
        )
        return {"content": [{"type": "text", "text": str(payload)}]}
```

Then extend the `tools=[...]` list passed to `create_sdk_mcp_server`:

```python
        tools=[
            t_create_project,
            t_list_projects,
            t_upload_doc,
            t_list_docs,
            t_pdf_render_page,
            t_derive_schema,
            t_read_schema,
            t_write_schema,
            t_extract_one,
            t_extract_batch,
            t_save_reviewed,
            t_list_reviewed,
            t_get_reviewed,
            t_get_prediction,
        ],
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`
Expected: 1 passed.

Then full backend suite:
```
cd backend && uv run pytest -q 2>&1 | tail -3
```
Expected: all green (~107 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/__init__.py backend/tests/unit/test_tool_registration.py
git commit -m "feat(tools): register save/list/get_reviewed + get_prediction in MCP"
```

---

## Phase 2 — Backend HTTP routes

The frontend's review-mode UI talks directly to these routes; it doesn't go through the agent for every value edit (would cost an LLM call per save).

### Task 7: GET predictions route

**Files:**
- Create: `backend/app/api/routes/predictions.py`
- Modify: `backend/app/main.py` — mount router
- Create: `backend/tests/integration/test_lab_predictions.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_lab_predictions.py
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir


async def test_get_prediction_200(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    pdir = predictions_draft_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pdir / "d_aaa.json", {"entities": [{"x": 1}]})
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/predictions/d_aaa")
    assert r.status_code == 200
    assert r.json() == {"entities": [{"x": 1}]}


async def test_get_prediction_404_when_missing(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/predictions/d_nope")
    assert r.status_code == 404


def test_get_prediction_400_on_bad_pid() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/..%2Fetc/predictions/d_x")
    assert r.status_code == 400
```

- [ ] **Step 2: Run, confirm 404 (route not mounted)**

Run: `cd backend && uv run pytest tests/integration/test_lab_predictions.py -v`
Expected: routes not found.

- [ ] **Step 3: Implement route**

```python
# backend/app/api/routes/predictions.py
from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_doc_id, safe_project_id
from app.config import get_settings
from app.tools.predictions import get_prediction


router = APIRouter()


@router.get("/lab/projects/{project_id}/predictions/{doc_id}")
async def get_doc_prediction(project_id: str, doc_id: str) -> dict:
    safe_project_id(project_id)
    safe_doc_id(doc_id)
    settings = get_settings()
    payload = await get_prediction(settings.workspace_root, project_id, doc_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="prediction_not_found")
    return payload
```

- [ ] **Step 4: Mount router**

In `backend/app/main.py`, add the import next to the other route imports:

```python
from app.api.routes import predictions as predictions_route
```

And add the include after the other `app.include_router(...)` lines:

```python
app.include_router(predictions_route.router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_lab_predictions.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/predictions.py backend/app/main.py backend/tests/integration/test_lab_predictions.py
git commit -m "feat(api): GET /lab/projects/{pid}/predictions/{did}"
```

---

### Task 8: GET + POST reviewed route

**Files:**
- Create: `backend/app/api/routes/reviewed.py`
- Modify: `backend/app/main.py` — mount router
- Create: `backend/tests/integration/test_lab_reviewed.py`

The POST is the human review save path. Body shape mirrors the `Reviewed` model.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_lab_reviewed.py
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project


async def test_post_reviewed_writes_file(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    body = {
        "entities": [{"invoice_no": "INV-1", "total_amount": 99.5}],
        "source": "manual",
    }
    r = client.post(f"/lab/projects/{pid}/reviewed/d_test", json=body)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    saved = (workspace / pid / "reviewed" / "d_test.json").read_text()
    assert "INV-1" in saved
    assert '"source": "manual"' in saved


async def test_post_reviewed_with_notes(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    body = {
        "entities": [{"buyer_name": "ACME"}],
        "source": "manual",
        "notes": {"buyer_name": "official: ACME Sdn Bhd"},
    }
    r = client.post(f"/lab/projects/{pid}/reviewed/d_test", json=body)
    assert r.status_code == 200
    saved = (workspace / pid / "reviewed" / "d_test.json").read_text()
    assert "official: ACME Sdn Bhd" in saved


async def test_get_reviewed_returns_payload(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    client.post(
        f"/lab/projects/{pid}/reviewed/d_test",
        json={"entities": [{"x": 1}], "source": "manual"},
    )
    r = client.get(f"/lab/projects/{pid}/reviewed/d_test")
    assert r.status_code == 200
    assert r.json()["entities"] == [{"x": 1}]


def test_get_reviewed_404_when_missing() -> None:
    client = TestClient(app)
    # use a valid-format pid that doesn't exist
    r = client.get("/lab/projects/p_abcdef012345/reviewed/d_abcdef012345")
    assert r.status_code == 404


def test_post_reviewed_400_on_bad_pid() -> None:
    client = TestClient(app)
    r = client.post(
        "/lab/projects/..%2Fetc/reviewed/d_x",
        json={"entities": [], "source": "manual"},
    )
    assert r.status_code == 400


def test_post_reviewed_422_on_bad_body() -> None:
    client = TestClient(app)
    r = client.post(
        "/lab/projects/p_abcdef012345/reviewed/d_abcdef012345",
        json={"entities": "not-a-list", "source": "manual"},
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/integration/test_lab_reviewed.py -v`
Expected: routes not mounted.

- [ ] **Step 3: Implement route**

```python
# backend/app/api/routes/reviewed.py
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.routes._safety import safe_doc_id, safe_project_id
from app.config import get_settings
from app.schemas.reviewed import ReviewedSource
from app.tools.reviewed import get_reviewed, save_reviewed


router = APIRouter()


class ReviewedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entities: list[dict[str, Any]]
    source: ReviewedSource = ReviewedSource.MANUAL
    notes: Optional[dict[str, str]] = None


@router.post("/lab/projects/{project_id}/reviewed/{doc_id}")
async def post_reviewed(
    project_id: str,
    doc_id: str,
    body: ReviewedBody,
) -> dict:
    safe_project_id(project_id)
    safe_doc_id(doc_id)
    settings = get_settings()
    await save_reviewed(
        settings.workspace_root,
        project_id,
        doc_id,
        entities=body.entities,
        source=body.source,
        notes=body.notes,
    )
    return {"ok": True}


@router.get("/lab/projects/{project_id}/reviewed/{doc_id}")
async def get_doc_reviewed(project_id: str, doc_id: str) -> dict:
    safe_project_id(project_id)
    safe_doc_id(doc_id)
    settings = get_settings()
    payload = await get_reviewed(settings.workspace_root, project_id, doc_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="reviewed_not_found")
    return payload
```

- [ ] **Step 4: Mount router**

In `backend/app/main.py`:

```python
from app.api.routes import reviewed as reviewed_route
# ... and:
app.include_router(reviewed_route.router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_lab_reviewed.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/reviewed.py backend/app/main.py backend/tests/integration/test_lab_reviewed.py
git commit -m "feat(api): GET / POST /lab/projects/{pid}/reviewed/{did}"
```

---

### Task 9: GET project docs list (used by frontend doc list)

**Files:**
- Modify: `backend/app/api/routes/projects.py`
- Modify: `backend/tests/integration/test_lab_projects.py`

We need a way for the frontend to list a project's docs **with status badges** (`reviewed` vs `draft`-only). Add a single GET that returns each doc enriched with `has_prediction` + `has_reviewed` booleans.

- [ ] **Step 1: Append failing test**

Append to `backend/tests/integration/test_lab_projects.py`:

```python
async def test_get_project_docs_with_status(workspace: Path) -> None:
    from app.tools.docs import upload_doc
    from app.tools.reviewed import save_reviewed
    from app.schemas.reviewed import ReviewedSource

    pid = await create_project(workspace, name="x")
    pdf = b"%PDF-1.4\n%%EOF\n"
    d1 = await upload_doc(workspace, pid, pdf, "a.pdf")
    d2 = await upload_doc(workspace, pid, pdf, "b.pdf")
    # mark one reviewed
    await save_reviewed(
        workspace, pid, d1, entities=[{}], source=ReviewedSource.MANUAL
    )

    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/docs")
    assert r.status_code == 200
    items = r.json()
    by_id = {it["doc_id"]: it for it in items}
    assert by_id[d1]["has_reviewed"] is True
    assert by_id[d1]["has_prediction"] is False
    assert by_id[d2]["has_reviewed"] is False
    assert by_id[d2]["filename"] == "b.pdf"


def test_get_project_docs_400_on_bad_pid() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/..%2Fetc/docs")
    assert r.status_code == 400
```

- [ ] **Step 2: Run, confirm 404**

Run: `cd backend && uv run pytest tests/integration/test_lab_projects.py -v`
Expected: existing 3 tests still pass; 2 new fail.

- [ ] **Step 3: Append implementation**

In `backend/app/api/routes/projects.py`, add at top:

```python
from app.api.routes._safety import safe_project_id
from app.tools.docs import list_docs
from app.tools.reviewed import list_reviewed
from app.workspace.paths import predictions_draft_dir
```

(`safe_project_id` is already imported in some routes — keep imports tidy.)

Append a new endpoint:

```python
@router.get("/lab/projects/{project_id}/docs")
async def get_project_docs(project_id: str) -> list[dict]:
    safe_project_id(project_id)
    settings = get_settings()
    docs = await list_docs(settings.workspace_root, project_id)
    reviewed_ids = {
        r["doc_id"] for r in await list_reviewed(settings.workspace_root, project_id)
    }
    pdir = predictions_draft_dir(settings.workspace_root, project_id)
    pred_ids = {p.stem for p in pdir.glob("*.json")} if pdir.exists() else set()
    out = []
    for d in docs:
        out.append({
            **d,
            "has_reviewed": d["doc_id"] in reviewed_ids,
            "has_prediction": d["doc_id"] in pred_ids,
        })
    return out
```

(Note: `safe_project_id` import will already exist if `projects.py` was updated by the M1 path-traversal fix; otherwise add it.)

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_lab_projects.py -v`
Expected: 5 passed (3 existing + 2 new).

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3` — all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/projects.py backend/tests/integration/test_lab_projects.py
git commit -m "feat(api): GET /lab/projects/{pid}/docs with reviewed/prediction status"
```

---

## Phase 3 — Frontend types + API

### Task 10: Frontend types for review

**Files:**
- Create: `frontend/src/types/review.ts`

- [ ] **Step 1: Write the file**

```ts
// frontend/src/types/review.ts
export type DocStatus = 'reviewed' | 'predicted' | 'pending'

export interface DocSummary {
  doc_id: string
  filename: string
  ext: string
  page_count: number
  uploaded_at: string
  has_prediction: boolean
  has_reviewed: boolean
}

export interface PredictionPayload {
  entities: Record<string, unknown>[]
  _evidence?: Record<string, number | null>[]
}

export interface ReviewedPayload {
  entities: Record<string, unknown>[]
  source: 'manual' | 'feedback'
  _notes?: Record<string, string>
}

export function docStatus(d: DocSummary): DocStatus {
  if (d.has_reviewed) return 'reviewed'
  if (d.has_prediction) return 'predicted'
  return 'pending'
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/review.ts
git commit -m "feat(frontend): review types — DocSummary / DocStatus / payload shapes"
```

---

### Task 11: Frontend API methods

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Write the additions**

Append to `frontend/src/lib/api.ts`:

```ts
import type { DocSummary, PredictionPayload, ReviewedPayload } from '../types/review'

export async function listProjectDocs(projectId: string): Promise<DocSummary[]> {
  const r = await fetch(`/lab/projects/${projectId}/docs`)
  if (!r.ok) throw new Error(`listProjectDocs ${r.status}`)
  return r.json()
}

export async function getPrediction(projectId: string, docId: string): Promise<PredictionPayload | null> {
  const r = await fetch(`/lab/projects/${projectId}/predictions/${docId}`)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getPrediction ${r.status}`)
  return r.json()
}

export async function getReviewed(projectId: string, docId: string): Promise<ReviewedPayload | null> {
  const r = await fetch(`/lab/projects/${projectId}/reviewed/${docId}`)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`getReviewed ${r.status}`)
  return r.json()
}

export async function saveReviewed(
  projectId: string,
  docId: string,
  payload: ReviewedPayload,
): Promise<void> {
  const r = await fetch(`/lab/projects/${projectId}/reviewed/${docId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(`saveReviewed ${r.status}`)
}

export function pdfPageUrl(projectId: string, docId: string, page: number): string {
  return `/lab/projects/${projectId}/docs/${docId}/pages/${page}`
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): API for prediction / reviewed / project-docs"
```

---

## Phase 4 — Doc list (right pane)

### Task 12: Docs Zustand store

**Files:**
- Create: `frontend/src/stores/docs.ts`

- [ ] **Step 1: Write the store**

```ts
// frontend/src/stores/docs.ts
import { create } from 'zustand'

import { listProjectDocs } from '../lib/api'
import type { DocSummary } from '../types/review'

interface State {
  byProject: Record<string, DocSummary[]>
  loading: boolean
  refresh: (projectId: string) => Promise<void>
}

export const useDocs = create<State>((set) => ({
  byProject: {},
  loading: false,
  refresh: async (projectId) => {
    set({ loading: true })
    try {
      const docs = await listProjectDocs(projectId)
      set((s) => ({ byProject: { ...s.byProject, [projectId]: docs }, loading: false }))
    } catch {
      set({ loading: false })
    }
  },
}))
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/docs.ts
git commit -m "feat(frontend): docs store keyed by project id"
```

---

### Task 13: DocItem component (with vitest)

**Files:**
- Create: `frontend/src/components/DocList/DocItem.tsx`
- Create: `frontend/tests/unit/DocItem.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/tests/unit/DocItem.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import DocItem from '../../src/components/DocList/DocItem'
import type { DocSummary } from '../../src/types/review'

function makeDoc(overrides: Partial<DocSummary> = {}): DocSummary {
  return {
    doc_id: 'd_abc',
    filename: 'invoice.pdf',
    ext: 'pdf',
    page_count: 1,
    uploaded_at: '2026-05-09T00:00:00Z',
    has_prediction: false,
    has_reviewed: false,
    ...overrides,
  }
}

describe('DocItem', () => {
  it('shows filename + pending status when no prediction', () => {
    render(<DocItem doc={makeDoc()} onClick={() => {}} />)
    expect(screen.getByText('invoice.pdf')).toBeInTheDocument()
    expect(screen.getByText(/pending/i)).toBeInTheDocument()
  })

  it('shows draft when has_prediction but not reviewed', () => {
    render(<DocItem doc={makeDoc({ has_prediction: true })} onClick={() => {}} />)
    expect(screen.getByText(/draft/i)).toBeInTheDocument()
  })

  it('shows reviewed badge when has_reviewed', () => {
    render(<DocItem doc={makeDoc({ has_prediction: true, has_reviewed: true })} onClick={() => {}} />)
    expect(screen.getByText(/reviewed/i)).toBeInTheDocument()
  })

  it('calls onClick when clicked', async () => {
    const onClick = vi.fn()
    render(<DocItem doc={makeDoc()} onClick={onClick} />)
    await userEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledWith('d_abc')
  })
})
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `cd frontend && npm run test 2>&1 | tail -20`
Expected: 4 failures.

- [ ] **Step 3: Implement DocItem**

```tsx
// frontend/src/components/DocList/DocItem.tsx
import { docStatus, type DocSummary } from '../../types/review'

interface Props {
  doc: DocSummary
  onClick: (docId: string) => void
}

export default function DocItem({ doc, onClick }: Props) {
  const status = docStatus(doc)
  const badge =
    status === 'reviewed' ? 'reviewed'
    : status === 'predicted' ? 'draft'
    : 'pending'
  const badgeClass =
    status === 'reviewed' ? 'text-accent-success'
    : status === 'predicted' ? 'text-accent-info'
    : 'text-fg-muted'
  return (
    <button
      onClick={() => onClick(doc.doc_id)}
      className="w-full text-left px-3 py-2 hover:bg-subtle border-b border-subtle"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-sm truncate">{doc.filename}</span>
        <span className={`text-xs uppercase tracking-wide ${badgeClass}`}>{badge}</span>
      </div>
      <span className="text-xs text-fg-muted">{doc.page_count} page{doc.page_count !== 1 ? 's' : ''}</span>
    </button>
  )
}
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `cd frontend && npm run test`
Expected: 4 new pass + existing pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DocList/DocItem.tsx frontend/tests/unit/DocItem.test.tsx
git commit -m "feat(frontend): DocItem with status badge (reviewed/draft/pending)"
```

---

### Task 14: DocList component (replaces DocPreview)

**Files:**
- Create: `frontend/src/components/DocList/DocList.tsx`
- Modify: `frontend/src/App.tsx` — replace DocPreview import + usage
- Delete: `frontend/src/components/DocPreview/DocPreview.tsx`

DocList replaces the placeholder right pane. When no project selected → "select a project". When selected → list docs, click a doc to enter review mode (Task 19 wires that).

- [ ] **Step 1: Implement DocList**

```tsx
// frontend/src/components/DocList/DocList.tsx
import { useEffect } from 'react'

import { useProjects } from '../../stores/projects'
import { useDocs } from '../../stores/docs'
import { useReview } from '../../stores/review'

import DocItem from './DocItem'

export default function DocList() {
  const { selectedId } = useProjects()
  const { byProject, refresh } = useDocs()
  const { open } = useReview()

  useEffect(() => {
    if (selectedId) void refresh(selectedId)
  }, [selectedId, refresh])

  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 font-heading text-sm uppercase tracking-wide text-fg-muted">
        Docs
      </header>
      {!selectedId && (
        <div className="flex-1 grid place-items-center text-fg-muted text-sm font-body">
          select a project to see its docs
        </div>
      )}
      {selectedId && (
        <ul className="flex-1 overflow-auto">
          {(byProject[selectedId] ?? []).map((d) => (
            <li key={d.doc_id}>
              <DocItem doc={d} onClick={(did) => open(selectedId, did)} />
            </li>
          ))}
          {(byProject[selectedId] ?? []).length === 0 && (
            <li className="px-4 py-3 text-fg-muted text-sm font-body">
              no docs yet — drop PDFs into the chat to upload
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Update App.tsx**

Replace `DocPreview` import with `DocList`:

```tsx
// frontend/src/App.tsx
import ProjectList from './components/ProjectList/ProjectList'
import ChatPanel from './components/Chat/ChatPanel'
import DocList from './components/DocList/DocList'
import ReviewMode from './components/ReviewMode/ReviewMode'
import { useReview } from './stores/review'

export default function App() {
  const { activeDocId } = useReview()
  if (activeDocId) return <ReviewMode />
  return (
    <div className="grid grid-cols-[260px_1fr_360px] h-full bg-canvas text-fg-primary">
      <aside className="border-r border-subtle">
        <ProjectList />
      </aside>
      <main className="flex flex-col">
        <ChatPanel />
      </main>
      <aside className="border-l border-subtle">
        <DocList />
      </aside>
    </div>
  )
}
```

(`useReview` and `ReviewMode` are created in Task 15 / 18 — build will fail until those land. That's the expected interim state for this task.)

- [ ] **Step 3: Delete the placeholder**

```bash
rm frontend/src/components/DocPreview/DocPreview.tsx
rmdir frontend/src/components/DocPreview/ 2>/dev/null || true
```

- [ ] **Step 4: Commit (build will FAIL until later tasks land — that's OK)**

```bash
git add frontend/src/components/DocList/DocList.tsx frontend/src/App.tsx
git rm frontend/src/components/DocPreview/DocPreview.tsx 2>/dev/null || true
git commit -m "feat(frontend): DocList replaces DocPreview (review wiring in next tasks)"
```

---

## Phase 5 — Review mode

### Task 15: Review Zustand store

**Files:**
- Create: `frontend/src/stores/review.ts`

- [ ] **Step 1: Write the store**

```ts
// frontend/src/stores/review.ts
import { create } from 'zustand'

import { getPrediction, getReviewed, saveReviewed } from '../lib/api'
import type { ReviewedPayload } from '../types/review'

type FieldsValue = Record<string, unknown>

interface State {
  activeProjectId: string | null
  activeDocId: string | null
  page: number
  pageCount: number    // best-effort; defaulted to 1 until viewer probes
  loading: boolean
  saving: boolean
  err: string | null
  // Editing state: one entity for now (multi-entity is post-M2A)
  fields: FieldsValue
  open: (projectId: string, docId: string) => Promise<void>
  close: () => void
  setField: (name: string, value: unknown) => void
  goPage: (page: number) => void
  setPageCount: (n: number) => void
  save: () => Promise<void>
}

export const useReview = create<State>((set, get) => ({
  activeProjectId: null,
  activeDocId: null,
  page: 1,
  pageCount: 1,
  loading: false,
  saving: false,
  err: null,
  fields: {},
  open: async (projectId, docId) => {
    set({
      activeProjectId: projectId,
      activeDocId: docId,
      page: 1,
      pageCount: 1,
      loading: true,
      err: null,
      fields: {},
    })
    try {
      // Prefer reviewed payload (resume a partial review); fall back to draft.
      const reviewed = await getReviewed(projectId, docId)
      if (reviewed) {
        set({ fields: reviewed.entities[0] ?? {}, loading: false })
        return
      }
      const pred = await getPrediction(projectId, docId)
      set({ fields: pred?.entities[0] ?? {}, loading: false })
    } catch (e: unknown) {
      set({ err: String(e), loading: false })
    }
  },
  close: () => set({ activeProjectId: null, activeDocId: null, fields: {}, page: 1 }),
  setField: (name, value) => set((s) => ({ fields: { ...s.fields, [name]: value } })),
  goPage: (page) => set((s) => ({ page: Math.max(1, Math.min(s.pageCount, page)) })),
  setPageCount: (n) => set({ pageCount: Math.max(1, n) }),
  save: async () => {
    const { activeProjectId, activeDocId, fields } = get()
    if (!activeProjectId || !activeDocId) return
    set({ saving: true, err: null })
    try {
      const payload: ReviewedPayload = {
        entities: [fields],
        source: 'manual',
      }
      await saveReviewed(activeProjectId, activeDocId, payload)
      set({ saving: false })
    } catch (e: unknown) {
      set({ err: String(e), saving: false })
    }
  },
}))
```

- [ ] **Step 2: Verify build (still fails until ReviewMode component lands — OK)**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: errors about ReviewMode (created in Task 18) — that's fine.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/review.ts
git commit -m "feat(frontend): review store (open/close/setField/goPage/save)"
```

---

### Task 16: PdfViewer component

**Files:**
- Create: `frontend/src/components/ReviewMode/PdfViewer.tsx`

This component fetches `/lab/projects/{pid}/docs/{did}/pages/{n}` for the current page from the review store, displays it, and offers prev/next buttons. Page count is discovered lazily: try page+1; if 404, set pageCount=current.

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/components/ReviewMode/PdfViewer.tsx
import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

import { pdfPageUrl } from '../../lib/api'
import { useReview } from '../../stores/review'

export default function PdfViewer() {
  const { activeProjectId, activeDocId, page, pageCount, goPage, setPageCount } = useReview()
  const [loadError, setLoadError] = useState(false)
  const url = activeProjectId && activeDocId ? pdfPageUrl(activeProjectId, activeDocId, page) : ''

  // Lazy probe of next page on each page change. If the server 404s on page+1
  // we know the total. Cheap because rendered PNGs are cached server-side.
  useEffect(() => {
    if (!activeProjectId || !activeDocId) return
    if (page < pageCount) return
    fetch(pdfPageUrl(activeProjectId, activeDocId, page + 1), { method: 'HEAD' })
      .then((r) => {
        if (r.ok) setPageCount(page + 1)
      })
      .catch(() => {/* ignore */})
  }, [activeProjectId, activeDocId, page, pageCount, setPageCount])

  return (
    <div className="flex flex-col h-full bg-subtle">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-subtle bg-canvas">
        <button
          type="button"
          onClick={() => goPage(page - 1)}
          disabled={page <= 1}
          className="p-1 disabled:opacity-30 hover:bg-subtle rounded"
          aria-label="previous page"
        >
          <ChevronLeft size={16} />
        </button>
        <span className="text-xs font-mono text-fg-secondary">
          {page} / {pageCount}
        </span>
        <button
          type="button"
          onClick={() => goPage(page + 1)}
          disabled={page >= pageCount}
          className="p-1 disabled:opacity-30 hover:bg-subtle rounded"
          aria-label="next page"
        >
          <ChevronRight size={16} />
        </button>
      </div>
      <div className="flex-1 overflow-auto grid place-items-start p-4">
        {loadError ? (
          <div className="text-sm text-fg-muted">page render failed</div>
        ) : (
          <img
            src={url}
            alt={`page ${page}`}
            onError={() => setLoadError(true)}
            onLoad={() => setLoadError(false)}
            className="max-w-full shadow"
          />
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit (build still incomplete)**

```bash
git add frontend/src/components/ReviewMode/PdfViewer.tsx
git commit -m "feat(frontend): PdfViewer with page nav + lazy page-count probe"
```

---

### Task 17: FieldEditor component

**Files:**
- Create: `frontend/src/components/ReviewMode/FieldEditor.tsx`
- Create: `frontend/tests/unit/FieldEditor.test.tsx`

The FieldEditor reads field names from the **schema** (which lists the canonical fields and their types) and the **current value** from the review store. Plain text input for every type in M2A.

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/tests/unit/FieldEditor.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import FieldEditor from '../../src/components/ReviewMode/FieldEditor'

const SCHEMA = [
  { name: 'invoice_number', type: 'string', description: 'invoice no' },
  { name: 'total_amount', type: 'number', description: 'total' },
]

describe('FieldEditor', () => {
  it('renders a labelled input per schema field', () => {
    render(
      <FieldEditor
        schema={SCHEMA as any}
        values={{ invoice_number: 'INV-1', total_amount: 99.5 }}
        onChange={() => {}}
        onSave={() => {}}
        saving={false}
      />,
    )
    expect(screen.getByLabelText(/invoice_number/)).toHaveValue('INV-1')
    expect(screen.getByLabelText(/total_amount/)).toHaveValue('99.5')
  })

  it('calls onChange with field name and new value when input changes', async () => {
    const onChange = vi.fn()
    render(
      <FieldEditor
        schema={SCHEMA as any}
        values={{ invoice_number: '' }}
        onChange={onChange}
        onSave={() => {}}
        saving={false}
      />,
    )
    const input = screen.getByLabelText(/invoice_number/)
    await userEvent.type(input, 'INV-42')
    // last call has the most-recent text typed (testing-library does keystrokes)
    expect(onChange).toHaveBeenCalledWith('invoice_number', 'INV-42')
  })

  it('disables save button when saving=true', () => {
    render(
      <FieldEditor
        schema={SCHEMA as any}
        values={{}}
        onChange={() => {}}
        onSave={() => {}}
        saving={true}
      />,
    )
    expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled()
  })
})
```

- [ ] **Step 2: Run tests, confirm fail**

Run: `cd frontend && npm run test 2>&1 | tail -25`
Expected: 3 failures.

- [ ] **Step 3: Implement FieldEditor**

```tsx
// frontend/src/components/ReviewMode/FieldEditor.tsx
import type { ChangeEvent } from 'react'

interface SchemaField {
  name: string
  type: string
  description: string
  enum?: string[] | null
}

interface Props {
  schema: SchemaField[]
  values: Record<string, unknown>
  onChange: (name: string, value: string) => void
  onSave: () => void
  saving: boolean
}

export default function FieldEditor({ schema, values, onChange, onSave, saving }: Props) {
  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 border-b border-subtle font-heading text-sm uppercase tracking-wide text-fg-muted">
        Fields
      </header>
      <div className="flex-1 overflow-auto px-4 py-3 space-y-3">
        {schema.map((f) => {
          const current = values[f.name]
          const display = current == null ? '' : String(current)
          return (
            <div key={f.name} className="flex flex-col gap-1">
              <label
                htmlFor={`f-${f.name}`}
                className="font-mono text-xs text-fg-secondary"
              >
                {f.name} <span className="text-fg-muted">({f.type})</span>
              </label>
              <input
                id={`f-${f.name}`}
                type="text"
                value={display}
                onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(f.name, e.target.value)}
                className="bg-surface border border-subtle px-2 py-1 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-accent-primary"
              />
              {f.description && (
                <span className="text-xs text-fg-muted leading-tight">{f.description}</span>
              )}
            </div>
          )
        })}
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
}
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `cd frontend && npm run test`
Expected: 3 new pass + existing pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ReviewMode/FieldEditor.tsx frontend/tests/unit/FieldEditor.test.tsx
git commit -m "feat(frontend): FieldEditor with text input per schema field + save button"
```

---

### Task 18: ReviewMode container component

**Files:**
- Create: `frontend/src/components/ReviewMode/ReviewMode.tsx`

Composes PdfViewer + FieldEditor + an `← back` button. Loads the project's schema on mount so FieldEditor can render the right rows.

- [ ] **Step 1: Implement**

```tsx
// frontend/src/components/ReviewMode/ReviewMode.tsx
import { useEffect, useState } from 'react'
import { ChevronLeft } from 'lucide-react'

import { useReview } from '../../stores/review'
import { useDocs } from '../../stores/docs'

import FieldEditor from './FieldEditor'
import PdfViewer from './PdfViewer'

interface SchemaField {
  name: string
  type: string
  description: string
  enum?: string[] | null
}

async function fetchSchema(projectId: string): Promise<SchemaField[]> {
  // Direct GET so review mode loads without an agent round trip. The /schema
  // endpoint is added in Task 19.
  const r = await fetch(`/lab/projects/${projectId}/schema`)
  if (!r.ok) return []
  return r.json()
}

export default function ReviewMode() {
  const { activeProjectId, activeDocId, fields, setField, save, close, saving, err } = useReview()
  const { byProject } = useDocs()
  const [schema, setSchema] = useState<SchemaField[]>([])

  useEffect(() => {
    if (!activeProjectId) return
    void fetchSchema(activeProjectId).then(setSchema)
  }, [activeProjectId])

  const filename = activeProjectId
    ? byProject[activeProjectId]?.find((d) => d.doc_id === activeDocId)?.filename
    : undefined

  return (
    <div className="flex flex-col h-full bg-canvas text-fg-primary">
      <header className="flex items-center gap-3 px-4 py-2 border-b border-subtle">
        <button
          onClick={close}
          className="p-1 hover:bg-subtle rounded inline-flex items-center gap-1 text-sm"
          aria-label="back"
        >
          <ChevronLeft size={16} /> back
        </button>
        <span className="font-heading text-sm uppercase tracking-wide text-fg-muted">
          Review
        </span>
        <span className="font-mono text-sm">{filename ?? activeDocId}</span>
      </header>
      {err && (
        <div className="bg-subtle border-l-2 border-accent-danger px-4 py-2 text-sm">
          <span className="font-mono text-accent-danger">error</span>: {err}
        </div>
      )}
      <div className="flex-1 grid grid-cols-[60%_40%] min-h-0">
        <section className="border-r border-subtle min-h-0">
          <PdfViewer />
        </section>
        <section className="min-h-0">
          <FieldEditor
            schema={schema}
            values={fields}
            onChange={setField}
            onSave={save}
            saving={saving}
          />
        </section>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit (build still missing /schema endpoint — Task 19)**

```bash
git add frontend/src/components/ReviewMode/ReviewMode.tsx
git commit -m "feat(frontend): ReviewMode container — PDF + FieldEditor + back button"
```

---

### Task 19: Schema GET endpoint + final wiring

**Files:**
- Modify: `backend/app/api/routes/projects.py` — add `/lab/projects/{pid}/schema`
- Modify: `backend/tests/integration/test_lab_projects.py`

ReviewMode needs the schema as a list. Quick GET endpoint that returns `schema.json` content.

- [ ] **Step 1: Append failing test**

```python
async def test_get_project_schema(workspace: Path) -> None:
    from app.tools.schema import write_schema
    from app.schemas.schema_field import FieldType, SchemaField

    pid = await create_project(workspace, name="x")
    await write_schema(
        workspace,
        pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
        reason="seed",
        allow_structural=True,
    )
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/schema")
    assert r.status_code == 200
    fields = r.json()
    assert len(fields) == 1
    assert fields[0]["name"] == "invoice_no"


def test_get_project_schema_400_on_bad_pid() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/..%2Fetc/schema")
    assert r.status_code == 400
```

- [ ] **Step 2: Run, confirm 404**

Run: `cd backend && uv run pytest tests/integration/test_lab_projects.py -v`

- [ ] **Step 3: Add the endpoint**

Append to `backend/app/api/routes/projects.py`:

```python
import json
from app.workspace.paths import schema_path


@router.get("/lab/projects/{project_id}/schema")
async def get_project_schema(project_id: str) -> list[dict]:
    safe_project_id(project_id)
    settings = get_settings()
    sp = schema_path(settings.workspace_root, project_id)
    if not sp.exists():
        raise HTTPException(status_code=404, detail="schema_not_found")
    return json.loads(sp.read_text())
```

(`json` and `HTTPException` are already imported by Task 9 — no duplicate import needed.)

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_lab_projects.py -v`
Expected: 7 passed (5 from Task 9 + 2 new).

- [ ] **Step 5: Frontend sanity build**

```
cd frontend && npm run build 2>&1 | tail -5
```
Expected: success now that the /schema endpoint exists.

```
cd frontend && npm run test
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/projects.py backend/tests/integration/test_lab_projects.py
git commit -m "feat(api): GET /lab/projects/{pid}/schema for review mode"
```

---

## Phase 6 — Integration polish + e2e

### Task 20: Refresh doc list after save

**Files:**
- Modify: `frontend/src/stores/review.ts`

After saving reviewed, the doc-list status badge should flip to `reviewed`. The simplest path: after a successful save, ask the docs store to refresh.

- [ ] **Step 1: Update review store**

In `frontend/src/stores/review.ts`, modify the `save` method to also refresh docs:

```ts
import { useDocs } from './docs'

// inside the save method, after `await saveReviewed(...)`:
      await saveReviewed(activeProjectId, activeDocId, payload)
      // refresh the doc-list status so the badge flips to "reviewed"
      void useDocs.getState().refresh(activeProjectId)
      set({ saving: false })
```

(Importing `useDocs` from another store is fine in Zustand.)

- [ ] **Step 2: Manual smoke (no test changes)**

The vitest tests don't exercise the cross-store call; integration via Playwright in Task 22.

```
cd frontend && npm run build 2>&1 | tail -5
```
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/review.ts
git commit -m "feat(frontend): refresh doc list after saving reviewed"
```

---

### Task 21: SKILL.md hint about reviewed examples

**Files:**
- Modify: `backend/app/skills/emerge_extractor.md`

Now that the agent has `save_reviewed` / `list_reviewed` / `get_reviewed` / `get_prediction`, the skill should mention them so the model uses them (instead of e.g. dumping a fix into chat without persisting).

- [ ] **Step 1: Append section**

Add this to `backend/app/skills/emerge_extractor.md` near the top of the "## Tool usage hints" block (after the `extract_batch` hint):

```markdown
- After the user corrects a value (e.g. "buyer_name should be ACME Sdn Bhd"),
  call `get_prediction` to load the latest draft, apply the correction in
  memory, then call `save_reviewed` to persist it as ground truth. Don't
  just acknowledge in chat without saving — the user expects their
  correction to flow into the eval set.
- `list_reviewed` tells you how many ground-truth examples exist in a
  project. Use this when the user asks "how am I doing" or before
  suggesting `/eval` (which needs ≥1 reviewed example to be useful).
```

- [ ] **Step 2: Commit (no tests; SKILL.md is content)**

```bash
git add backend/app/skills/emerge_extractor.md
git commit -m "feat(skill): tell agent to save_reviewed when user corrects values"
```

---

### Task 22: Playwright e2e — review save round-trip

**Files:**
- Modify: `backend/app/api/routes/_test_stubs.py` — add stub for review-mode dependencies if needed
- Create: `frontend/tests/e2e/review-mode.spec.ts`

The existing `EMERGE_TEST_MODE=1` only stubs `/lab/chat`. For review mode the real backend routes work fine (no LLM calls); we just need a project + doc + draft prediction pre-populated. Use Python helpers via a test fixture script.

- [ ] **Step 1: Create a fixture seeder script**

```python
# backend/tests/e2e_seed.py
"""Seed a project + doc + prediction so the e2e review-mode test has data.

Invoked from playwright config's webServer setup before launch.
"""
import asyncio
import os
from pathlib import Path

from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.schema import write_schema
from app.schemas.schema_field import FieldType, SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir


async def main() -> None:
    workspace = Path(os.environ.get("EMERGE_WORKSPACE_ROOT", "./.tmp_workspace"))
    workspace.mkdir(parents=True, exist_ok=True)
    pid = await create_project(workspace, name="e2e-test")
    await write_schema(
        workspace,
        pid,
        [
            SchemaField(name="invoice_number", type=FieldType.STRING, description="Invoice no"),
            SchemaField(name="total_amount", type=FieldType.NUMBER, description="Total"),
        ],
        reason="e2e seed",
        allow_structural=True,
    )
    fixture = Path(__file__).parent / "fixtures" / "invoice_sample.pdf"
    did = await upload_doc(workspace, pid, fixture.read_bytes(), "sample.pdf")
    pdir = predictions_draft_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        pdir / f"{did}.json",
        {"entities": [{"invoice_number": "DRAFT-1", "total_amount": 100.0}]},
    )
    print(f"SEEDED pid={pid} did={did}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Update playwright.config.ts to seed before tests**

Modify `frontend/playwright.config.ts` so the backend webServer command seeds first:

```ts
webServer: [
  {
    command: 'rm -rf .tmp_workspace && EMERGE_TEST_MODE=1 EMERGE_WORKSPACE_ROOT=./.tmp_workspace uv --directory ../backend run python -m tests.e2e_seed && EMERGE_TEST_MODE=1 EMERGE_WORKSPACE_ROOT=./.tmp_workspace uv --directory ../backend run uvicorn app.main:app --port 8000',
    url: 'http://localhost:8000/healthz',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
],
```

- [ ] **Step 3: Write the e2e test**

```ts
// frontend/tests/e2e/review-mode.spec.ts
import { test, expect } from '@playwright/test'

test('open a doc, edit a field, save, badge flips to reviewed', async ({ page }) => {
  await page.goto('/')

  // wait for project to load + click it
  await expect(page.getByText('e2e-test')).toBeVisible({ timeout: 10_000 })
  await page.getByRole('button', { name: 'e2e-test' }).click()

  // doc list shows up in right pane with "draft" badge
  await expect(page.getByText('sample.pdf')).toBeVisible()
  await expect(page.getByText('draft')).toBeVisible()

  // click the doc to enter review mode
  await page.getByRole('button', { name: /sample\.pdf/ }).click()

  // FieldEditor renders: invoice_number with value DRAFT-1
  const invoiceInput = page.getByLabel(/invoice_number/)
  await expect(invoiceInput).toHaveValue('DRAFT-1')

  // edit and save
  await invoiceInput.fill('CONFIRMED-1')
  await page.getByRole('button', { name: /save reviewed/i }).click()

  // wait for save to complete, then back out
  await expect(page.getByRole('button', { name: /save reviewed/i })).toBeEnabled({ timeout: 10_000 })
  await page.getByRole('button', { name: /back/i }).click()

  // doc list shows "reviewed" badge now
  await expect(page.getByText('reviewed')).toBeVisible()
})
```

- [ ] **Step 4: Run e2e**

```
cd frontend && npx playwright test review-mode.spec.ts 2>&1 | tail -10
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/e2e_seed.py frontend/playwright.config.ts frontend/tests/e2e/review-mode.spec.ts
git commit -m "test(e2e): review save round-trip — open doc, edit field, save, badge flips"
```

---

## Acceptance check

```
cd backend && uv run pytest -q
# expect ~120 passed (90 baseline + ~30 added across M2A)

cd frontend && npm run test
# expect ~10 passed (6 baseline + 4 added)

cd frontend && npm run e2e
# expect 2 passed (walking-skeleton + review-mode)
```

Manual smoke (with real `GOOGLE_API_KEY` + `CLAUDE_CODE_OAUTH_TOKEN` in `backend/.env`):

```
cd backend && uv run uvicorn app.main:app --port 8080 --reload
cd frontend && npm run dev -- --port 5172
```

Open http://localhost:5172/, click an existing project (or create one via chat), the right pane shows the project's docs with status badges. Click a doc → review mode opens; PDF on the left, fields on the right populated from the latest draft. Edit a field, click "save reviewed", click "back" → doc badge flips to `reviewed`. The on-disk file `backend/workspace/{pid}/reviewed/{did}.json` exists with the corrected entities.

---

## Spec coverage check

| Spec section | Covered by |
|---|---|
| §3.2 reviewed/{doc_id}.json filesystem layout | Tasks 1, 3 |
| §5.4 save_reviewed / list_reviewed | Tasks 3, 4 |
| §5.4 source: 'manual'\|'feedback' | Task 2 |
| §6.3 risk gates — reviewed save not gated | save_reviewed has no gate flag (intentional — corrections aren't structural) |
| §8.2 review mode (PDF + JSON editor) | Tasks 16, 17, 18 |
| §8.2 back button returning to three-pane | Task 18, 14 |
| §8.4 inline comments | DEFERRED — M2B |
| §8.3 field controls auto-derived from type | DEFERRED — M2B (text input only in M2A) |
| §10 testing layers — tool unit / route integration / e2e | Tasks 3,4,5,7,8,9,13,17,22 |

---

## Self-Review notes

- M2A intentionally excludes _evidence click-to-page (frontend doesn't even fetch _evidence). The `_source_page` plumbing comes in M2B with the schema-typed controls.
- The `fetchSchema` helper inside `ReviewMode.tsx` could be promoted to a `useSchema` store hook, but with one consumer per session that's premature.
- Multi-entity docs (one PDF with N invoices) are NOT handled in M2A — `fields` is `entities[0]`. Add multi-entity tab/scroll in a later milestone if real docs surface this.
- The doc-list status badge uses 3 levels (`reviewed` / `draft` / `pending`) but the underlying `has_prediction` boolean doesn't distinguish "draft was rerun and now stale relative to schema". That's a stale-vs-fresh concern for M3+.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-09-m2a-reviewed-examples.md`. Two execution options:

**1. Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
