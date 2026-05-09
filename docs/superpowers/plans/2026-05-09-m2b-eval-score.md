# M2B — Eval (score + /eval) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute per-field correctness (precision / recall / F1) by comparing the latest draft predictions against reviewed ground truth, persist a metrics snapshot, surface the score in chat via a `/eval` command, and clear two minor M2A debts (DocStatus naming + multi-page PDF probe).

**Architecture:** New `score` pure function lives in `app/tools/score.py` and computes per-field TP/FP/FN by exact string match (case-sensitive, after stringification). It iterates over reviewed docs only — unreviewed docs are not graded. Results land in `metrics/eval_{ts}.json`. A new `mcp__emerge_tools__score` exposes it to the agent, plus a thin POST `/lab/projects/{pid}/eval` route the frontend can call directly. SKILL.md teaches the agent that `/eval` runs `score` then summarizes. No frontend "metrics panel" yet — agent's chat summary is the deliverable. Polish work covers DocStatus rename + a fix for the page-probe bug.

**Tech Stack:** No new tech. FastAPI + pydantic v2 backend; vitest only for the polish-side frontend test.

**Spec reference:** `docs/superpowers/specs/2026-05-08-agent-native-design.md` §5.3 (`score` tool), §11 M2 deliverables. Out of scope: `metrics/eval_{ts}.json` UI viewer (deferred to M2C alongside autoresearch progress event stream); type-derived field controls (deferred to M2C); `_source_page` click-to-page (deferred to M2C); inline `_notes` UI (deferred to M2C — model already exists from M2A).

---

## Scope cuts (deferred)

- **Metrics UI panel** — agent's chat summary is sufficient for v1; the spec's right-pane 📊 toggle is M2C-prep.
- **Per-field score chip in DocList** — would force a 2-store dependency (`metrics` × `docs`); save for M2C.
- **Field-aware comparison** (number tolerance, date format normalization, enum case-insensitivity) — exact match for v1. Description-as-code already pushes models toward canonical formats; tolerance is a M2C polish.
- **Score history / timeseries** — `metrics/eval_{ts}.json` files accumulate naturally on disk; a "score over time" chart is M2C.

---

## File structure

### Backend (`backend/`)

```
backend/app/
├── tools/
│   ├── score.py             # NEW — score(predictions, reviewed) → ScoreResult, persist
│   └── __init__.py          # MCP register `score` tool (MODIFIED)
├── schemas/
│   └── score.py             # NEW — ScoreResult, FieldScore models
├── workspace/
│   └── paths.py             # add metrics_dir, metrics_path (MODIFIED)
└── api/routes/
    └── eval.py              # NEW — POST /lab/projects/{pid}/eval
└── skills/
    └── emerge_extractor.md  # /eval intent hint (MODIFIED)
└── main.py                  # mount eval router (MODIFIED)

backend/tests/unit/
├── test_paths.py            # add metrics_path tests (MODIFIED)
├── test_score_schema.py     # NEW
├── test_tool_score.py       # NEW
└── test_tool_registration.py # extended set (MODIFIED)
backend/tests/integration/
└── test_lab_eval.py         # NEW
```

### Frontend (`frontend/`)

```
src/
├── types/review.ts          # rename DocStatus 'predicted' → 'draft' (MODIFIED)
├── components/
│   ├── DocList/DocItem.tsx  # adjust to renamed enum (MODIFIED)
│   └── ReviewMode/PdfViewer.tsx  # iterate page-probe loop (MODIFIED)
tests/unit/DocItem.test.tsx  # update test labels (MODIFIED)
```

---

## Conventions

- TDD throughout. Each backend task lands a failing test first.
- Backend tests: `cd backend && uv run pytest -v`. Frontend: `cd frontend && npm run test`.
- All HTTP routes go through `safe_project_id` from M1.
- Atomic write via `atomic_write_json` for any file persisted under a project.
- M2A's review-mode flow stays unchanged — this plan only ADDS routes/tools/files; the only frontend modifications are for the 2 polish items.

---

## Task index

Phase 1: backend score core (1–6) — ~120 min
Phase 2: routes + agent integration (7–10) — ~80 min
Phase 3: frontend polish (11–12) — ~30 min
Phase 4: e2e (13) — ~30 min

---

## Phase 1 — Backend score core

### Task 1: `metrics_dir` / `metrics_path` helpers

**Files:**
- Modify: `backend/app/workspace/paths.py`
- Modify: `backend/tests/unit/test_paths.py`

Per spec §3.2 each project has `metrics/eval_{ts}.json` files; we add the two helpers consistent with the M1 pattern.

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/unit/test_paths.py`:

```python
def test_metrics_dir(workspace: Path) -> None:
    from app.workspace.paths import metrics_dir
    assert metrics_dir(workspace, "p_abc") == workspace / "p_abc" / "metrics"


def test_metrics_path(workspace: Path) -> None:
    from app.workspace.paths import metrics_path
    assert metrics_path(workspace, "p_abc", "eval_2026-05-09T00-00-00Z") == workspace / "p_abc" / "metrics" / "eval_2026-05-09T00-00-00Z.json"
```

- [ ] **Step 2: Run, verify failure**

Run: `cd backend && uv run pytest tests/unit/test_paths.py -v`
Expected: ImportError on the new helpers.

- [ ] **Step 3: Append helpers**

Append to `backend/app/workspace/paths.py`:

```python
def metrics_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "metrics"


def metrics_path(workspace: Path, project_id: str, name: str) -> Path:
    return metrics_dir(workspace, project_id) / f"{name}.json"
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/unit/test_paths.py -v`
Expected: 15 passed (13 from prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace/paths.py backend/tests/unit/test_paths.py
git commit -m "feat(workspace): metrics_dir / metrics_path helpers"
```

---

### Task 2: `FieldScore` + `ScoreResult` schemas

**Files:**
- Create: `backend/app/schemas/score.py`
- Create: `backend/tests/unit/test_score_schema.py`

Per spec §5.3 the score envelope returns `{f1, per_field, errors[]}`. The shape committed here is what gets persisted on disk and surfaced over the wire — keep it simple.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_score_schema.py
import pytest
from pydantic import ValidationError

from app.schemas.score import FieldScore, ScoreResult


def test_field_score_minimal() -> None:
    f = FieldScore(field="invoice_no", tp=8, fp=1, fn=1, support=10, precision=8/9, recall=8/10, f1=0.8421052631578948)
    assert f.field == "invoice_no"
    assert f.support == 10


def test_score_result_aggregates() -> None:
    r = ScoreResult(
        n_docs=2,
        n_reviewed=2,
        macro_f1=0.85,
        per_field=[
            FieldScore(field="a", tp=1, fp=0, fn=0, support=1, precision=1.0, recall=1.0, f1=1.0),
        ],
        errors=[],
        ts="2026-05-09T00-00-00Z",
        schema_field_count=1,
    )
    assert r.n_docs == 2
    assert r.macro_f1 == 0.85
    assert len(r.per_field) == 1


def test_score_result_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        ScoreResult(
            n_docs=0, n_reviewed=0, macro_f1=0.0,
            per_field=[], errors=[], ts="x", schema_field_count=0,
            unknown_field=1,
        )


def test_field_score_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        FieldScore(field="x", tp=0, fp=0, fn=0, support=0, precision=0.0, recall=0.0, f1=0.0, unknown=1)
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_score_schema.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/schemas/score.py
from pydantic import BaseModel, ConfigDict


class FieldScore(BaseModel):
    """Per-field accuracy across all reviewed docs in this run."""
    model_config = ConfigDict(extra="forbid")

    field: str
    tp: int    # predicted == reviewed (both present, equal)
    fp: int    # predicted but not equal to reviewed (or reviewed missing this field)
    fn: int    # reviewed has the field but prediction omits it
    support: int  # number of reviewed docs containing this field
    precision: float
    recall: float
    f1: float


class ScoreResult(BaseModel):
    """Outcome of one /eval run."""
    model_config = ConfigDict(extra="forbid")

    n_docs: int                 # total docs in project
    n_reviewed: int             # docs with both prediction AND reviewed file (the graded subset)
    macro_f1: float             # mean of per-field f1
    per_field: list[FieldScore]
    errors: list[str]           # human-readable issues (e.g. "doc d_xyz has reviewed but no prediction")
    ts: str                     # ISO-8601 with colons replaced by `-` so it's filename-safe
    schema_field_count: int     # snapshot of `len(schema)` at eval time
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_score_schema.py -v`
Expected: 4 passed.

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: 124 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/score.py backend/tests/unit/test_score_schema.py
git commit -m "feat(schemas): FieldScore + ScoreResult models"
```

---

### Task 3: `score` core function (compute, no persistence)

**Files:**
- Create: `backend/app/tools/score.py`
- Create: `backend/tests/unit/test_tool_score.py`

Score logic, expressed as a pure function:

- For each reviewed doc, take `entities[0]` from both reviewed and the corresponding prediction. (Multi-entity is M2C-deferred.)
- For each field in `schema`:
  - reviewed has field, prediction matches → TP
  - reviewed has field, prediction value differs (or prediction lacks the field) → FN; if prediction has a non-empty value that disagrees, also FP
  - reviewed lacks field but prediction has a non-empty value → FP
  - both lack the field → not counted
- `precision = tp / (tp + fp)` (or 0 if denominator 0)
- `recall = tp / (tp + fn)` (or 0)
- `f1 = 2 * p * r / (p + r)` (or 0)
- `macro_f1 = mean(per_field.f1)`

Comparison is **exact string match** after `str(value)`. Trailing whitespace stripped. None and missing key both treated as "absent". Empty string "" treated as "absent" too.

This task implements only `score(...)` returning a `ScoreResult` — persistence comes in T4.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_tool_score.py
from pathlib import Path

import pytest

from app.schemas.schema_field import FieldType, SchemaField
from app.tools.score import score


def _f(name: str, t: FieldType = FieldType.STRING) -> SchemaField:
    return SchemaField(name=name, type=t, description="d")


SCHEMA = [_f("invoice_no"), _f("buyer_name"), _f("total")]


def test_score_perfect_match() -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]}
    predictions = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]}
    r = score(SCHEMA, predictions, reviewed)
    assert r.n_reviewed == 1
    assert r.macro_f1 == 1.0
    for fs in r.per_field:
        assert fs.tp == 1
        assert fs.fp == 0
        assert fs.fn == 0
        assert fs.f1 == 1.0


def test_score_one_wrong_value() -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]}
    predictions = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "WRONG", "total": 100}]}
    r = score(SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in r.per_field}
    assert by_field["invoice_no"].f1 == 1.0
    assert by_field["buyer_name"].f1 == 0.0  # 0 tp, 1 fp, 1 fn → 0
    assert by_field["total"].f1 == 1.0
    assert r.macro_f1 == pytest.approx(2 / 3, rel=0.01)


def test_score_missing_prediction_field() -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]}
    predictions = {"d_a": [{"invoice_no": "INV-1", "total": 100}]}  # buyer_name missing
    r = score(SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in r.per_field}
    bn = by_field["buyer_name"]
    assert bn.tp == 0
    assert bn.fn == 1   # reviewed had it; prediction omitted
    assert bn.fp == 0   # prediction said nothing → not a wrong claim


def test_score_extra_prediction_field() -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1"}]}
    predictions = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "GUESS"}]}
    r = score(SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in r.per_field}
    bn = by_field["buyer_name"]
    assert bn.fp == 1   # prediction asserted a value reviewed never had
    assert bn.fn == 0
    assert bn.tp == 0


def test_score_skips_doc_without_prediction() -> None:
    reviewed = {"d_a": [{"invoice_no": "X"}], "d_b": [{"invoice_no": "Y"}]}
    predictions = {"d_a": [{"invoice_no": "X"}]}  # d_b missing prediction
    r = score(SCHEMA, predictions, reviewed)
    assert r.n_reviewed == 1
    assert any("d_b" in e for e in r.errors)


def test_score_empty_reviewed_returns_zeros() -> None:
    r = score(SCHEMA, {}, {})
    assert r.n_reviewed == 0
    assert r.macro_f1 == 0.0
    for fs in r.per_field:
        assert fs.tp == fs.fp == fs.fn == 0


def test_score_treats_empty_string_and_none_as_absent() -> None:
    reviewed = {"d_a": [{"invoice_no": "X", "buyer_name": ""}]}
    predictions = {"d_a": [{"invoice_no": "X", "buyer_name": None}]}
    r = score(SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in r.per_field}
    bn = by_field["buyer_name"]
    # Both absent → no tp, no fp, no fn (neither side made a claim)
    assert bn.tp == bn.fp == bn.fn == 0


def test_score_strings_compared_after_strip_and_str_cast() -> None:
    reviewed = {"d_a": [{"total": 100}]}
    predictions = {"d_a": [{"total": "100 "}]}  # trailing space, str type
    r = score(SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in r.per_field}
    assert by_field["total"].tp == 1   # 100 == "100" after str+strip
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_score.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/tools/score.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas.schema_field import SchemaField
from app.schemas.score import FieldScore, ScoreResult


def _absent(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def _eq(a: Any, b: Any) -> bool:
    """Exact match after str()+strip()."""
    return str(a).strip() == str(b).strip()


def _safe_div(a: float, b: float) -> float:
    return 0.0 if b == 0 else a / b


def _now_filename_ts() -> str:
    # ISO-8601 with colons replaced; safe as a filename component.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def score(
    schema: list[SchemaField],
    predictions: dict[str, list[dict[str, Any]]],
    reviewed: dict[str, list[dict[str, Any]]],
) -> ScoreResult:
    """Score predictions vs reviewed for each field defined in schema.

    Both `predictions` and `reviewed` are keyed by doc_id and value is the
    `entities` list (only entity 0 is graded for v1).

    Docs in `reviewed` but missing from `predictions` are recorded as errors
    and skipped.
    """
    errors: list[str] = []
    # Init per-field counters
    counts = {f.name: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for f in schema}

    n_reviewed_graded = 0
    for doc_id, rev_entities in reviewed.items():
        if doc_id not in predictions:
            errors.append(f"doc {doc_id} has reviewed but no prediction")
            continue
        rev = rev_entities[0] if rev_entities else {}
        pred_entities = predictions[doc_id]
        pred = pred_entities[0] if pred_entities else {}
        n_reviewed_graded += 1

        for f in schema:
            r_val = rev.get(f.name)
            p_val = pred.get(f.name)
            r_absent = _absent(r_val)
            p_absent = _absent(p_val)

            if r_absent and p_absent:
                continue   # neither side made a claim
            if not r_absent:
                counts[f.name]["support"] += 1

            if not r_absent and not p_absent:
                if _eq(r_val, p_val):
                    counts[f.name]["tp"] += 1
                else:
                    counts[f.name]["fp"] += 1
                    counts[f.name]["fn"] += 1
            elif r_absent and not p_absent:
                counts[f.name]["fp"] += 1
            elif not r_absent and p_absent:
                counts[f.name]["fn"] += 1

    per_field: list[FieldScore] = []
    for f in schema:
        c = counts[f.name]
        precision = _safe_div(c["tp"], c["tp"] + c["fp"])
        recall = _safe_div(c["tp"], c["tp"] + c["fn"])
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_field.append(FieldScore(
            field=f.name, tp=c["tp"], fp=c["fp"], fn=c["fn"],
            support=c["support"], precision=precision, recall=recall, f1=f1,
        ))

    macro_f1 = _safe_div(sum(fs.f1 for fs in per_field), len(per_field))

    return ScoreResult(
        n_docs=len(reviewed) + sum(1 for d in predictions if d not in reviewed),
        n_reviewed=n_reviewed_graded,
        macro_f1=macro_f1,
        per_field=per_field,
        errors=errors,
        ts=_now_filename_ts(),
        schema_field_count=len(schema),
    )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_score.py -v`
Expected: 8 passed.

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: 132 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/score.py backend/tests/unit/test_tool_score.py
git commit -m "feat(tools): score(schema, predictions, reviewed) -> ScoreResult"
```

---

### Task 4: `run_eval` — orchestrator that loads + scores + persists

**Files:**
- Modify: `backend/app/tools/score.py` (append `run_eval`)
- Modify: `backend/tests/unit/test_tool_score.py` (append integration-style tests)

`run_eval(workspace, project_id)` reads `schema.json`, `reviewed/*.json`, `predictions/_draft/*.json`, calls `score(...)`, persists the result to `metrics/eval_{ts}.json`, and returns the `ScoreResult`. This is the layer the route + the agent both call.

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/unit/test_tool_score.py`:

```python
import json

from app.schemas.reviewed import ReviewedSource
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.tools.score import run_eval
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir


async def test_run_eval_writes_metrics_file(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await write_schema(
        workspace, pid, [_f("invoice_no")], reason="seed", allow_structural=True,
    )
    pdf = b"%PDF-1.4\n%%EOF\n"
    did = await upload_doc(workspace, pid, pdf, "a.pdf")
    pdir = predictions_draft_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pdir / f"{did}.json", {"entities": [{"invoice_no": "INV-1"}]})
    await save_reviewed(
        workspace, pid, did, entities=[{"invoice_no": "INV-1"}], source=ReviewedSource.MANUAL,
    )

    result = await run_eval(workspace, pid)
    assert result.n_reviewed == 1
    assert result.macro_f1 == 1.0

    metrics_files = list((workspace / pid / "metrics").glob("eval_*.json"))
    assert len(metrics_files) == 1
    saved = json.loads(metrics_files[0].read_text())
    assert saved["macro_f1"] == 1.0


async def test_run_eval_with_no_reviewed_returns_zero_macro(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await write_schema(
        workspace, pid, [_f("invoice_no")], reason="seed", allow_structural=True,
    )
    result = await run_eval(workspace, pid)
    assert result.n_reviewed == 0
    assert result.macro_f1 == 0.0
    # zeros file still persisted — useful for tracking "we tried"
    assert (workspace / pid / "metrics").is_dir()
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_score.py -v`
Expected: ImportError on `run_eval`.

- [ ] **Step 3: Append `run_eval`**

Append to `backend/app/tools/score.py`:

```python
import json
from pathlib import Path

from app.schemas.schema_field import SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    metrics_dir,
    metrics_path,
    predictions_draft_dir,
    reviewed_dir,
    schema_path,
)


async def run_eval(workspace: Path, project_id: str) -> ScoreResult:
    """Load schema + predictions + reviewed, score, persist, return result."""
    schema_blob = json.loads(schema_path(workspace, project_id).read_text())
    schema = [SchemaField(**f) for f in schema_blob]

    pdir = predictions_draft_dir(workspace, project_id)
    predictions: dict[str, list] = {}
    if pdir.exists():
        for p in pdir.glob("*.json"):
            blob = json.loads(p.read_text())
            predictions[p.stem] = blob.get("entities", [])

    rdir = reviewed_dir(workspace, project_id)
    reviewed: dict[str, list] = {}
    if rdir.exists():
        for r in rdir.glob("*.json"):
            blob = json.loads(r.read_text())
            reviewed[r.stem] = blob.get("entities", [])

    result = score(schema, predictions, reviewed)

    # persist
    async with project_lock(workspace, project_id):
        metrics_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            metrics_path(workspace, project_id, f"eval_{result.ts}"),
            result.model_dump(mode="json"),
        )
    return result
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_score.py -v`
Expected: 10 passed (8 prior + 2 new).

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: 134 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/score.py backend/tests/unit/test_tool_score.py
git commit -m "feat(tools): run_eval orchestrates score+persist for a project"
```

---

### Task 5: Register `run_eval` as `score` MCP tool

**Files:**
- Modify: `backend/app/tools/__init__.py`
- Modify: `backend/tests/unit/test_tool_registration.py`

The agent calls this via `mcp__emerge_tools__score`. Returns the result as a string (str(...) like the other tools).

- [ ] **Step 1: Update test_tool_registration**

Modify the `expected` set in `backend/tests/unit/test_tool_registration.py`:

```python
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
        "save_reviewed",
        "list_reviewed",
        "get_reviewed",
        "get_prediction",
        # M2B addition
        "score",
    }
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`
Expected: assertion shows `{"score"}` missing.

- [ ] **Step 3: Register the tool**

In `backend/app/tools/__init__.py`, add to imports near the other `from app.tools import ...` lines:

```python
from app.tools import score as score_mod
```

Inside `build_emerge_mcp(...)`, after the existing `t_get_prediction` definition and before `return create_sdk_mcp_server(...)`:

```python
    @tool(
        "score",
        "Compute precision/recall/F1 by comparing draft predictions against reviewed examples. Persists a metrics snapshot under metrics/eval_{ts}.json. Returns ScoreResult.",
        {"project_id": str},
    )
    async def t_score(args: dict[str, Any]) -> dict[str, Any]:
        result = await score_mod.run_eval(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": str(result.model_dump(mode='json'))}]}
```

Then extend the `tools=[...]` list:

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
            t_score,
        ],
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`
Expected: 1 passed.

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: 134 still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/__init__.py backend/tests/unit/test_tool_registration.py
git commit -m "feat(tools): register score MCP tool"
```

---

### Task 6: SKILL.md hint for `/eval`

**Files:**
- Modify: `backend/app/skills/emerge_extractor.md`

Add an entry to the Tool usage hints section instructing the agent to call `score` when the user types `/eval` or asks "how am I doing".

- [ ] **Step 1: Edit**

In `backend/app/skills/emerge_extractor.md`, find the `## Tool usage hints` block (after the `extract_batch` and `list_reviewed` bullets). Append:

```markdown
- When the user types `/eval` (or asks "how am I doing", "what's the
  score"), call the `score` tool. It needs only `project_id`. The result
  has `macro_f1`, `per_field` (each with precision/recall/f1/support),
  `n_reviewed`, and `errors`. Summarize in chat:
  - lead with `macro_f1` rounded to 2 decimals
  - call out the lowest-f1 field as the "where to focus" pointer
  - if `n_reviewed` is 0, gently prompt the user to review some docs first
  - if `errors` non-empty, surface them
- Run `score` only when the project has reviewed examples (`list_reviewed`
  returns non-empty). With zero reviewed, score returns macro_f1=0.0
  which is misleading — better to ask the user to review a few docs first.
```

Also update the slash-commands table — locate the line for `/eval` and remove the `(M2+)` annotation:

```markdown
- `/eval` — compute precision/recall/F1 vs reviewed examples; persists a
  metrics snapshot.
```

- [ ] **Step 2: Verify**

Read the file and confirm the additions are in the right section.

- [ ] **Step 3: Commit**

```bash
git add backend/app/skills/emerge_extractor.md
git commit -m "feat(skill): /eval intent — call score tool, summarize macro_f1 + worst field"
```

---

## Phase 2 — HTTP route

### Task 7: POST `/lab/projects/{pid}/eval`

**Files:**
- Create: `backend/app/api/routes/eval.py`
- Modify: `backend/app/main.py` — mount router
- Create: `backend/tests/integration/test_lab_eval.py`

The frontend can hit this directly (no agent round trip) when wiring buttons later. For M2B, only the route + tests; no frontend button.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/integration/test_lab_eval.py
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.reviewed import ReviewedSource
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.schemas.schema_field import FieldType, SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir


async def test_post_eval_returns_score(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    pdf = b"%PDF-1.4\n%%EOF\n"
    did = await upload_doc(workspace, pid, pdf, "a.pdf")
    pdir = predictions_draft_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pdir / f"{did}.json", {"entities": [{"x": "yes"}]})
    await save_reviewed(workspace, pid, did, entities=[{"x": "yes"}], source=ReviewedSource.MANUAL)

    client = TestClient(app)
    r = client.post(f"/lab/projects/{pid}/eval")
    assert r.status_code == 200
    body = r.json()
    assert body["macro_f1"] == 1.0
    assert body["n_reviewed"] == 1


def test_post_eval_400_on_bad_pid() -> None:
    client = TestClient(app)
    r = client.post("/lab/projects/p_INVALIDPATH/eval")
    assert r.status_code == 400
```

- [ ] **Step 2: Run, confirm 404**

Run: `cd backend && uv run pytest tests/integration/test_lab_eval.py -v`
Expected: not mounted yet.

- [ ] **Step 3: Implement**

```python
# backend/app/api/routes/eval.py
from fastapi import APIRouter

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.tools.score import run_eval


router = APIRouter()


@router.post("/lab/projects/{project_id}/eval")
async def post_eval(project_id: str) -> dict:
    safe_project_id(project_id)
    settings = get_settings()
    result = await run_eval(settings.workspace_root, project_id)
    return result.model_dump(mode="json")
```

- [ ] **Step 4: Mount in main.py**

Add to `backend/app/main.py` next to the other route imports:

```python
from app.api.routes import eval as eval_route
```

And alongside the other `app.include_router` calls:

```python
app.include_router(eval_route.router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_lab_eval.py -v`
Expected: 2 passed.

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: 136 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/eval.py backend/app/main.py backend/tests/integration/test_lab_eval.py
git commit -m "feat(api): POST /lab/projects/{pid}/eval"
```

---

## Phase 3 — Polish

### Task 8: Rename DocStatus 'predicted' → 'draft'

**Files:**
- Modify: `frontend/src/types/review.ts`
- Modify: `frontend/src/components/DocList/DocItem.tsx`
- Modify: `frontend/tests/unit/DocItem.test.tsx`

M2A reviewer flagged: enum value `'predicted'` rendered as label `'draft'`. Single source of truth.

- [ ] **Step 1: Update review.ts**

In `frontend/src/types/review.ts`, change:

```ts
export type DocStatus = 'reviewed' | 'predicted' | 'pending'
```

to:

```ts
export type DocStatus = 'reviewed' | 'draft' | 'pending'
```

And in the `docStatus` function:

```ts
export function docStatus(d: DocSummary): DocStatus {
  if (d.has_reviewed) return 'reviewed'
  if (d.has_prediction) return 'draft'
  return 'pending'
}
```

- [ ] **Step 2: Update DocItem.tsx**

In `frontend/src/components/DocList/DocItem.tsx`, replace `'predicted'` with `'draft'`. The badge label can be derived directly from `status` now, eliminating the conditional remap:

```tsx
import { docStatus, type DocSummary } from '../../types/review'

interface Props {
  doc: DocSummary
  onClick: (docId: string) => void
}

export default function DocItem({ doc, onClick }: Props) {
  const status = docStatus(doc)
  const badgeClass =
    status === 'reviewed' ? 'text-accent-success'
    : status === 'draft' ? 'text-accent-info'
    : 'text-fg-muted'
  return (
    <button
      onClick={() => onClick(doc.doc_id)}
      className="w-full text-left px-3 py-2 hover:bg-subtle border-b border-subtle"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-sm truncate">{doc.filename}</span>
        <span className={`text-xs uppercase tracking-wide ${badgeClass}`}>{status}</span>
      </div>
      <span className="text-xs text-fg-muted">{doc.page_count} page{doc.page_count !== 1 ? 's' : ''}</span>
    </button>
  )
}
```

(Replaces the variable `badge` with directly using `status`.)

- [ ] **Step 3: Tests still pass**

The tests use case-insensitive regexes (`/draft/i`, `/reviewed/i`, `/pending/i`) so they should still pass without modification. Verify:

```
cd frontend && npm run test
```
Expected: 13 passed.

- [ ] **Step 4: Build**

```
cd frontend && npm run build 2>&1 | tail -5
```
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/review.ts frontend/src/components/DocList/DocItem.tsx
git commit -m "refactor(frontend): rename DocStatus 'predicted' → 'draft' (matches label)"
```

---

### Task 9: PDF page-probe loop

**Files:**
- Modify: `frontend/src/components/ReviewMode/PdfViewer.tsx`

M2A's PdfViewer probes only `page + 1` once per page change. Boeing Distribution is 2 pages but the probe never fired because `pageCount` started at 1 and the user never navigated. Fix: probe forward in a loop until 404, capping at e.g. 50 to avoid runaway. Run once on mount per `(activeProjectId, activeDocId)` pair.

- [ ] **Step 1: Replace the probe effect**

In `frontend/src/components/ReviewMode/PdfViewer.tsx`, replace the existing `useEffect` for page probing with:

```tsx
  // Probe forward from page 1 once per (project, doc) pair so pageCount reflects
  // the real page count even before the user navigates. Cap the probe so a
  // pathological PDF doesn't generate hundreds of HEAD requests on mount.
  useEffect(() => {
    if (!activeProjectId || !activeDocId) return
    let cancelled = false
    async function probe() {
      let n = 1
      while (n < 50) {
        const r = await fetch(pdfPageUrl(activeProjectId!, activeDocId!, n + 1), { method: 'HEAD' })
          .catch(() => null)
        if (cancelled || !r || !r.ok) break
        n += 1
      }
      if (!cancelled) setPageCount(n)
    }
    void probe()
    return () => { cancelled = true }
  }, [activeProjectId, activeDocId, setPageCount])
```

(Note: the dep array drops `page` and `pageCount` — probing now runs once per doc, not per page change. Keeps the network footprint at exactly N HEAD requests for an N-page doc.)

- [ ] **Step 2: Build**

```
cd frontend && npm run build 2>&1 | tail -5
```
Expected: success.

- [ ] **Step 3: Manual smoke (light)**

If a backend + frontend are available locally with at least one multi-page PDF in a project, navigate to review mode and confirm page count shows >1 in the header. Otherwise rely on Playwright in T13 to catch regressions.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ReviewMode/PdfViewer.tsx
git commit -m "fix(frontend): probe PDF pages forward to N until 404 (was stuck at 1)"
```

---

### Task 10: Update SKILL.md slash-commands annotation

**Files:**
- Modify: `backend/app/skills/emerge_extractor.md`

The slash-commands table still lists `/review` as `(M2+)`. M2A actually shipped review mode — fix that, plus our new `/eval` is shipping in this milestone. T6 already updated `/eval`; this task only handles `/review`.

- [ ] **Step 1: Edit**

In `backend/app/skills/emerge_extractor.md`, find the slash-commands table and remove the `(M2+)` annotation for `/review`:

```markdown
- `/review` — opens review mode on first un-reviewed doc.
```

(The line in the file currently reads `- \`/review\` (M2+) — opens review mode on first un-reviewed doc.` — drop ` (M2+)`.)

- [ ] **Step 2: Commit**

```bash
git add backend/app/skills/emerge_extractor.md
git commit -m "feat(skill): drop (M2+) from /review (shipped in M2A)"
```

---

## Phase 4 — End-to-end

### Task 11: Update Playwright e2e seed to populate reviewed data for `/eval` smoke

**Files:**
- Modify: `backend/tests/e2e_seed.py`

The existing seed script creates a project + draft prediction. To smoke-test `/eval`, add a reviewed file alongside the prediction so a `score` call has something to grade.

- [ ] **Step 1: Append reviewed save to seed**

In `backend/tests/e2e_seed.py`, after the existing `atomic_write_json` for the draft prediction, add:

```python
    from app.schemas.reviewed import ReviewedSource
    from app.tools.reviewed import save_reviewed
    await save_reviewed(
        workspace, pid, did,
        entities=[{"invoice_number": "DRAFT-1", "total_amount": 100.0}],
        source=ReviewedSource.MANUAL,
    )
    print(f"  + reviewed for {did}")
```

- [ ] **Step 2: Sanity — run seed standalone**

```
cd backend && rm -rf .tmp_workspace && EMERGE_WORKSPACE_ROOT=./.tmp_workspace uv run python -m tests.e2e_seed
```
Expected: prints `SEEDED pid=p_xxx did=d_xxx` and `+ reviewed for d_xxx`. The directory `.tmp_workspace/p_xxx/reviewed/` exists with one JSON file.

Cleanup:
```
rm -rf backend/.tmp_workspace
```

- [ ] **Step 3: Commit**

```bash
git add backend/tests/e2e_seed.py
git commit -m "test(e2e): seed reviewed alongside prediction so /eval has GT"
```

---

### Task 12: Backend e2e route check via curl in a Python smoke test

**Files:**
- Create: `backend/tests/integration/test_lab_eval_smoke.py`

A focused integration test that exercises the whole eval pipeline from project setup through HTTP — duplicates some setup with `test_lab_eval.py` but separates "POST returns shape" (T7) from "POST against full flow" (this task). Keep it minimal.

- [ ] **Step 1: Write the test**

```python
# backend/tests/integration/test_lab_eval_smoke.py
"""End-to-end backend smoke for the eval flow:
schema → upload → prediction → reviewed → POST /eval → metrics file on disk."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import metrics_dir, predictions_draft_dir


async def test_eval_full_pipeline(workspace: Path) -> None:
    pid = await create_project(workspace, name="smoke")
    await write_schema(
        workspace, pid,
        [
            SchemaField(name="invoice_no", type=FieldType.STRING, description="d"),
            SchemaField(name="total", type=FieldType.NUMBER, description="d"),
        ],
        reason="seed", allow_structural=True,
    )
    pdf = b"%PDF-1.4\n%%EOF\n"
    d1 = await upload_doc(workspace, pid, pdf, "a.pdf")
    d2 = await upload_doc(workspace, pid, pdf, "b.pdf")

    pdir = predictions_draft_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pdir / f"{d1}.json", {"entities": [{"invoice_no": "INV-1", "total": 100}]})
    atomic_write_json(pdir / f"{d2}.json", {"entities": [{"invoice_no": "WRONG", "total": 200}]})

    # Both reviewed, but d2 has the right invoice_no — prediction is wrong
    await save_reviewed(workspace, pid, d1, entities=[{"invoice_no": "INV-1", "total": 100}], source=ReviewedSource.MANUAL)
    await save_reviewed(workspace, pid, d2, entities=[{"invoice_no": "INV-2", "total": 200}], source=ReviewedSource.MANUAL)

    client = TestClient(app)
    r = client.post(f"/lab/projects/{pid}/eval")
    assert r.status_code == 200
    body = r.json()
    assert body["n_reviewed"] == 2
    by_field = {fs["field"]: fs for fs in body["per_field"]}
    # d1 invoice_no correct, d2 wrong → 1 tp, 1 fp, 1 fn → precision=0.5 recall=0.5 f1=0.5
    assert by_field["invoice_no"]["tp"] == 1
    assert by_field["invoice_no"]["f1"] == 0.5
    # total exact for both
    assert by_field["total"]["tp"] == 2
    assert by_field["total"]["f1"] == 1.0

    # Persisted metrics file
    files = list(metrics_dir(workspace, pid).glob("eval_*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text())
    assert saved["macro_f1"] == body["macro_f1"]
```

- [ ] **Step 2: Run**

Run: `cd backend && uv run pytest tests/integration/test_lab_eval_smoke.py -v`
Expected: 1 passed.

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: 137 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_lab_eval_smoke.py
git commit -m "test(integration): full eval pipeline smoke (schema→pred→GT→/eval→metrics file)"
```

---

### Task 13: Final manual smoke (no commit)

After all 12 tasks land, run the actual chat-driven /eval:

- [ ] **Step 1: Restart servers**

```
pkill -f "uvicorn app.main" 2>/dev/null; sleep 1
cd backend && uv run uvicorn app.main:app --port 8080 --reload > /tmp/emerge-logs/backend.log 2>&1 &
cd frontend && npm run dev -- --port 5172 > /tmp/emerge-logs/frontend.log 2>&1 &
```

- [ ] **Step 2: Wait for ready**

```
until curl -sf http://localhost:8080/healthz >/dev/null 2>&1; do sleep 0.5; done; echo "ok"
```

- [ ] **Step 3: Use existing us-invoice project (3 reviewed PDFs from M2A dogfood)**

Open http://localhost:5172/ → click `us-invoice` project → in chat type:

```
现在跑一次 /eval，告诉我每个字段的 F1
```

Expected:
- Agent calls `mcp__emerge_tools__score`
- Returns macro_f1 around 0.85-1.0 (depends on exact value matches; a few minor differences may exist)
- Worst field surfaced
- Metrics file lands at `backend/workspace/{pid}/metrics/eval_*.json`

- [ ] **Step 4: Verify on disk**

```
ls /Users/qinqiang02/colab/codespace/ai/emerge/backend/workspace/p_4w6rzeuz9dfi/metrics/
```
Expected: at least one `eval_*.json` file.

If the manual smoke passes, M2B is verified end-to-end. No commit.

---

## Acceptance check

```
cd backend && uv run pytest -q
# expect ~137 passed (124 baseline + ~13 added)

cd frontend && npm run test
# expect 13 passed (no count change; only T8 modifies test labels which already use case-insensitive regex)

cd frontend && npm run e2e
# expect 2 passed (no e2e additions in M2B)
```

Manual smoke: chat `/eval` returns a macro_f1 number; `metrics/eval_*.json` lands on disk.

---

## Spec coverage check

| Spec section | Covered by |
|---|---|
| §3.2 metrics/{eval_ts}.json filesystem layout | Tasks 1, 4 |
| §5.3 score(predictions, reviewed) → {f1, per_field, errors[]} | Tasks 2, 3 |
| §11 M2 deliverable: score tool + /eval | Tasks 3, 4, 5, 6, 7 |
| §6.1 /eval slash command | Task 6 (SKILL.md) |
| §10 testing layers — tool unit + route integration + smoke | Tasks 3, 4, 7, 12 |

M2A polish items (DocStatus, page probe) addressed in Phase 3.

---

## Self-Review notes

- `score(...)` deliberately compares `entities[0]` only. Multi-entity docs are rare in M2 and unsupported in the review-mode editor anyway. M2C autoresearch may iterate on this if needed.
- `_evidence` round-trip is NOT addressed here — review-mode save still drops it. M2C can decide whether to carry through (for `_source_page` click-to-page) or generate fresh from prediction.
- Score persistence is "append a new file per run" with no rollup index. The frontend doesn't list metrics yet; M2C's autoresearch UI is the natural consumer.
- The slash menu's existing `(M2)` markings were reset for `/eval` (T6) and `/review` (T10). `/improve` and `/publish` still carry their pre-M2C markings.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-09-m2b-eval-score.md`. Default execution: subagent-driven-development (per user preference). New session recommended before starting Phase 1 to keep main context budget healthy.
