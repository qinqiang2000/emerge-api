# M9.3 — Experiments Axis + Review-Mode Multi-Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** add the experiment axis from the M9.x design — 7 MCP tools (`create_experiment`, `extract_with_experiment`, `run_experiment_eval`, `promote_experiment`, `archive_experiment`, `list_experiments`, `delete_experiment`), 4 HTTP routes, an `useExperiments` Zustand store, and a Review-mode tab strip (⭐ Active + N experiments + `[+]`) so users can attach experiments to a doc and switch between their per-doc extracts. Also harden M9.2's `delete_prompt` / `delete_model` to block when a non-archived experiment references them.

**Architecture:** thin layer on top of M9.1/M9.2. `experiments/{exp_id}/{meta.json,extracts/{doc_id}.json}` is the new disk shape; `Experiment` + `ExperimentEval` pydantic models live alongside `PromptVariant` and `ModelConfig`. Experiment extract reuses the existing extract LLM code path (`extract_one_with_schema`, extended with an optional `params` argument) — never recurses into the Agent SDK. `promote_experiment` is the only flow that writes to `predictions/_draft/`; `freeze_version` and the publish fast-path stay untouched. The Review tabstrip is a new component that extends the existing `useReview` slice (tabs are doc-scoped state, the ground-truth save path already lives in `useReview`, so a separate store would just duplicate `activeDocId`/`page`/`evidence`/`notes`); only the field-editor data source changes per tab — when `activeTabKey === 'active'` it reads `useReview.entities` (writable, saves to `reviewed/`), otherwise it reads `extractsByExp[exp_id]` (read-only).

**Tech Stack:** FastAPI + pydantic v2 + `claude_agent_sdk` (backend); React 19 + TypeScript + Zustand + Vite + Vitest + RTL + Playwright (frontend). CSS tokens from `frontend/src/theme/tokens.css` (`--ink-*`, `--paper-*`, `--ochre`, `--moss`, `--rose`).

**Reference docs:**
- Spec: `docs/superpowers/specs/2026-05-12-extraction-comparability-design.md` (§2.2 `Experiment` / `ExperimentEval` pydantic; §3.3 experiment tools; §3.5 `promote_experiment` semantics; §4.2–4.4 scenario walkthroughs; §7.4 review-mode tab strip; §7.5 single-doc predict entries)
- Predecessor plan: `docs/superpowers/plans/2026-05-12-m9-2-axis-tools-and-ui.md` (M9.2, shipped — provides `usePrompts` / `useModels` stores, FSSpine `prompts/` and `models/` groups, `delete_prompt` / `delete_model` with active-only blocking)
- Predecessor plan: `docs/superpowers/plans/2026-05-12-m9-1-data-model-migration.md` (M9.1, shipped — provides path helpers, `read_prompt` / `read_model`, `migrate_project_if_needed`)
- INSIGHTS to respect: #1 (`can_use_tool` mandatory), #4 (Gemini `additionalProperties`), #8 (`safe_project_id` per route), #9 (frontend cross-store refresh)
- CLAUDE.md hard rules — **publish fast-path 0 改动**, **reviewed/ 跨 experiment 共享**, **experiment 永不 auto-promote**, **task-type-agnostic UI vocabulary** (chrome verbs only — "experiment" is acceptable as it's not extraction-specific), **Agent brain ↔ Extract LLM 分离** (experiment extract goes through provider adapter, never back through SDK)

**Conventions:**
- Backend test command: `cd backend && uv run pytest <path> -v`
- Frontend unit-test command: `cd frontend && npm test -- <pattern>`
- Frontend e2e command: `cd frontend && npm run e2e -- <pattern>`
- Async backend tests need NO `@pytest.mark.asyncio` — `pyproject.toml` sets `asyncio_mode="auto"`
- The `workspace` fixture lives in `backend/tests/conftest.py`
- Every task ends with a single `git commit` using `feat(m9.3):`, `refactor(m9.3):`, `test(m9.3):`, `fix(m9.3):`, or `docs(m9.3):` prefix.

**Scope boundary (explicit out of scope for M9.3, save for later plans):**
- Autoresearch path migration (`versions/_candidate/` → `prompts/_candidate/`, "Accept turn N" → "Save turn N as variant") → **M9.4**
- `fork_project`, `import_prompt` (cross-project clone) → **M9.5**
- `readiness_check` rule loosening (move some hard fails to soft warns) → **M9.6**
- Field-diff power-user view ("compare with…", spec §7.4.1) → M9.x follow-up
- Cost / latency tracking per model (`models/{id}.json` placeholder field) → out of scope; deferred until user demand
- `run_experiment_eval` as a background `JobRunner` job → out of scope; inline foreground tool call mirrors `extract_batch`. If a project ever has >20 reviewed docs the tool turn will be long; cross that bridge by lifting into `JobRunner` in a follow-up
- Global-notes wiring into the extract prompt — M9.3 keeps parity with current `extract_one` which only injects schema fields, not `global_notes`. Adding that is a cross-cutting change to `_EXTRACT_SYSTEM` / `_build_field_instructions`, tracked separately
- Tab-pin / field-diff side-by-side (spec §7.4.1) — explicit YAGNI for M9.3
- Single-prompt + single-model "Models card detail editor" — same approach as M9.2 (read-only summary, edits via chat tool only)

---

## Architectural decision notes

### Decision 1 — extend `useReview` over a new `useExperimentReview` store

**Choice:** extend `useReview` with `attachedExperimentIds`, `activeTabKey`, `extractsByExp`.

**Rationale:**
- The "currently active doc" state is identical across tabs — `useReview` already owns `activeDocId`, `page`, `pageCount`, `evidence`, `notes`. A separate store would duplicate all of it and force cross-store sync on tab switch.
- The ground-truth save path (`save()` → POST `/lab/projects/{pid}/reviewed/{doc_id}`) only ever runs on the ⭐ Active tab. Splitting it across stores creates a tempting bug surface (the wrong store's save being called on the wrong tab).
- Tab attachments are doc-scoped — when the user navigates to the next doc, the new tab strip should re-resolve which experiments still have extracts for the new doc. That natural reset matches `useReview.open()` which already wipes per-doc state. A separate store would need a parallel reset hook.
- Per-experiment per-doc extract payloads (`extractsByExp[exp_id][doc_id]`) are a derivable cache. They DON'T live in `useExperiments` because that store is project-scoped (list of meta), not doc-scoped (extract content). Keeping them in `useReview` aligns with their lifecycle.

### Decision 2 — `run_experiment_eval` inline, not a job

**Choice:** synchronous foreground tool call, mirroring `extract_batch`.

**Rationale:** typical lab projects have <20 reviewed docs (M2A dogfood: `us-invoice` had 5–7). At ~3–5s per extract that's <2min turn time. The Job-Runner ceremony (event stream, pause/resume, SSE) is overkill until projects routinely exceed 50+ reviewed. Defer to a follow-up if the lab pattern shifts. The MCP tool returns the `ExperimentEval` dict synchronously; the chat UI's existing tool-progress card covers the wait.

### Decision 3 — `promote_experiment` writes `predictions/_draft/` from experiment extracts

**Choice:** follow spec §3.5 verbatim — `rm -rf predictions/_draft/*` then copy each `experiments/{exp_id}/extracts/{doc_id}.json` → `predictions/_draft/{doc_id}.json`.

**Rationale:** UX win — after promote, Review immediately shows the experiment's results without forcing the user to re-extract. The disk cost (a few KB per doc × N docs) is negligible. The experiment dir is preserved (status="promoted"), so audit is intact and the prompt's `derived_from` lineage chain remains queryable. **Not** clone-the-prompt — the spec explicitly says "set active" not "clone variant"; we honour that.

### Decision 4 — `delete_prompt` / `delete_model` experiment-ref check uses non-archived experiments only

**Choice:** block deletion if any experiment with `status != "archived"` references the prompt/model. Status="promoted" experiments DO block (they're audit trail and must stay queryable).

**Rationale:** matches the spec table in §3.1/§3.2 ("不能删被未 archived experiment 引用的"). Archived experiments are tombstones and don't gate cleanup. Promoted experiments are audit trail and must keep their referenced prompt/model files queryable.

---

## File structure

**New files (backend):**
- `backend/app/schemas/experiment.py` — `Experiment` + `ExperimentEval` pydantic models
- `backend/app/tools/experiment.py` — `create_experiment`, `read_experiment`, `list_experiments`, `extract_with_experiment`, `run_experiment_eval`, `promote_experiment`, `archive_experiment`, `delete_experiment`, plus the two `experiments_referencing_*` helpers used by `delete_prompt` / `delete_model`
- `backend/app/api/routes/experiments.py` — 4 HTTP routes
- `backend/tests/unit/test_schema_experiment.py` — pydantic round-trip tests
- `backend/tests/unit/test_tool_experiment.py` — helper unit tests
- `backend/tests/unit/test_routes_experiments.py` — HTTP route tests

**Modified files (backend):**
- `backend/app/workspace/paths.py` — append `experiments_dir`, `experiment_dir`, `experiment_meta_path`, `experiment_extracts_dir`, `experiment_extract_path`
- `backend/app/workspace/ids.py` — append `new_experiment_id` (prefix `ex_`)
- `backend/app/tools/extract.py` — `extract_one_with_schema` gains an optional `params: dict[str, Any] | None = None` argument (defaults to `{"temperature": 0.0}` to preserve autoresearch behaviour)
- `backend/app/tools/prompt.py` — `delete_prompt` extended to call `experiments_referencing_prompt` and raise `PromptInUseError` with `referenced_by` info when a non-archived experiment references it
- `backend/app/tools/model.py` — symmetrical extension to `delete_model`
- `backend/app/tools/__init__.py` — register 7 new `@tool` wrappers (`t_create_experiment`, `t_extract_with_experiment`, `t_run_experiment_eval`, `t_promote_experiment`, `t_archive_experiment`, `t_list_experiments`, `t_delete_experiment`)
- `backend/app/main.py` — mount `experiments_route.router`
- `backend/app/skills/emerge_extractor.md` — add experiment workflow section + risk-gate entries
- `backend/tests/unit/test_tool_prompt.py` — extend with experiment-ref-block test
- `backend/tests/unit/test_tool_model.py` — extend with experiment-ref-block test
- `backend/tests/unit/test_tool_registration.py` — assert 7 new tools registered
- `backend/tests/unit/test_extract.py` — extend `extract_one_with_schema` test to cover explicit `params` override

**New files (frontend):**
- `frontend/src/stores/experiments.ts` — `useExperiments` Zustand store
- `frontend/src/components/ReviewMode/ExperimentTabStrip.tsx` — segmented tab strip + `[+]` popover
- `frontend/tests/unit/stores/experiments.test.ts`
- `frontend/tests/unit/ReviewMode/ExperimentTabStrip.test.tsx`
- `frontend/tests/e2e/experiment-tabs.spec.ts` — seeded experiment + per-doc extract → open Review → switch tabs

**Modified files (frontend):**
- `frontend/src/lib/api.ts` — append `listExperiments`, `getExperiment`, `getExperimentExtract`, `runExperimentExtract`
- `frontend/src/stores/review.ts` — extend with `attachedExperimentIds`, `activeTabKey`, `extractsByExp`, `attachExperiment`, `detachExperiment`, `setActiveTab`, `loadExperimentExtract`, `runExperimentExtract`; tab reset on doc change in `open()`
- `frontend/src/components/ReviewMode/ReviewOverlay.tsx` — mount `ExperimentTabStrip` above `rev-body`; pass `readOnly` to `FieldEditor` when `activeTabKey !== 'active'`; swap entities source per tab
- `frontend/src/components/ReviewMode/FieldEditor.tsx` — accept optional `readOnly?: boolean` prop; disable inputs and hide remove/add-entity buttons when set
- `frontend/src/components/ReviewMode/ReviewBar.tsx` — hide `save` button when current tab is not active; show small hint "save lives on the ⭐ Active tab"
- `frontend/src/types/review.ts` — append `Experiment` summary type + `ExperimentExtractPayload` (mirrors `ExtractionOutput`)
- `frontend/src/components/Spine/FSSpine.tsx` — add `experiments/` group rendering (read-only list rows; clicking an experiment is inert for M9.3, future M9.x may open detail sheet)
- `frontend/tests/unit/ReviewMode/ReviewOverlay.test.tsx` — extend with tab-switch test
- `frontend/tests/unit/Spine/FSSpine.test.tsx` — extend with `experiments/` group test

---

## Task 1: Pydantic models — `Experiment` + `ExperimentEval`

**Files:**
- Create: `backend/app/schemas/experiment.py`
- Create: `backend/tests/unit/test_schema_experiment.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_schema_experiment.py`:

```python
from app.schemas.experiment import Experiment, ExperimentEval


def test_experiment_minimum_fields_default_status_draft():
    ex = Experiment(
        experiment_id="ex_abcdef012345",
        label="trial 1",
        prompt_id="pr_baseline",
        model_id="m_default",
        created_at="2026-05-13T00:00:00Z",
    )
    assert ex.status == "draft"
    assert ex.eval is None
    assert ex.promoted_at is None
    assert ex.notes == ""


def test_experiment_with_eval_roundtrip():
    blob = {
        "experiment_id": "ex_abcdef012345",
        "label": "trial 2",
        "prompt_id": "pr_baseline",
        "model_id": "m_default",
        "status": "ran",
        "created_at": "2026-05-13T00:00:00Z",
        "notes": "tried adding 'top-right' hint",
        "eval": {
            "ran_at": "2026-05-13T00:01:00Z",
            "score": 0.91,
            "per_field": {"supplier": 1.0, "amount": 0.85},
            "per_doc": {"d_aaa": 0.95, "d_bbb": 0.87},
            "run_id": "r_1715567890",
            "coverage": 2,
        },
    }
    ex = Experiment(**blob)
    assert ex.eval is not None
    assert ex.eval.score == 0.91
    assert ex.eval.per_field["supplier"] == 1.0
    # round-trip preserves shape
    assert Experiment(**ex.model_dump(mode="json")).eval == ex.eval


def test_experiment_rejects_unknown_status():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Experiment(
            experiment_id="ex_abcdef012345",
            label="x",
            prompt_id="pr_x",
            model_id="m_x",
            status="bogus",  # type: ignore[arg-type]
            created_at="2026-05-13T00:00:00Z",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_schema_experiment.py -v`
Expected: FAIL with `ModuleNotFoundError: app.schemas.experiment`.

- [ ] **Step 3: Implement the models**

Create `backend/app/schemas/experiment.py`:

```python
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExperimentEval(BaseModel):
    """Outcome of one run_experiment_eval call against the reviewed/ ground truth."""
    model_config = ConfigDict(extra="forbid")

    ran_at: str
    score: float
    per_field: dict[str, float] = Field(default_factory=dict)
    per_doc: dict[str, float] = Field(default_factory=dict)
    run_id: str
    coverage: int


class Experiment(BaseModel):
    """A (prompt_id, model_id) reference pair plus optional eval + per-doc extracts.

    Disk: experiments/{experiment_id}/meta.json (this blob) +
          experiments/{experiment_id}/extracts/{doc_id}.json (per-doc payloads).
    """
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    label: str
    prompt_id: str
    model_id: str
    status: Literal["draft", "ran", "archived", "promoted"] = "draft"
    created_at: str
    promoted_at: Optional[str] = None
    notes: str = ""
    eval: Optional[ExperimentEval] = None
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && uv run pytest tests/unit/test_schema_experiment.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/experiment.py backend/tests/unit/test_schema_experiment.py
git commit -m "feat(m9.3): add Experiment + ExperimentEval pydantic models"
```

---

## Task 2: Workspace paths + id helper

**Files:**
- Modify: `backend/app/workspace/paths.py` (append 5 helpers)
- Modify: `backend/app/workspace/ids.py` (append `new_experiment_id`)
- Modify: existing tests at `backend/tests/unit/test_paths.py` if present, otherwise create coverage in `backend/tests/unit/test_workspace_paths_experiment.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_workspace_paths_experiment.py`:

```python
from pathlib import Path

from app.workspace.ids import new_experiment_id
from app.workspace.paths import (
    experiment_dir,
    experiment_extract_path,
    experiment_extracts_dir,
    experiment_meta_path,
    experiments_dir,
)


def test_new_experiment_id_format():
    eid = new_experiment_id()
    assert eid.startswith("ex_")
    assert len(eid) == 3 + 12  # "ex_" + 12-char base36
    assert eid[3:].isalnum() and eid[3:].islower()


def test_experiment_path_helpers(tmp_path: Path):
    ws = tmp_path
    pid = "p_test12345678"
    eid = "ex_abcdef012345"
    did = "d_doc000000000"
    assert experiments_dir(ws, pid) == ws / pid / "experiments"
    assert experiment_dir(ws, pid, eid) == ws / pid / "experiments" / eid
    assert experiment_meta_path(ws, pid, eid) == ws / pid / "experiments" / eid / "meta.json"
    assert experiment_extracts_dir(ws, pid, eid) == ws / pid / "experiments" / eid / "extracts"
    assert experiment_extract_path(ws, pid, eid, did) == \
        ws / pid / "experiments" / eid / "extracts" / f"{did}.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_workspace_paths_experiment.py -v`
Expected: FAIL with `ImportError` on the new helpers / `new_experiment_id`.

- [ ] **Step 3: Implement**

Append to `backend/app/workspace/paths.py` (placement near the existing `prompt_path` / `model_path` block):

```python
def experiments_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "experiments"


def experiment_dir(workspace: Path, project_id: str, experiment_id: str) -> Path:
    return experiments_dir(workspace, project_id) / experiment_id


def experiment_meta_path(workspace: Path, project_id: str, experiment_id: str) -> Path:
    return experiment_dir(workspace, project_id, experiment_id) / "meta.json"


def experiment_extracts_dir(workspace: Path, project_id: str, experiment_id: str) -> Path:
    return experiment_dir(workspace, project_id, experiment_id) / "extracts"


def experiment_extract_path(
    workspace: Path, project_id: str, experiment_id: str, doc_id: str,
) -> Path:
    return experiment_extracts_dir(workspace, project_id, experiment_id) / f"{doc_id}.json"
```

Append to `backend/app/workspace/ids.py`:

```python
def new_experiment_id() -> str:
    return _new("ex")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_workspace_paths_experiment.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace/paths.py backend/app/workspace/ids.py \
        backend/tests/unit/test_workspace_paths_experiment.py
git commit -m "feat(m9.3): experiments/ disk paths + new_experiment_id helper"
```

---

## Task 3: `create_experiment` + `read_experiment` + `list_experiments`

**Files:**
- Create: `backend/app/tools/experiment.py`
- Create: `backend/tests/unit/test_tool_experiment.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_tool_experiment.py`:

```python
import json
from pathlib import Path

import pytest

from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    experiment_meta_path,
    model_path,
    project_json_path,
    prompt_path,
)


def _now() -> str:
    return "2026-05-13T00:00:00+00:00"


def _seed_axes(workspace: Path, pid: str) -> None:
    """Seed a project with one active prompt + one active model."""
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "project_id": pid,
        "name": "Test",
        "created_at": _now(),
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
    })
    atomic_write_json(prompt_path(workspace, pid, "pr_baseline"), {
        "prompt_id": "pr_baseline",
        "label": "Baseline",
        "schema": [
            {"name": "supplier", "type": "string", "description": "Supplier name", "required": False},
        ],
        "global_notes": "",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, pid, "m_default"), {
        "model_id": "m_default",
        "label": "Default",
        "provider": "google",
        "provider_model_id": "gemini-2.5-flash",
        "params": {"temperature": 0.0},
        "created_at": _now(),
    })


async def test_create_experiment_defaults_to_active(workspace: Path) -> None:
    from app.tools.experiment import create_experiment, read_experiment
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    assert eid.startswith("ex_")
    ex = await read_experiment(workspace, pid, eid)
    assert ex.prompt_id == "pr_baseline"
    assert ex.model_id == "m_default"
    assert ex.status == "draft"
    assert ex.eval is None
    assert ex.label.startswith("trial_")


async def test_create_experiment_explicit_axes(workspace: Path) -> None:
    from app.tools.experiment import create_experiment, read_experiment
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # seed a second prompt and a second model
    atomic_write_json(prompt_path(workspace, pid, "pr_v2"), {
        "prompt_id": "pr_v2", "label": "v2",
        "schema": [{"name": "x", "type": "string", "description": "x", "required": False}],
        "global_notes": "", "derived_from": "pr_baseline",
        "created_at": _now(), "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, pid, "m_other"), {
        "model_id": "m_other", "label": "Other",
        "provider": "anthropic",
        "provider_model_id": "claude-haiku-4-5-20251001",
        "params": {}, "created_at": _now(),
    })
    eid = await create_experiment(
        workspace, pid, label="custom", prompt_id="pr_v2", model_id="m_other",
    )
    ex = await read_experiment(workspace, pid, eid)
    assert ex.label == "custom"
    assert ex.prompt_id == "pr_v2"
    assert ex.model_id == "m_other"


async def test_create_experiment_missing_prompt_raises(workspace: Path) -> None:
    from app.tools.experiment import create_experiment
    from app.tools.prompt import PromptNotFoundError
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await create_experiment(workspace, pid, prompt_id="pr_missing")


async def test_create_experiment_missing_model_raises(workspace: Path) -> None:
    from app.tools.experiment import create_experiment
    from app.tools.model import ModelNotFoundError
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    with pytest.raises(ModelNotFoundError):
        await create_experiment(workspace, pid, model_id="m_missing")


async def test_list_experiments_excludes_archived_by_default(workspace: Path) -> None:
    from app.tools.experiment import (
        archive_experiment,
        create_experiment,
        list_experiments,
    )
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    e1 = await create_experiment(workspace, pid, label="keep")
    e2 = await create_experiment(workspace, pid, label="hide")
    await archive_experiment(workspace, pid, e2)
    rows_default = await list_experiments(workspace, pid)
    assert [r["experiment_id"] for r in rows_default] == [e1]
    rows_all = await list_experiments(workspace, pid, include_archived=True)
    assert {r["experiment_id"] for r in rows_all} == {e1, e2}


async def test_list_experiments_returns_score_when_available(workspace: Path) -> None:
    from app.tools.experiment import create_experiment, list_experiments
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    meta = json.loads(experiment_meta_path(workspace, pid, eid).read_text())
    meta["status"] = "ran"
    meta["eval"] = {
        "ran_at": _now(), "score": 0.91,
        "per_field": {"supplier": 1.0}, "per_doc": {},
        "run_id": "r_1", "coverage": 0,
    }
    atomic_write_json(experiment_meta_path(workspace, pid, eid), meta)
    rows = await list_experiments(workspace, pid)
    assert rows[0]["status"] == "ran"
    assert rows[0]["score"] == 0.91
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_experiment.py -v`
Expected: FAIL with `ModuleNotFoundError: app.tools.experiment`.

- [ ] **Step 3: Implement helpers**

Create `backend/app/tools/experiment.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.experiment import Experiment, ExperimentEval
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_experiment_id
from app.workspace.lock import project_lock
from app.workspace.paths import (
    experiment_extract_path,
    experiment_extracts_dir,
    experiment_dir,
    experiment_meta_path,
    experiments_dir,
    project_json_path,
)


class ExperimentNotFoundError(Exception):
    """Raised when an experiment_id has no on-disk meta.json."""


class ExperimentInUseError(Exception):
    """Raised when delete_experiment targets a promoted experiment (audit trail)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _resolve_active_prompt_id(workspace: Path, project_id: str) -> str:
    blob = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    pid_active = blob.get("active_prompt_id")
    if not pid_active:
        raise ValueError(f"project {project_id} has no active_prompt_id")
    return pid_active


async def _resolve_active_model_id(workspace: Path, project_id: str) -> str:
    blob = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    mid_active = blob.get("active_model_id")
    if not mid_active:
        raise ValueError(f"project {project_id} has no active_model_id")
    return mid_active


async def read_experiment(
    workspace: Path, project_id: str, experiment_id: str,
) -> Experiment:
    mp = experiment_meta_path(workspace, project_id, experiment_id)
    if not mp.exists():
        raise ExperimentNotFoundError(
            f"{experiment_id} not found in project {project_id}"
        )
    return Experiment(**json.loads(mp.read_text(encoding="utf-8")))


async def create_experiment(
    workspace: Path,
    project_id: str,
    *,
    label: str | None = None,
    prompt_id: str | None = None,
    model_id: str | None = None,
) -> str:
    """Create an experiment referencing (prompt_id or active, model_id or active).

    Validates that referenced prompt + model exist (raises PromptNotFoundError /
    ModelNotFoundError otherwise). Returns the new experiment_id.
    """
    from app.tools.model import ModelNotFoundError, read_model
    from app.tools.prompt import PromptNotFoundError, read_prompt
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)

    async with project_lock(workspace, project_id):
        pid_resolved = prompt_id or await _resolve_active_prompt_id(workspace, project_id)
        mid_resolved = model_id or await _resolve_active_model_id(workspace, project_id)
        # validate existence
        await read_prompt(workspace, project_id, pid_resolved)
        await read_model(workspace, project_id, mid_resolved)

        new_id = new_experiment_id()
        now = _now_iso()
        ex = Experiment(
            experiment_id=new_id,
            label=label or f"trial_{now}",
            prompt_id=pid_resolved,
            model_id=mid_resolved,
            status="draft",
            created_at=now,
            promoted_at=None,
            notes="",
            eval=None,
        )
        experiment_dir(workspace, project_id, new_id).mkdir(parents=True, exist_ok=True)
        experiment_extracts_dir(workspace, project_id, new_id).mkdir(
            parents=True, exist_ok=True,
        )
        atomic_write_json(
            experiment_meta_path(workspace, project_id, new_id),
            ex.model_dump(mode="json"),
        )
    return new_id


async def list_experiments(
    workspace: Path,
    project_id: str,
    *,
    include_archived: bool = False,
) -> list[dict]:
    """Return summary rows for experiments in this project.

    Each row: {experiment_id, label, prompt_id, model_id, status, created_at,
               score | None}. Newest-first by created_at.
    """
    edir = experiments_dir(workspace, project_id)
    if not edir.exists():
        return []
    rows: list[dict] = []
    for sub in edir.iterdir():
        if not sub.is_dir():
            continue
        meta_path = sub / "meta.json"
        if not meta_path.exists():
            continue
        ex = Experiment(**json.loads(meta_path.read_text(encoding="utf-8")))
        if ex.status == "archived" and not include_archived:
            continue
        rows.append({
            "experiment_id": ex.experiment_id,
            "label": ex.label,
            "prompt_id": ex.prompt_id,
            "model_id": ex.model_id,
            "status": ex.status,
            "created_at": ex.created_at,
            "score": ex.eval.score if ex.eval else None,
        })
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return rows


async def archive_experiment(
    workspace: Path, project_id: str, experiment_id: str,
) -> None:
    """status → 'archived'. No-op if already archived. Cannot archive a promoted
    experiment (that would lose audit trail — raises ExperimentInUseError)."""
    async with project_lock(workspace, project_id):
        ex = await read_experiment(workspace, project_id, experiment_id)
        if ex.status == "promoted":
            raise ExperimentInUseError(
                f"cannot archive {experiment_id}: status is 'promoted' (audit trail)"
            )
        if ex.status == "archived":
            return
        updated = ex.model_copy(update={"status": "archived"})
        atomic_write_json(
            experiment_meta_path(workspace, project_id, experiment_id),
            updated.model_dump(mode="json"),
        )
```

(The remaining functions `extract_with_experiment`, `run_experiment_eval`, `promote_experiment`, `delete_experiment`, and the two `experiments_referencing_*` helpers are added in Tasks 4, 5, 6, 7 — keeping each task's diff small. The placeholder `archive_experiment` is included now to satisfy the Task 3 test for `list_experiments` filtering.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_experiment.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/experiment.py backend/tests/unit/test_tool_experiment.py
git commit -m "feat(m9.3): create_experiment + read/list/archive helpers"
```

---

## Task 4: `extract_with_experiment` (single-doc)

**Files:**
- Modify: `backend/app/tools/extract.py` (add `params` argument to `extract_one_with_schema`)
- Modify: `backend/app/tools/experiment.py` (append `extract_with_experiment`)
- Modify: `backend/tests/unit/test_tool_experiment.py` (append extract tests)
- Modify: `backend/tests/unit/test_extract.py` (or wherever `extract_one_with_schema` is tested — confirm the new `params` arg is respected)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_tool_experiment.py`:

```python
async def test_extract_with_experiment_writes_to_extracts_dir(
    workspace: Path, fake_provider,
):
    """fake_provider fixture should be the same one extract tests use; returns
    a canned ExtractionOutput-shaped payload."""
    from app.tools.experiment import create_experiment, extract_with_experiment
    from app.workspace.paths import doc_path, docs_dir
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # seed a fake doc
    did = "d_doc000000000"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, did, "txt").write_text("invoice from ACME")

    eid = await create_experiment(workspace, pid)
    payload = await extract_with_experiment(
        workspace, pid, eid, did, provider=fake_provider,
    )
    assert payload.get("entities")  # canned payload renders entities
    on_disk = json.loads(
        experiment_extract_path(workspace, pid, eid, did).read_text(),
    )
    assert on_disk == payload


async def test_extract_with_experiment_uses_experiment_prompt_not_active(
    workspace: Path, fake_provider,
):
    """Even if active prompt has fields [A, B], if the experiment references a
    variant with fields [X, Y, Z], the extract must instruct on X/Y/Z."""
    from app.tools.experiment import create_experiment, extract_with_experiment
    from app.workspace.paths import doc_path, docs_dir
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # seed a variant with one different field name
    atomic_write_json(prompt_path(workspace, pid, "pr_variant"), {
        "prompt_id": "pr_variant", "label": "variant",
        "schema": [
            {"name": "marker", "type": "string", "description": "unique field", "required": False},
        ],
        "global_notes": "", "derived_from": "pr_baseline",
        "created_at": _now(), "updated_at": _now(),
    })
    did = "d_doc000000000"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, did, "txt").write_text("hi")
    eid = await create_experiment(workspace, pid, prompt_id="pr_variant")
    await extract_with_experiment(workspace, pid, eid, did, provider=fake_provider)
    # fake_provider records the last user text it was sent; assert it carries
    # 'marker' from the experiment prompt, NOT 'supplier' from active.
    assert "marker" in fake_provider.last_user_text
    assert "supplier" not in fake_provider.last_user_text
```

(If `fake_provider` doesn't exist yet, add it to `backend/tests/conftest.py` as a recording stub — see the M2A test fixtures for the established pattern; do NOT instantiate a real provider.)

Sketch for `fake_provider` (place in conftest.py if not present):

```python
@pytest.fixture
def fake_provider():
    class _FakeResult:
        def __init__(self, raw_json: dict):
            self.raw_json = raw_json
    class _FakeProvider:
        last_user_text: str = ""
        last_model_id: str | None = None
        last_params: dict | None = None
        async def extract(self, *, model_id, system_prompt, user_content,
                          response_schema, params=None):
            self.last_model_id = model_id
            self.last_params = params
            self.last_user_text = " ".join(
                getattr(b, "text", "") for b in user_content
            )
            return _FakeResult({
                "entities": [{}],
            })
    return _FakeProvider()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_experiment.py -v -k "extract_with_experiment"`
Expected: FAIL with `ImportError: cannot import name 'extract_with_experiment'`.

- [ ] **Step 3: Extend `extract_one_with_schema` to accept `params`**

Edit `backend/app/tools/extract.py` — find the `extract_one_with_schema` signature and add `params` to its keyword arguments, defaulting to `None` and falling back to `{"temperature": 0.0}` only when `params is None`. Concretely:

```python
async def extract_one_with_schema(
    workspace: Path,
    project_id: str,
    doc_id: str,
    *,
    schema: list[SchemaField],
    provider: Provider,
    model_id: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Like extract_one but uses an in-memory schema (does NOT read schema.json
    or write predictions/_draft/). Used by autoresearch and by
    extract_with_experiment to grade alternative (prompt, model) combos.
    """
    if not schema:
        raise ValueError("schema must be non-empty")

    user_blocks: list[ContentBlock] = [
        TextBlock(text=_build_field_instructions(schema)),
        await _doc_to_block(workspace, project_id, doc_id),
    ]
    response_schema = _build_response_schema(schema)
    result = await provider.extract(
        model_id=model_id,
        system_prompt=_EXTRACT_SYSTEM,
        user_content=user_blocks,
        response_schema=response_schema,
        params=params if params is not None else {"temperature": 0.0},
    )
    parsed = ExtractionOutput(**result.raw_json)
    return parsed.model_dump(by_alias=True, exclude_none=True, mode="json")
```

- [ ] **Step 4: Add `extract_with_experiment` to `experiment.py`**

Append to `backend/app/tools/experiment.py`:

```python
async def extract_with_experiment(
    workspace: Path,
    project_id: str,
    experiment_id: str,
    doc_id: str,
    *,
    provider,
) -> dict:
    """Run the experiment's (prompt, model) pair on a single doc, writing the
    payload to experiments/{exp_id}/extracts/{doc_id}.json. Returns the payload.

    The caller is responsible for passing the right provider for the experiment's
    model — the MCP wrapper / HTTP route uses get_provider_for_model(
    experiment.model.provider_model_id).
    """
    from app.tools.extract import extract_one_with_schema
    from app.tools.model import read_model
    from app.tools.prompt import read_prompt

    ex = await read_experiment(workspace, project_id, experiment_id)
    prompt = await read_prompt(workspace, project_id, ex.prompt_id)
    model = await read_model(workspace, project_id, ex.model_id)

    payload = await extract_one_with_schema(
        workspace, project_id, doc_id,
        schema=prompt.schema,
        provider=provider,
        model_id=model.provider_model_id,
        params=model.params or None,
    )
    async with project_lock(workspace, project_id):
        experiment_extracts_dir(workspace, project_id, experiment_id).mkdir(
            parents=True, exist_ok=True,
        )
        atomic_write_json(
            experiment_extract_path(workspace, project_id, experiment_id, doc_id),
            payload,
        )
    return payload
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_experiment.py tests/unit/test_extract.py -v`
Expected: all PASS (including pre-existing tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/extract.py backend/app/tools/experiment.py \
        backend/tests/unit/test_tool_experiment.py backend/tests/conftest.py
git commit -m "feat(m9.3): extract_with_experiment writes to experiment's extracts/"
```

---

## Task 5: `run_experiment_eval` (loop reviewed → score → write eval)

**Files:**
- Modify: `backend/app/tools/experiment.py` (append `run_experiment_eval`)
- Modify: `backend/tests/unit/test_tool_experiment.py` (append run-eval tests)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_tool_experiment.py`:

```python
async def test_run_experiment_eval_writes_eval_meta_and_per_doc(
    workspace: Path, fake_provider,
):
    """Each reviewed doc gets extracted, results aggregate into per_field +
    per_doc scores, status flips to 'ran'."""
    from app.tools.experiment import create_experiment, run_experiment_eval
    from app.workspace.paths import doc_path, docs_dir, reviewed_path, reviewed_dir
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # seed 2 reviewed docs
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    for did in ("d_aaaaaaaaaaaa", "d_bbbbbbbbbbbb"):
        doc_path(workspace, pid, did, "txt").write_text("hello")
        atomic_write_json(reviewed_path(workspace, pid, did), {
            "entities": [{"supplier": "ACME"}],
            "source": "manual",
        })
    eid = await create_experiment(workspace, pid)
    # fake_provider returns canned entities — wire it to return what reviewed
    # has so the score is non-zero
    fake_provider._payload = {"entities": [{"supplier": "ACME"}]}
    ev = await run_experiment_eval(workspace, pid, eid, provider=fake_provider)
    assert ev["score"] >= 0.0
    assert set(ev["per_doc"].keys()) == {"d_aaaaaaaaaaaa", "d_bbbbbbbbbbbb"}
    assert ev["coverage"] == 2
    # status / persisted shape
    ex = await read_experiment(workspace, pid, eid)
    assert ex.status == "ran"
    assert ex.eval is not None
    assert ex.eval.score == ev["score"]


async def test_run_experiment_eval_with_no_reviewed_raises(
    workspace: Path, fake_provider,
):
    from app.tools.experiment import create_experiment, run_experiment_eval
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    with pytest.raises(ValueError, match="no reviewed docs"):
        await run_experiment_eval(workspace, pid, eid, provider=fake_provider)


async def test_run_experiment_eval_reuses_existing_extract_when_present(
    workspace: Path, fake_provider,
):
    """If experiments/{exp}/extracts/{doc}.json already exists, run_experiment_eval
    must NOT call provider.extract again for that doc — costly LLM call avoided."""
    from app.tools.experiment import (
        create_experiment,
        extract_with_experiment,
        run_experiment_eval,
    )
    from app.workspace.paths import doc_path, docs_dir, reviewed_path, reviewed_dir
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    did = "d_aaaaaaaaaaaa"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, did, "txt").write_text("x")
    atomic_write_json(reviewed_path(workspace, pid, did), {
        "entities": [{"supplier": "ACME"}], "source": "manual",
    })
    eid = await create_experiment(workspace, pid)
    fake_provider._payload = {"entities": [{"supplier": "ACME"}]}
    # priming extract
    await extract_with_experiment(workspace, pid, eid, did, provider=fake_provider)
    call_count_before = fake_provider.call_count
    await run_experiment_eval(workspace, pid, eid, provider=fake_provider)
    assert fake_provider.call_count == call_count_before  # no new extract calls
```

Update the conftest `fake_provider` fixture to support `_payload` override and `call_count` tracking:

```python
class _FakeProvider:
    last_user_text: str = ""
    last_model_id: str | None = None
    last_params: dict | None = None
    call_count: int = 0
    _payload: dict = {"entities": [{}]}
    async def extract(self, *, model_id, system_prompt, user_content,
                      response_schema, params=None):
        self.call_count += 1
        self.last_model_id = model_id
        self.last_params = params
        self.last_user_text = " ".join(
            getattr(b, "text", "") for b in user_content
        )
        return _FakeResult(self._payload)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_experiment.py -v -k "run_experiment_eval"`
Expected: FAIL with `ImportError: cannot import name 'run_experiment_eval'`.

- [ ] **Step 3: Implement `run_experiment_eval`**

Append to `backend/app/tools/experiment.py`:

```python
async def run_experiment_eval(
    workspace: Path,
    project_id: str,
    experiment_id: str,
    *,
    provider,
) -> dict:
    """Foreground loop: for each doc in reviewed/, ensure
    experiments/{exp_id}/extracts/{doc}.json exists (extract if missing),
    then score predictions vs reviewed (overall + per-doc). Writes the
    resulting ExperimentEval into meta.json.eval, sets status='ran'.

    Returns the eval dict (matching the persisted blob).

    Reviewed docs with no underlying doc file (rare; usually means the doc was
    deleted after review) are skipped with a logged warning rather than raised
    — the eval coverage count reflects only docs that were successfully extracted.
    """
    import time
    from app.schemas.experiment import ExperimentEval
    from app.tools.extract import extract_one_with_schema
    from app.tools.model import read_model
    from app.tools.prompt import read_prompt
    from app.tools.score import score
    from app.workspace.paths import doc_path, reviewed_dir, reviewed_path

    ex = await read_experiment(workspace, project_id, experiment_id)
    prompt = await read_prompt(workspace, project_id, ex.prompt_id)
    model = await read_model(workspace, project_id, ex.model_id)

    rdir = reviewed_dir(workspace, project_id)
    if not rdir.exists():
        raise ValueError("project has no reviewed docs; nothing to eval against")
    reviewed_files = sorted(rdir.glob("*.json"))
    if not reviewed_files:
        raise ValueError("project has no reviewed docs; nothing to eval against")

    predictions: dict[str, list[dict]] = {}
    reviewed_payloads: dict[str, list[dict]] = {}
    per_doc: dict[str, float] = {}

    for rfile in reviewed_files:
        did = rfile.stem
        reviewed_blob = json.loads(rfile.read_text(encoding="utf-8"))
        reviewed_entities = reviewed_blob.get("entities", [])
        # ensure underlying doc exists
        if not any(
            doc_path(workspace, project_id, did, ext).exists()
            for ext in ("pdf", "txt", "png", "jpg", "jpeg", "webp")
        ):
            continue
        # reuse cached extract if present
        ep = experiment_extract_path(workspace, project_id, experiment_id, did)
        if ep.exists():
            payload = json.loads(ep.read_text(encoding="utf-8"))
        else:
            payload = await extract_one_with_schema(
                workspace, project_id, did,
                schema=prompt.schema, provider=provider,
                model_id=model.provider_model_id,
                params=model.params or None,
            )
            experiment_extracts_dir(workspace, project_id, experiment_id).mkdir(
                parents=True, exist_ok=True,
            )
            atomic_write_json(ep, payload)
        predictions[did] = payload.get("entities", [])
        reviewed_payloads[did] = reviewed_entities

    # overall
    overall = score(prompt.schema, predictions, reviewed_payloads)
    # per-doc: re-score one doc at a time (cheap; in-memory)
    for did in predictions:
        single = score(
            prompt.schema,
            {did: predictions[did]},
            {did: reviewed_payloads[did]},
        )
        per_doc[did] = single.macro_f1

    now = _now_iso()
    eval_blob = ExperimentEval(
        ran_at=now,
        score=overall.macro_f1,
        per_field={fs.field: fs.f1 for fs in overall.per_field},
        per_doc=per_doc,
        run_id=f"r_{int(time.time())}",
        coverage=len(predictions),
    )
    async with project_lock(workspace, project_id):
        updated = ex.model_copy(update={"status": "ran", "eval": eval_blob})
        atomic_write_json(
            experiment_meta_path(workspace, project_id, experiment_id),
            updated.model_dump(mode="json"),
        )
    return eval_blob.model_dump(mode="json")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_experiment.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/experiment.py backend/tests/unit/test_tool_experiment.py \
        backend/tests/conftest.py
git commit -m "feat(m9.3): run_experiment_eval — score reviewed/, write per-field + per-doc"
```

---

## Task 6: `promote_experiment` + `delete_experiment`

**Files:**
- Modify: `backend/app/tools/experiment.py` (append)
- Modify: `backend/tests/unit/test_tool_experiment.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_tool_experiment.py`:

```python
async def test_promote_experiment_switches_active_and_seeds_predictions(
    workspace: Path, fake_provider,
):
    """After promote: active_prompt_id + active_model_id match the experiment,
    predictions/_draft/ contains files copied from experiment extracts,
    status='promoted', promoted_at set."""
    from app.tools.experiment import (
        create_experiment,
        extract_with_experiment,
        promote_experiment,
    )
    from app.workspace.paths import (
        doc_path,
        docs_dir,
        predictions_draft_dir,
        prompt_path,
    )
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # seed a variant + doc
    atomic_write_json(prompt_path(workspace, pid, "pr_v2"), {
        "prompt_id": "pr_v2", "label": "v2",
        "schema": [{"name": "x", "type": "string", "description": "x", "required": False}],
        "global_notes": "", "derived_from": "pr_baseline",
        "created_at": _now(), "updated_at": _now(),
    })
    did = "d_aaaaaaaaaaaa"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, did, "txt").write_text("z")

    eid = await create_experiment(workspace, pid, prompt_id="pr_v2")
    fake_provider._payload = {"entities": [{"x": "1"}]}
    await extract_with_experiment(workspace, pid, eid, did, provider=fake_provider)
    await promote_experiment(workspace, pid, eid)

    project = json.loads(project_json_path(workspace, pid).read_text())
    assert project["active_prompt_id"] == "pr_v2"

    draft_dir = predictions_draft_dir(workspace, pid)
    assert (draft_dir / f"{did}.json").exists()
    assert json.loads((draft_dir / f"{did}.json").read_text())["entities"][0]["x"] == "1"

    ex = await read_experiment(workspace, pid, eid)
    assert ex.status == "promoted"
    assert ex.promoted_at is not None


async def test_promote_experiment_replaces_existing_predictions_draft(
    workspace: Path, fake_provider,
):
    """Spec §3.5 step 2: rm -rf predictions/_draft/* then re-fill from
    experiment.extracts. Pre-existing draft files must be cleared."""
    from app.tools.experiment import (
        create_experiment,
        extract_with_experiment,
        promote_experiment,
    )
    from app.workspace.paths import doc_path, docs_dir, predictions_draft_dir
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # pre-existing draft from a previous active prompt
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    stale = predictions_draft_dir(workspace, pid) / "d_old0000.json"
    stale.write_text(json.dumps({"entities": [{"supplier": "stale"}]}))

    did = "d_aaaaaaaaaaaa"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, did, "txt").write_text("z")
    eid = await create_experiment(workspace, pid)
    fake_provider._payload = {"entities": [{"supplier": "fresh"}]}
    await extract_with_experiment(workspace, pid, eid, did, provider=fake_provider)
    await promote_experiment(workspace, pid, eid)
    assert not stale.exists()
    assert (predictions_draft_dir(workspace, pid) / f"{did}.json").exists()


async def test_delete_experiment_blocks_promoted(workspace: Path, fake_provider):
    from app.tools.experiment import (
        create_experiment,
        delete_experiment,
        promote_experiment,
        extract_with_experiment,
        ExperimentInUseError,
    )
    from app.workspace.paths import doc_path, docs_dir
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    did = "d_aaaaaaaaaaaa"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, did, "txt").write_text("z")
    eid = await create_experiment(workspace, pid)
    fake_provider._payload = {"entities": [{}]}
    await extract_with_experiment(workspace, pid, eid, did, provider=fake_provider)
    await promote_experiment(workspace, pid, eid)
    with pytest.raises(ExperimentInUseError):
        await delete_experiment(workspace, pid, eid)


async def test_delete_experiment_physical_removal(workspace: Path, fake_provider):
    from app.tools.experiment import (
        ExperimentNotFoundError,
        create_experiment,
        delete_experiment,
        read_experiment,
    )
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    await delete_experiment(workspace, pid, eid)
    with pytest.raises(ExperimentNotFoundError):
        await read_experiment(workspace, pid, eid)
    # directory gone
    assert not experiment_meta_path(workspace, pid, eid).parent.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_experiment.py -v -k "promote_experiment or delete_experiment"`
Expected: FAIL with `ImportError` on `promote_experiment` / `delete_experiment`.

- [ ] **Step 3: Implement**

Append to `backend/app/tools/experiment.py`:

```python
async def promote_experiment(
    workspace: Path,
    project_id: str,
    experiment_id: str,
) -> None:
    """Spec §3.5: set active_prompt_id + active_model_id from experiment,
    clear predictions/_draft/, copy experiment extracts into predictions/_draft/,
    mark experiment status='promoted' + promoted_at.

    All under project_lock to guarantee no concurrent freeze_version observes a
    half-state."""
    import shutil

    from app.workspace.paths import predictions_draft_dir

    ex = await read_experiment(workspace, project_id, experiment_id)

    async with project_lock(workspace, project_id):
        # 1. switch active
        pj = project_json_path(workspace, project_id)
        project = json.loads(pj.read_text(encoding="utf-8"))
        project["active_prompt_id"] = ex.prompt_id
        project["active_model_id"] = ex.model_id
        atomic_write_json(pj, project)

        # 2. wipe + repopulate predictions/_draft/
        draft_dir = predictions_draft_dir(workspace, project_id)
        if draft_dir.exists():
            shutil.rmtree(draft_dir)
        draft_dir.mkdir(parents=True, exist_ok=True)
        ex_extracts = experiment_extracts_dir(workspace, project_id, experiment_id)
        if ex_extracts.exists():
            for src in ex_extracts.glob("*.json"):
                atomic_write_json(
                    draft_dir / src.name,
                    json.loads(src.read_text(encoding="utf-8")),
                )

        # 3. mark promoted
        now = _now_iso()
        updated = ex.model_copy(update={"status": "promoted", "promoted_at": now})
        atomic_write_json(
            experiment_meta_path(workspace, project_id, experiment_id),
            updated.model_dump(mode="json"),
        )


async def delete_experiment(
    workspace: Path,
    project_id: str,
    experiment_id: str,
) -> None:
    """Physically remove experiments/{exp_id}/. Blocks deletion of a promoted
    experiment (audit trail must be preserved). Raises ExperimentNotFoundError
    if the experiment doesn't exist; ExperimentInUseError if status='promoted'.
    """
    import shutil

    async with project_lock(workspace, project_id):
        ex = await read_experiment(workspace, project_id, experiment_id)
        if ex.status == "promoted":
            raise ExperimentInUseError(
                f"cannot delete {experiment_id}: status is 'promoted' (audit trail)"
            )
        edir = experiment_dir(workspace, project_id, experiment_id)
        if edir.exists():
            shutil.rmtree(edir)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_experiment.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/experiment.py backend/tests/unit/test_tool_experiment.py
git commit -m "feat(m9.3): promote_experiment + delete_experiment (audit-preserving)"
```

---

## Task 7: Cross-reference checks for `delete_prompt` / `delete_model`

**Files:**
- Modify: `backend/app/tools/experiment.py` (append helpers)
- Modify: `backend/app/tools/prompt.py` (extend `delete_prompt`)
- Modify: `backend/app/tools/model.py` (extend `delete_model`)
- Modify: `backend/tests/unit/test_tool_prompt.py` (append cross-ref test)
- Modify: `backend/tests/unit/test_tool_model.py` (append cross-ref test)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_tool_prompt.py`:

```python
async def test_delete_prompt_blocked_by_non_archived_experiment_reference(
    workspace: Path,
) -> None:
    from app.tools.experiment import archive_experiment, create_experiment
    from app.tools.prompt import (
        PromptInUseError,
        create_prompt,
        delete_prompt,
        switch_active_prompt,
    )
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "x", "type": "string", "description": "d", "required": False}
    ])
    # also seed the active model so create_experiment can resolve it
    atomic_write_json(model_path(workspace, pid, "m_default"), {
        "model_id": "m_default", "label": "Default",
        "provider": "google", "provider_model_id": "gemini-2.5-flash",
        "params": {}, "created_at": _now(),
    })
    project = json.loads(project_json_path(workspace, pid).read_text())
    project["active_model_id"] = "m_default"
    atomic_write_json(project_json_path(workspace, pid), project)

    variant_id = await create_prompt(workspace, pid, label="v")
    exp_id = await create_experiment(workspace, pid, prompt_id=variant_id)
    # variant is not active so the M9.2 "is active" check won't fire — but the
    # M9.3 cross-ref check should.
    with pytest.raises(PromptInUseError, match="referenced by experiment"):
        await delete_prompt(workspace, pid, variant_id)

    await archive_experiment(workspace, pid, exp_id)
    # after archive, the deletion succeeds
    await delete_prompt(workspace, pid, variant_id)
```

Append to `backend/tests/unit/test_tool_model.py`:

```python
async def test_delete_model_blocked_by_non_archived_experiment_reference(
    workspace: Path,
) -> None:
    from app.tools.experiment import archive_experiment, create_experiment
    from app.tools.model import ModelInUseError, create_model, delete_model
    # similar setup to the prompt test above
    ...
    new_mid = await create_model(
        workspace, pid, label="haiku",
        provider="anthropic", provider_model_id="claude-haiku-4-5-20251001",
        params={},
    )
    exp_id = await create_experiment(workspace, pid, model_id=new_mid)
    with pytest.raises(ModelInUseError, match="referenced by experiment"):
        await delete_model(workspace, pid, new_mid)
    await archive_experiment(workspace, pid, exp_id)
    await delete_model(workspace, pid, new_mid)
```

(Both tests should leverage the existing `_seed_active_project` helpers in their respective test files; fill in the symmetric model-test setup analogous to the prompt test above.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_prompt.py tests/unit/test_tool_model.py -v -k "blocked_by_non_archived"`
Expected: FAIL with no `referenced by experiment` message — the existing `delete_*` only checks active.

- [ ] **Step 3: Add reference-check helpers to `experiment.py`**

Append to `backend/app/tools/experiment.py`:

```python
async def experiments_referencing_prompt(
    workspace: Path,
    project_id: str,
    prompt_id: str,
    *,
    exclude_archived: bool = True,
) -> list[str]:
    """Return experiment_ids that reference this prompt. Archived experiments
    are excluded by default; promoted ones are included (audit trail blocks
    deletion of the prompt they point at)."""
    edir = experiments_dir(workspace, project_id)
    if not edir.exists():
        return []
    hits: list[str] = []
    for sub in edir.iterdir():
        if not sub.is_dir():
            continue
        meta = sub / "meta.json"
        if not meta.exists():
            continue
        ex = Experiment(**json.loads(meta.read_text(encoding="utf-8")))
        if exclude_archived and ex.status == "archived":
            continue
        if ex.prompt_id == prompt_id:
            hits.append(ex.experiment_id)
    return hits


async def experiments_referencing_model(
    workspace: Path,
    project_id: str,
    model_id: str,
    *,
    exclude_archived: bool = True,
) -> list[str]:
    """Symmetric to experiments_referencing_prompt, keyed on model_id."""
    edir = experiments_dir(workspace, project_id)
    if not edir.exists():
        return []
    hits: list[str] = []
    for sub in edir.iterdir():
        if not sub.is_dir():
            continue
        meta = sub / "meta.json"
        if not meta.exists():
            continue
        ex = Experiment(**json.loads(meta.read_text(encoding="utf-8")))
        if exclude_archived and ex.status == "archived":
            continue
        if ex.model_id == model_id:
            hits.append(ex.experiment_id)
    return hits
```

- [ ] **Step 4: Extend `delete_prompt`**

Edit `backend/app/tools/prompt.py` — find the `delete_prompt` function. Just before the unlink, after the active-check, add the experiment-reference check:

```python
# Existing active-check stays...
if project.get("active_prompt_id") == prompt_id:
    raise PromptInUseError(
        f"cannot delete {prompt_id}: it is the active prompt; switch active first"
    )
# NEW: experiment-reference check
from app.tools.experiment import experiments_referencing_prompt
refs = await experiments_referencing_prompt(workspace, project_id, prompt_id)
if refs:
    raise PromptInUseError(
        f"cannot delete {prompt_id}: referenced by experiment(s) {refs}; "
        "archive them first"
    )
pp.unlink()
```

- [ ] **Step 5: Extend `delete_model` symmetrically**

Edit `backend/app/tools/model.py` `delete_model` analogously:

```python
if project.get("active_model_id") == model_id:
    raise ModelInUseError(
        f"cannot delete {model_id}: it is the active model; switch active first"
    )
from app.tools.experiment import experiments_referencing_model
refs = await experiments_referencing_model(workspace, project_id, model_id)
if refs:
    raise ModelInUseError(
        f"cannot delete {model_id}: referenced by experiment(s) {refs}; "
        "archive them first"
    )
mp.unlink()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_prompt.py tests/unit/test_tool_model.py -v`
Expected: all PASS (including the existing M9.2 active-check tests, which the new code path leaves intact).

- [ ] **Step 7: Commit**

```bash
git add backend/app/tools/experiment.py backend/app/tools/prompt.py backend/app/tools/model.py \
        backend/tests/unit/test_tool_prompt.py backend/tests/unit/test_tool_model.py
git commit -m "feat(m9.3): block delete_prompt/delete_model when non-archived experiment references"
```

---

## Task 8: HTTP routes — `/lab/projects/{pid}/experiments*`

**Files:**
- Create: `backend/app/api/routes/experiments.py`
- Create: `backend/tests/unit/test_routes_experiments.py`
- Modify: `backend/app/main.py` (mount the router)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_routes_experiments.py`:

```python
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    doc_path,
    docs_dir,
    experiment_meta_path,
    model_path,
    project_json_path,
    prompt_path,
)


def _now() -> str:
    return "2026-05-13T00:00:00+00:00"


def _seed_axes(workspace: Path, pid: str) -> None:
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "project_id": pid, "name": "Test", "created_at": _now(),
        "active_prompt_id": "pr_baseline", "active_model_id": "m_default",
    })
    atomic_write_json(prompt_path(workspace, pid, "pr_baseline"), {
        "prompt_id": "pr_baseline", "label": "Baseline",
        "schema": [{"name": "supplier", "type": "string", "description": "d", "required": False}],
        "global_notes": "", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, pid, "m_default"), {
        "model_id": "m_default", "label": "Default",
        "provider": "google", "provider_model_id": "gemini-2.5-flash",
        "params": {}, "created_at": _now(),
    })


async def test_list_experiments_empty(workspace, monkeypatch):
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.get(f"/lab/projects/{pid}/experiments")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_experiments_after_create(workspace, monkeypatch):
    from app.tools.experiment import create_experiment
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    await create_experiment(workspace, pid, label="trial 1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.get(f"/lab/projects/{pid}/experiments")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["label"] == "trial 1"
    assert rows[0]["status"] == "draft"


async def test_get_experiment_meta(workspace, monkeypatch):
    from app.tools.experiment import create_experiment
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.get(f"/lab/projects/{pid}/experiments/{eid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["experiment_id"] == eid
    assert body["prompt_id"] == "pr_baseline"


async def test_get_extract_404_when_not_run(workspace, monkeypatch):
    from app.tools.experiment import create_experiment
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    did = "d_doc000000000"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.get(f"/lab/projects/{pid}/experiments/{eid}/extracts/{did}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "experiment_extract_not_found"


async def test_run_extract_endpoint_writes_and_returns(workspace, monkeypatch, fake_provider):
    """POST .../extracts/{doc_id} runs extract_with_experiment and returns the
    payload. Use a monkeypatched get_provider_for_model so we don't hit a real
    LLM."""
    from app import provider as provider_pkg
    from app.tools.experiment import create_experiment
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(
        provider_pkg, "get_provider_for_model",
        lambda *_a, **_k: fake_provider,
    )
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    did = "d_doc000000000"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, did, "txt").write_text("hi")
    eid = await create_experiment(workspace, pid)
    fake_provider._payload = {"entities": [{"supplier": "ACME"}]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post(f"/lab/projects/{pid}/experiments/{eid}/extracts/{did}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entities"][0]["supplier"] == "ACME"
    # subsequent GET now returns 200
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp2 = await ac.get(f"/lab/projects/{pid}/experiments/{eid}/extracts/{did}")
    assert resp2.status_code == 200


async def test_invalid_project_id_rejected(workspace, monkeypatch):
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.get("/lab/projects/..%2Fattacker/experiments")
    assert resp.status_code in (400, 404)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_routes_experiments.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the router**

Create `backend/app/api/routes/experiments.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.provider import get_provider_for_model
from app.tools.experiment import (
    ExperimentNotFoundError,
    extract_with_experiment,
    list_experiments,
    read_experiment,
)
from app.tools.model import read_model
from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import experiment_extract_path, project_json_path


router = APIRouter()


def _project_or_404(pid: str) -> Path:
    safe_project_id(pid)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, pid).exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return settings.workspace_root


@router.get("/lab/projects/{project_id}/experiments")
async def get_project_experiments(
    project_id: str,
    include_archived: bool = False,
) -> list[dict]:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    return await list_experiments(
        workspace, project_id, include_archived=include_archived,
    )


@router.get("/lab/projects/{project_id}/experiments/{experiment_id}")
async def get_project_experiment(project_id: str, experiment_id: str) -> dict:
    workspace = _project_or_404(project_id)
    try:
        ex = await read_experiment(workspace, project_id, experiment_id)
    except ExperimentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_not_found"},
        )
    return ex.model_dump(mode="json")


@router.get(
    "/lab/projects/{project_id}/experiments/{experiment_id}/extracts/{doc_id}",
)
async def get_experiment_extract(
    project_id: str, experiment_id: str, doc_id: str,
) -> dict:
    workspace = _project_or_404(project_id)
    # validate experiment exists (raises 404 if not)
    try:
        await read_experiment(workspace, project_id, experiment_id)
    except ExperimentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_not_found"},
        )
    p = experiment_extract_path(workspace, project_id, experiment_id, doc_id)
    if not p.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_extract_not_found"},
        )
    return json.loads(p.read_text(encoding="utf-8"))


@router.post(
    "/lab/projects/{project_id}/experiments/{experiment_id}/extracts/{doc_id}",
)
async def run_experiment_extract(
    project_id: str, experiment_id: str, doc_id: str,
) -> dict:
    workspace = _project_or_404(project_id)
    try:
        ex = await read_experiment(workspace, project_id, experiment_id)
    except ExperimentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_not_found"},
        )
    model = await read_model(workspace, project_id, ex.model_id)
    provider = get_provider_for_model(model.provider_model_id)
    payload = await extract_with_experiment(
        workspace, project_id, experiment_id, doc_id, provider=provider,
    )
    return payload
```

Mount in `backend/app/main.py` (find the existing router-include block and add):

```python
from app.api.routes import experiments as experiments_route
# ...
app.include_router(experiments_route.router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_routes_experiments.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/experiments.py backend/app/main.py \
        backend/tests/unit/test_routes_experiments.py
git commit -m "feat(m9.3): HTTP routes for experiments (list/get/get-extract/run-extract)"
```

---

## Task 9: MCP tool registrations (7 new `@tool` wrappers)

**Files:**
- Modify: `backend/app/tools/__init__.py` (register 7 tools, expose in `emerge_tools` server)
- Modify: `backend/tests/unit/test_tool_registration.py` (assert new tools exist)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_tool_registration.py` (or add a new test if the existing file structure differs):

```python
def test_registers_experiment_axis_tools(workspace):
    from app.tools import build_emerge_tools
    from app.provider.base import Provider

    class _FakeProvider:
        pass

    server, tools_by_name = build_emerge_tools(
        workspace=workspace, provider=_FakeProvider(),
    )
    for name in [
        "create_experiment",
        "extract_with_experiment",
        "run_experiment_eval",
        "promote_experiment",
        "archive_experiment",
        "list_experiments",
        "delete_experiment",
    ]:
        assert name in tools_by_name, f"missing tool: {name}"
```

(If `build_emerge_tools` does not currently return a dict alongside the server, adjust the assertion to whatever shape the existing tests use — the goal is to assert these 7 names are registered.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`
Expected: FAIL — 7 missing tools.

- [ ] **Step 3: Register the wrappers**

In `backend/app/tools/__init__.py`, after the existing model-tool block, add:

```python
from app.tools import experiment as experiment_mod
# (the import goes alongside the existing `from app.tools import model as model_mod`)

# Inside build_emerge_tools, after the delete_model block:

    @tool(
        "create_experiment",
        "Create an experiment referencing a (prompt_id, model_id) pair. Both axes "
        "default to the project's active. Returns the new experiment_id.",
        {"project_id": str, "label": str, "prompt_id": str, "model_id": str},
    )
    async def t_create_experiment(args: dict[str, Any]) -> dict[str, Any]:
        eid = await experiment_mod.create_experiment(
            workspace, args["project_id"],
            label=args.get("label") or None,
            prompt_id=args.get("prompt_id") or None,
            model_id=args.get("model_id") or None,
        )
        return {"content": [{"type": "text", "text": eid}]}

    @tool(
        "extract_with_experiment",
        "Run an experiment's (prompt, model) pair on a single doc; writes "
        "experiments/{experiment_id}/extracts/{doc_id}.json. Returns the payload.",
        {"project_id": str, "experiment_id": str, "doc_id": str},
    )
    async def t_extract_with_experiment(args: dict[str, Any]) -> dict[str, Any]:
        ex = await experiment_mod.read_experiment(
            workspace, args["project_id"], args["experiment_id"],
        )
        model = await model_mod.read_model(
            workspace, args["project_id"], ex.model_id,
        )
        from app.provider import get_provider_for_model
        exp_provider = get_provider_for_model(model.provider_model_id)
        payload = await experiment_mod.extract_with_experiment(
            workspace, args["project_id"], args["experiment_id"], args["doc_id"],
            provider=exp_provider,
        )
        return {"content": [{"type": "text", "text": _json.dumps(payload)}]}

    @tool(
        "run_experiment_eval",
        "Loop reviewed/ docs through the experiment's (prompt, model); writes "
        "per-doc extracts and computes overall + per-field + per-doc scores. "
        "Returns the eval dict and sets status='ran'.",
        {"project_id": str, "experiment_id": str},
    )
    async def t_run_experiment_eval(args: dict[str, Any]) -> dict[str, Any]:
        ex = await experiment_mod.read_experiment(
            workspace, args["project_id"], args["experiment_id"],
        )
        model = await model_mod.read_model(
            workspace, args["project_id"], ex.model_id,
        )
        from app.provider import get_provider_for_model
        exp_provider = get_provider_for_model(model.provider_model_id)
        ev = await experiment_mod.run_experiment_eval(
            workspace, args["project_id"], args["experiment_id"],
            provider=exp_provider,
        )
        return {"content": [{"type": "text", "text": _json.dumps(ev)}]}

    @tool(
        "promote_experiment",
        "Set the experiment's (prompt_id, model_id) as the project's active pair; "
        "clear predictions/_draft/ and re-seed from the experiment's extracts. "
        "Marks experiment status='promoted' (audit trail).",
        {"project_id": str, "experiment_id": str},
    )
    async def t_promote_experiment(args: dict[str, Any]) -> dict[str, Any]:
        await experiment_mod.promote_experiment(
            workspace, args["project_id"], args["experiment_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "archive_experiment",
        "Mark an experiment as archived (excluded from default lists, not deleted). "
        "Cannot archive a promoted experiment.",
        {"project_id": str, "experiment_id": str},
    )
    async def t_archive_experiment(args: dict[str, Any]) -> dict[str, Any]:
        await experiment_mod.archive_experiment(
            workspace, args["project_id"], args["experiment_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "list_experiments",
        "List experiments in a project. Archived experiments excluded unless "
        "include_archived=true.",
        {"project_id": str, "include_archived": bool},
    )
    async def t_list_experiments(args: dict[str, Any]) -> dict[str, Any]:
        rows = await experiment_mod.list_experiments(
            workspace, args["project_id"],
            include_archived=bool(args.get("include_archived", False)),
        )
        return {"content": [{"type": "text", "text": _json.dumps(rows)}]}

    @tool(
        "delete_experiment",
        "Physically remove an experiment directory. Cannot delete a promoted "
        "experiment (audit trail).",
        {"project_id": str, "experiment_id": str},
    )
    async def t_delete_experiment(args: dict[str, Any]) -> dict[str, Any]:
        await experiment_mod.delete_experiment(
            workspace, args["project_id"], args["experiment_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}
```

And add these 7 `t_*` references to the existing `mcp_server` tool list (mirror how `t_extract_one`/`t_extract_batch` were added at the registration site near the bottom of `build_emerge_tools`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`
Expected: PASS.

- [ ] **Step 5: Smoke-check the whole backend test suite**

Run: `cd backend && uv run pytest -v`
Expected: all PASS — no regressions in chat / extract / publish / autoresearch.

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/__init__.py backend/tests/unit/test_tool_registration.py
git commit -m "feat(m9.3): register 7 experiment MCP tools"
```

---

## Task 10: Skill markdown update (agent guidance)

**Files:**
- Modify: `backend/app/skills/emerge_extractor.md`

- [ ] **Step 1: Add the experiment workflow section**

Edit `backend/app/skills/emerge_extractor.md`. In the "Risk gates" section, add these bullets (alphabetically, around the `switch_active_prompt` line):

```markdown
- Promoting an experiment (`promote_experiment`): always confirm. This sets the
  experiment's prompt + model as active AND replaces predictions/_draft/ with
  the experiment's per-doc extracts. The experiment is then marked `promoted`
  (audit trail; the experiment dir itself is NOT deleted).
- Deleting an experiment (`delete_experiment`): always confirm. Cannot delete
  a promoted experiment.
- Running an experiment eval (`run_experiment_eval`): no need to confirm —
  read-only against the user's reviewed/ ground truth, but the per-doc extract
  loop calls the experiment's LLM N times where N = number of reviewed docs.
  Surface the count up front: "this will call <provider/model> N times".
```

In the body of the skill, before the Risk-gates section but after the discipline rules, add a short "Experiment axis" subsection:

```markdown
## Experiment axis (M9.3)

The user can isolate a (prompt_variant, model_config) pair as an *experiment*
without touching the active pair. Use this when the user says "试试" / "A/B"
/ "对比 model X" / "看看 prompt 改 description 的效果".

Workflow:
1. `create_experiment(label, prompt_id=None, model_id=None)` — both axes
   default to active.
2. `extract_with_experiment(experiment_id, doc_id)` — single-doc probe; the
   user typically asks for this on 1–2 specific docs first to eyeball.
3. (optional) `run_experiment_eval(experiment_id)` — score against the full
   reviewed/ set; emits ExperimentEval with per-field + per-doc breakdown.
4. `promote_experiment(experiment_id)` — flip active to the experiment's pair
   when the user confirms.
5. `archive_experiment(experiment_id)` — for the experiments the user
   rejected. Don't delete unless asked.

The user views per-experiment extracts in Review mode by clicking the `[+]`
button on the tab strip — the agent does NOT need to switch the user there
manually.
```

In the "Discipline" red-line section, add this bullet (near "AutoResearch never auto-promotes"):

```markdown
- Experiments NEVER auto-promote. `promote_experiment` is the only path that
  switches active prompt/model based on an experiment; it requires explicit
  user confirmation per the risk-gate above.
```

- [ ] **Step 2: Smoke-run the smallest chat test that exercises skill loading**

Run: `cd backend && uv run pytest tests/unit/test_chat_service.py -v` (or equivalent — check the existing test that asserts skill markdown loads without parse error).
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/app/skills/emerge_extractor.md
git commit -m "docs(m9.3): agent guidance for experiment axis + promote risk gate"
```

---

## Task 11: Frontend types + API client

**Files:**
- Modify: `frontend/src/types/review.ts` (append `Experiment` summary + `ExperimentExtractPayload` types)
- Modify: `frontend/src/lib/api.ts` (append 4 functions)
- Create: `frontend/tests/unit/lib/api-experiments.test.ts` (or extend an existing api test file)

- [ ] **Step 1: Write the failing test**

Add to `frontend/tests/unit/lib/api-experiments.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'

import {
  getExperiment,
  getExperimentExtract,
  listExperiments,
  runExperimentExtract,
} from '../../../src/lib/api'

describe('experiment api', () => {
  it('listExperiments calls the right URL with include_archived', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    })
    vi.stubGlobal('fetch', fetchMock)
    await listExperiments('p_test12345678', { includeArchived: true })
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/lab/projects/p_test12345678/experiments?include_archived=true'),
      expect.any(Object),
    )
  })

  it('getExperimentExtract returns null on 404', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 404, json: async () => ({
        detail: { error_code: 'experiment_extract_not_found' },
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const out = await getExperimentExtract('p_x', 'ex_y', 'd_z')
    expect(out).toBeNull()
  })

  it('runExperimentExtract POSTs and returns payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ entities: [{ x: 1 }] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const out = await runExperimentExtract('p_x', 'ex_y', 'd_z')
    expect(out.entities[0].x).toBe(1)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/lab/projects/p_x/experiments/ex_y/extracts/d_z'),
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('getExperiment returns meta blob', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({
        experiment_id: 'ex_abc', label: 't', prompt_id: 'pr', model_id: 'm',
        status: 'draft', created_at: '2026-05-13', notes: '', eval: null,
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const meta = await getExperiment('p_x', 'ex_abc')
    expect(meta.label).toBe('t')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- api-experiments`
Expected: FAIL — imports don't resolve.

- [ ] **Step 3: Add types**

Append to `frontend/src/types/review.ts` (or a new `frontend/src/types/experiment.ts` if `review.ts` is getting too crowded — judgement call, mirror the existing convention):

```ts
export interface ExperimentSummary {
  experiment_id: string
  label: string
  prompt_id: string
  model_id: string
  status: 'draft' | 'ran' | 'archived' | 'promoted'
  created_at: string
  score: number | null
}

export interface ExperimentEval {
  ran_at: string
  score: number
  per_field: Record<string, number>
  per_doc: Record<string, number>
  run_id: string
  coverage: number
}

export interface Experiment {
  experiment_id: string
  label: string
  prompt_id: string
  model_id: string
  status: 'draft' | 'ran' | 'archived' | 'promoted'
  created_at: string
  promoted_at: string | null
  notes: string
  eval: ExperimentEval | null
}

export interface ExperimentExtractPayload {
  entities: Record<string, unknown>[]
  _evidence?: Record<string, number | null>[] | null
  _notes?: Record<string, string>
}
```

- [ ] **Step 4: Add api client functions**

Append to `frontend/src/lib/api.ts`:

```ts
import type {
  Experiment,
  ExperimentExtractPayload,
  ExperimentSummary,
} from '../types/review'  // (or wherever you placed the types)

export async function listExperiments(
  projectId: string,
  opts?: { includeArchived?: boolean },
): Promise<ExperimentSummary[]> {
  const q = opts?.includeArchived ? '?include_archived=true' : ''
  const resp = await fetch(`/lab/projects/${projectId}/experiments${q}`)
  if (!resp.ok) throw new Error(`listExperiments ${resp.status}`)
  return await resp.json()
}

export async function getExperiment(
  projectId: string,
  experimentId: string,
): Promise<Experiment> {
  const resp = await fetch(`/lab/projects/${projectId}/experiments/${experimentId}`)
  if (!resp.ok) throw new Error(`getExperiment ${resp.status}`)
  return await resp.json()
}

export async function getExperimentExtract(
  projectId: string,
  experimentId: string,
  docId: string,
): Promise<ExperimentExtractPayload | null> {
  const resp = await fetch(
    `/lab/projects/${projectId}/experiments/${experimentId}/extracts/${docId}`,
  )
  if (resp.status === 404) return null
  if (!resp.ok) throw new Error(`getExperimentExtract ${resp.status}`)
  return await resp.json()
}

export async function runExperimentExtract(
  projectId: string,
  experimentId: string,
  docId: string,
): Promise<ExperimentExtractPayload> {
  const resp = await fetch(
    `/lab/projects/${projectId}/experiments/${experimentId}/extracts/${docId}`,
    { method: 'POST' },
  )
  if (!resp.ok) throw new Error(`runExperimentExtract ${resp.status}`)
  return await resp.json()
}
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd frontend && npm test -- api-experiments`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/review.ts frontend/src/lib/api.ts \
        frontend/tests/unit/lib/api-experiments.test.ts
git commit -m "feat(m9.3): frontend types + api client for experiments"
```

---

## Task 12: `useExperiments` Zustand store

**Files:**
- Create: `frontend/src/stores/experiments.ts`
- Create: `frontend/tests/unit/stores/experiments.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/stores/experiments.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useExperiments } from '../../../src/stores/experiments'

describe('useExperiments', () => {
  beforeEach(() => {
    useExperiments.setState({ byProject: {} })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('list fetches and caches per project', async () => {
    const rows = [
      { experiment_id: 'ex_a', label: 't', prompt_id: 'pr', model_id: 'm',
        status: 'draft', created_at: '2026-05-13', score: null },
    ]
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => rows,
    })
    vi.stubGlobal('fetch', fetchMock)
    await useExperiments.getState().load('p_test12345678')
    const slice = useExperiments.getState().byProject['p_test12345678']
    expect(slice).toBeDefined()
    expect(slice.list.length).toBe(1)
    // a second load is a cache hit (no new fetch)
    await useExperiments.getState().load('p_test12345678')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('refresh forces re-fetch', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    })
    vi.stubGlobal('fetch', fetchMock)
    await useExperiments.getState().load('p_x')
    await useExperiments.getState().refresh('p_x')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('invalidate clears the cache so next load refetches', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    })
    vi.stubGlobal('fetch', fetchMock)
    await useExperiments.getState().load('p_x')
    useExperiments.getState().invalidate('p_x')
    await useExperiments.getState().load('p_x')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- stores/experiments`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the store**

Create `frontend/src/stores/experiments.ts`:

```ts
import { create } from 'zustand'

import { listExperiments } from '../lib/api'
import type { ExperimentSummary } from '../types/review'

interface ProjectSlice {
  list: ExperimentSummary[]
  loading: boolean
  err: string | null
  loadedAt: number | null
}

interface State {
  byProject: Record<string, ProjectSlice>
  load: (projectId: string) => Promise<void>
  refresh: (projectId: string) => Promise<void>
  invalidate: (projectId: string) => void
}

function emptySlice(): ProjectSlice {
  return { list: [], loading: false, err: null, loadedAt: null }
}

async function fetchAndStore(
  projectId: string,
  set: (partial: Partial<State> | ((s: State) => Partial<State>)) => void,
) {
  set(s => ({
    byProject: { ...s.byProject, [projectId]: {
      ...(s.byProject[projectId] ?? emptySlice()), loading: true, err: null,
    } },
  }))
  try {
    const rows = await listExperiments(projectId)
    set(s => ({
      byProject: { ...s.byProject, [projectId]: {
        list: rows, loading: false, err: null, loadedAt: Date.now(),
      } },
    }))
  } catch (e) {
    set(s => ({
      byProject: { ...s.byProject, [projectId]: {
        ...(s.byProject[projectId] ?? emptySlice()),
        loading: false, err: String(e),
      } },
    }))
  }
}

export const useExperiments = create<State>((set, get) => ({
  byProject: {},
  load: async (projectId: string) => {
    const slice = get().byProject[projectId]
    if (slice && slice.loadedAt !== null) return
    await fetchAndStore(projectId, set)
  },
  refresh: async (projectId: string) => {
    await fetchAndStore(projectId, set)
  },
  invalidate: (projectId: string) => {
    set(s => {
      const next = { ...s.byProject }
      delete next[projectId]
      return { byProject: next }
    })
  },
}))
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd frontend && npm test -- stores/experiments`
Expected: all PASS.

- [ ] **Step 5: Cross-store refresh hook**

Per INSIGHTS #9, hooking into the SSE tool stream so the store refreshes when the agent calls `create_experiment` / `promote_experiment` / etc. Find the existing `handleToolResult` in `frontend/src/stores/chat.ts` and add to the tool-name switch:

```ts
import { useExperiments } from './experiments'

// ...inside handleToolResult, in the switch on tool name:
case 'mcp__emerge_tools__create_experiment':
case 'mcp__emerge_tools__archive_experiment':
case 'mcp__emerge_tools__delete_experiment':
case 'mcp__emerge_tools__promote_experiment':
case 'mcp__emerge_tools__run_experiment_eval':
  void useExperiments.getState().refresh(projectId)
  // promote also changes active prompt/model + predictions
  if (toolName.endsWith('promote_experiment')) {
    void usePrompts.getState().refresh(projectId)
    void useModels.getState().refresh(projectId)
    // predictions/_draft is reflected through useReview when it next opens; we
    // also invalidate it so an open review re-fetches:
    useSchema.getState().invalidate?.(projectId)
  }
  break
```

(Match the exact pattern used by the existing M9.2 hooks for `usePrompts` / `useModels` — see the M9.2 plan's Task 12 for prior art.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/experiments.ts frontend/tests/unit/stores/experiments.test.ts \
        frontend/src/stores/chat.ts
git commit -m "feat(m9.3): useExperiments store + SSE refresh hook"
```

---

## Task 13: Extend `useReview` with tab state

**Files:**
- Modify: `frontend/src/stores/review.ts`
- Create: `frontend/tests/unit/stores/review-tabs.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/stores/review-tabs.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useReview } from '../../../src/stores/review'

describe('useReview tab state', () => {
  beforeEach(() => {
    useReview.setState({
      activeProjectId: null, activeDocId: null,
      entities: [], evidence: null, notes: {},
      attachedExperimentIds: [], activeTabKey: 'active', extractsByExp: {},
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ entities: [{}] }),
    }))
  })

  it('attachExperiment appends to attached list and lazy-loads extract', async () => {
    useReview.setState({ activeProjectId: 'p_x', activeDocId: 'd_y' })
    await useReview.getState().attachExperiment('ex_a')
    const s = useReview.getState()
    expect(s.attachedExperimentIds).toContain('ex_a')
    expect(s.extractsByExp['ex_a']).toBeTruthy()
  })

  it('attachExperiment is idempotent', async () => {
    useReview.setState({ activeProjectId: 'p_x', activeDocId: 'd_y' })
    await useReview.getState().attachExperiment('ex_a')
    await useReview.getState().attachExperiment('ex_a')
    expect(useReview.getState().attachedExperimentIds).toEqual(['ex_a'])
  })

  it('detachExperiment removes from list but keeps cached extract', async () => {
    useReview.setState({ activeProjectId: 'p_x', activeDocId: 'd_y' })
    await useReview.getState().attachExperiment('ex_a')
    useReview.getState().detachExperiment('ex_a')
    const s = useReview.getState()
    expect(s.attachedExperimentIds).toEqual([])
    expect(s.extractsByExp['ex_a']).toBeTruthy()
    // active tab also resets to 'active'
    expect(s.activeTabKey).toBe('active')
  })

  it('setActiveTab switches tab without clearing other state', () => {
    useReview.setState({
      attachedExperimentIds: ['ex_a'], activeTabKey: 'active',
    })
    useReview.getState().setActiveTab('ex_a')
    expect(useReview.getState().activeTabKey).toBe('ex_a')
  })

  it('open() resets tab state when doc changes', async () => {
    useReview.setState({
      activeProjectId: 'p_x', activeDocId: 'd_old',
      attachedExperimentIds: ['ex_a'], activeTabKey: 'ex_a',
      extractsByExp: { ex_a: { entities: [{}] } },
    })
    // mock getReviewed / getPrediction to keep .open() happy
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ entities: [{}] }),
    }))
    await useReview.getState().open('p_x', 'd_new')
    expect(useReview.getState().attachedExperimentIds).toEqual([])
    expect(useReview.getState().activeTabKey).toBe('active')
    expect(useReview.getState().extractsByExp).toEqual({})
  })

  it('runExperimentExtract POSTs and overrides cached extract', async () => {
    const postMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ entities: [{ supplier: 'X' }] }),
    })
    vi.stubGlobal('fetch', postMock)
    useReview.setState({ activeProjectId: 'p_x', activeDocId: 'd_y' })
    await useReview.getState().runExperimentExtract('ex_a')
    const s = useReview.getState()
    expect((s.extractsByExp['ex_a']?.entities[0] as any)?.supplier).toBe('X')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- review-tabs`
Expected: FAIL — `attachExperiment` etc. don't exist.

- [ ] **Step 3: Extend the store**

Edit `frontend/src/stores/review.ts`. Add to the `interface State`:

```ts
attachedExperimentIds: string[]
activeTabKey: 'active' | string  // 'active' or experiment_id
extractsByExp: Record<string, ExperimentExtractPayload | null>
attachExperiment: (experimentId: string) => Promise<void>
detachExperiment: (experimentId: string) => void
setActiveTab: (key: 'active' | string) => void
loadExperimentExtract: (experimentId: string) => Promise<void>
runExperimentExtract: (experimentId: string) => Promise<void>
```

Add to the `create` body initial state:

```ts
attachedExperimentIds: [],
activeTabKey: 'active',
extractsByExp: {},
```

Modify `open()`:

```ts
open: async (projectId, docId) => {
  set({
    activeProjectId: projectId, activeDocId: docId,
    page: 1, pageCount: 1, loading: true, err: null,
    entities: [], evidence: null, notes: {},
    // ── tab state reset ──
    attachedExperimentIds: [],
    activeTabKey: 'active',
    extractsByExp: {},
  })
  try {
    // ... existing reviewed/prediction load logic unchanged ...
  } catch (e: unknown) {
    set({ err: String(e), loading: false })
  }
},
```

Add the new methods inside the store:

```ts
attachExperiment: async (experimentId) => {
  const { attachedExperimentIds } = get()
  if (attachedExperimentIds.includes(experimentId)) return
  set(s => ({ attachedExperimentIds: [...s.attachedExperimentIds, experimentId] }))
  await get().loadExperimentExtract(experimentId)
},

detachExperiment: (experimentId) => {
  set(s => ({
    attachedExperimentIds: s.attachedExperimentIds.filter(x => x !== experimentId),
    activeTabKey: s.activeTabKey === experimentId ? 'active' : s.activeTabKey,
  }))
},

setActiveTab: (key) => set({ activeTabKey: key }),

loadExperimentExtract: async (experimentId) => {
  const { activeProjectId, activeDocId } = get()
  if (!activeProjectId || !activeDocId) return
  // already cached?
  if (get().extractsByExp[experimentId]) return
  const payload = await getExperimentExtract(activeProjectId, experimentId, activeDocId)
  set(s => ({ extractsByExp: { ...s.extractsByExp, [experimentId]: payload } }))
},

runExperimentExtract: async (experimentId) => {
  const { activeProjectId, activeDocId } = get()
  if (!activeProjectId || !activeDocId) return
  const payload = await runExperimentExtract(activeProjectId, experimentId, activeDocId)
  set(s => ({ extractsByExp: { ...s.extractsByExp, [experimentId]: payload } }))
},
```

Imports at the top:

```ts
import { getExperimentExtract, runExperimentExtract } from '../lib/api'
import type { ExperimentExtractPayload } from '../types/review'
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd frontend && npm test -- review-tabs`
Expected: all PASS.

Also re-run the existing review-store test (if any) to confirm no regression:

`cd frontend && npm test -- stores/review`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/review.ts frontend/tests/unit/stores/review-tabs.test.ts
git commit -m "feat(m9.3): useReview tab state (attach/detach/setActiveTab + lazy extract load)"
```

---

## Task 14: `ExperimentTabStrip` component

**Files:**
- Create: `frontend/src/components/ReviewMode/ExperimentTabStrip.tsx`
- Create: `frontend/tests/unit/ReviewMode/ExperimentTabStrip.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/ReviewMode/ExperimentTabStrip.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ExperimentTabStrip from '../../../src/components/ReviewMode/ExperimentTabStrip'

const EXPERIMENTS = [
  { experiment_id: 'ex_a', label: 'try Gemma4', prompt_id: 'pr_x', model_id: 'm_y',
    status: 'draft', created_at: '2026-05-13', score: null },
  { experiment_id: 'ex_b', label: 'try notes', prompt_id: 'pr_z', model_id: 'm_y',
    status: 'ran', created_at: '2026-05-13', score: 0.91 },
]

describe('ExperimentTabStrip', () => {
  it('renders the ⭐ Active tab plus each attached experiment', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        attachedExperimentIds={['ex_a', 'ex_b']}
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        onAttach={() => {}}
        onDetach={() => {}}
        modelLabels={{ m_y: 'Gemma 4' }}
      />
    )
    expect(screen.getByText(/Active/i)).toBeInTheDocument()
    expect(screen.getByText('try Gemma4')).toBeInTheDocument()
    expect(screen.getByText('try notes')).toBeInTheDocument()
  })

  it('clicking a tab calls onSwitch', () => {
    const onSwitch = vi.fn()
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        attachedExperimentIds={['ex_a']}
        availableExperiments={EXPERIMENTS}
        onSwitch={onSwitch}
        onAttach={() => {}}
        onDetach={() => {}}
        modelLabels={{}}
      />
    )
    fireEvent.click(screen.getByText('try Gemma4'))
    expect(onSwitch).toHaveBeenCalledWith('ex_a')
  })

  it('[+] popover lists unattached non-archived experiments', () => {
    render(
      <ExperimentTabStrip
        activeTabKey="active"
        attachedExperimentIds={['ex_a']}
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        onAttach={() => {}}
        onDetach={() => {}}
        modelLabels={{}}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: '+' }))
    // ex_a already attached -> only ex_b shown
    expect(screen.queryAllByText('try Gemma4').length).toBe(1)  // only the tab
    expect(screen.getByRole('button', { name: /try notes/i })).toBeInTheDocument()
  })

  it('right-click on a tab triggers detach', () => {
    const onDetach = vi.fn()
    render(
      <ExperimentTabStrip
        activeTabKey="ex_a"
        attachedExperimentIds={['ex_a']}
        availableExperiments={EXPERIMENTS}
        onSwitch={() => {}}
        onAttach={() => {}}
        onDetach={onDetach}
        modelLabels={{}}
      />
    )
    fireEvent.contextMenu(screen.getByText('try Gemma4'))
    expect(onDetach).toHaveBeenCalledWith('ex_a')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ExperimentTabStrip`
Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/ReviewMode/ExperimentTabStrip.tsx`:

```tsx
import { useState } from 'react'

import type { ExperimentSummary } from '../../types/review'

type Props = {
  activeTabKey: 'active' | string
  attachedExperimentIds: string[]
  availableExperiments: ExperimentSummary[]
  onSwitch: (key: 'active' | string) => void
  onAttach: (experimentId: string) => void
  onDetach: (experimentId: string) => void
  modelLabels: Record<string, string>  // model_id → display label
}

export default function ExperimentTabStrip({
  activeTabKey,
  attachedExperimentIds,
  availableExperiments,
  onSwitch,
  onAttach,
  onDetach,
  modelLabels,
}: Props) {
  const [popoverOpen, setPopoverOpen] = useState(false)
  const attachedSet = new Set(attachedExperimentIds)
  const attachedExperiments = attachedExperimentIds
    .map(id => availableExperiments.find(e => e.experiment_id === id))
    .filter((e): e is ExperimentSummary => Boolean(e))

  const candidates = availableExperiments.filter(
    e => !attachedSet.has(e.experiment_id) && e.status !== 'archived',
  )

  return (
    <div className="rev-tabstrip" role="tablist">
      <button
        role="tab"
        aria-selected={activeTabKey === 'active'}
        className={'rev-tab' + (activeTabKey === 'active' ? ' on' : '')}
        onClick={() => onSwitch('active')}
        type="button"
      >
        <span className="star">⭐</span> Active
      </button>

      {attachedExperiments.map(e => (
        <button
          key={e.experiment_id}
          role="tab"
          aria-selected={activeTabKey === e.experiment_id}
          className={'rev-tab' + (activeTabKey === e.experiment_id ? ' on' : '')}
          onClick={() => onSwitch(e.experiment_id)}
          onContextMenu={ev => { ev.preventDefault(); onDetach(e.experiment_id) }}
          title={`${modelLabels[e.model_id] ?? e.model_id} · ${e.prompt_id}`}
          type="button"
        >
          {e.label}
        </button>
      ))}

      <div className="rev-tab-add">
        <button
          aria-label="+"
          className="rev-tab-plus"
          onClick={() => setPopoverOpen(o => !o)}
          type="button"
        >+</button>
        {popoverOpen && (
          <div className="rev-tab-popover" role="menu">
            {candidates.length === 0 && (
              <div className="rev-tab-empty">no more experiments to attach</div>
            )}
            {candidates.map(e => (
              <button
                key={e.experiment_id}
                role="menuitem"
                className="rev-tab-popover-item"
                onClick={() => {
                  onAttach(e.experiment_id)
                  setPopoverOpen(false)
                }}
                type="button"
              >
                {e.label} <span className="meta">{e.status}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add minimal CSS**

In the appropriate stylesheet (find where `.rev-bar` / `.rev-body` are defined — likely `frontend/src/styles/review.css` or similar), append:

```css
.rev-tabstrip {
  display: flex; gap: 4px; align-items: center;
  padding: 6px 16px;
  border-bottom: 1px solid var(--ink-line);
  background: var(--paper-1);
  font-family: var(--mono); font-size: 12px;
  overflow-x: auto;
}
.rev-tab {
  padding: 4px 10px; border-radius: 4px;
  border: 1px solid transparent; background: transparent;
  color: var(--ink-2); cursor: pointer; white-space: nowrap;
}
.rev-tab:hover { background: var(--paper-2); }
.rev-tab.on { background: var(--paper-3); color: var(--ink-1); border-color: var(--ink-line); }
.rev-tab .star { margin-right: 4px; }
.rev-tab-add { position: relative; margin-left: 4px; }
.rev-tab-plus { padding: 4px 8px; border: 1px dashed var(--ink-line); background: transparent; cursor: pointer; }
.rev-tab-popover {
  position: absolute; top: 100%; left: 0; margin-top: 4px;
  background: var(--paper-1); border: 1px solid var(--ink-line);
  padding: 4px; min-width: 200px; z-index: 5;
  display: flex; flex-direction: column; gap: 2px;
}
.rev-tab-popover-item {
  text-align: left; padding: 6px 8px;
  background: transparent; border: none; cursor: pointer;
}
.rev-tab-popover-item:hover { background: var(--paper-2); }
.rev-tab-popover-item .meta { float: right; color: var(--ink-3); }
.rev-tab-empty { padding: 6px 8px; color: var(--ink-3); font-style: italic; }
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd frontend && npm test -- ExperimentTabStrip`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ReviewMode/ExperimentTabStrip.tsx \
        frontend/tests/unit/ReviewMode/ExperimentTabStrip.test.tsx \
        frontend/src/styles/review.css  # (or whichever stylesheet you touched)
git commit -m "feat(m9.3): ExperimentTabStrip — segmented strip + [+] popover"
```

---

## Task 15: Wire the tab strip into `ReviewOverlay` + read-only `FieldEditor`

**Files:**
- Modify: `frontend/src/components/ReviewMode/ReviewOverlay.tsx`
- Modify: `frontend/src/components/ReviewMode/FieldEditor.tsx`
- Modify: `frontend/src/components/ReviewMode/ReviewBar.tsx`
- Modify: `frontend/tests/unit/ReviewMode/ReviewOverlay.test.tsx`

- [ ] **Step 1: Write the failing integration test**

Append to (or create) `frontend/tests/unit/ReviewMode/ReviewOverlay.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ReviewOverlay from '../../../src/components/ReviewMode/ReviewOverlay'
import { useReview } from '../../../src/stores/review'
import { useExperiments } from '../../../src/stores/experiments'

describe('ReviewOverlay tab integration', () => {
  it('shows the experiment tab strip when there are experiments in the project', () => {
    useExperiments.setState({
      byProject: {
        'p_x': {
          list: [
            { experiment_id: 'ex_a', label: 'gemma', prompt_id: 'pr', model_id: 'm',
              status: 'draft', created_at: '2026-05-13', score: null },
          ],
          loading: false, err: null, loadedAt: Date.now(),
        },
      },
    })
    useReview.setState({
      activeProjectId: 'p_x', activeDocId: 'd_y',
      entities: [{ supplier: 'ACME' }], evidence: null, notes: {},
      attachedExperimentIds: [], activeTabKey: 'active', extractsByExp: {},
      loading: false, saving: false, err: null, page: 1, pageCount: 1,
    })
    render(<ReviewOverlay onBack={() => {}} />)
    expect(screen.getByRole('tablist')).toBeInTheDocument()
    expect(screen.getByText(/Active/i)).toBeInTheDocument()
  })

  it('switching to an experiment tab renders read-only fields from extractsByExp', async () => {
    useExperiments.setState({
      byProject: { 'p_x': {
        list: [{ experiment_id: 'ex_a', label: 'g', prompt_id: 'pr', model_id: 'm',
                 status: 'ran', created_at: '2026-05-13', score: 0.9 }],
        loading: false, err: null, loadedAt: Date.now(),
      }},
    })
    useReview.setState({
      activeProjectId: 'p_x', activeDocId: 'd_y',
      entities: [{ supplier: 'ACME' }], evidence: null, notes: {},
      attachedExperimentIds: ['ex_a'],
      activeTabKey: 'ex_a',
      extractsByExp: { 'ex_a': { entities: [{ supplier: 'BETA' }] } },
      loading: false, saving: false, err: null, page: 1, pageCount: 1,
    })
    render(<ReviewOverlay onBack={() => {}} />)
    // BETA (from experiment) renders, not ACME (active)
    expect(screen.getByDisplayValue('BETA')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('ACME')).not.toBeInTheDocument()
    // inputs are read-only
    const input = screen.getByDisplayValue('BETA') as HTMLInputElement
    expect(input.readOnly || input.disabled).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ReviewOverlay`
Expected: FAIL — the tablist isn't yet rendered / read-only mode missing.

- [ ] **Step 3: Mount the tab strip in `ReviewOverlay`**

Edit `frontend/src/components/ReviewMode/ReviewOverlay.tsx`:

1. Subscribe to `useExperiments` for this project; call `useExperiments.load(activeProjectId)` on mount (effect, mirrors `useSchema` load).
2. Pull the new fields from `useReview`: `attachedExperimentIds`, `activeTabKey`, `extractsByExp`, `attachExperiment`, `detachExperiment`, `setActiveTab`.
3. Derive the entities to render in the FieldEditor based on `activeTabKey`:
   ```ts
   const displayEntities = activeTabKey === 'active'
     ? entities
     : (extractsByExp[activeTabKey]?.entities ?? [])
   const readOnly = activeTabKey !== 'active'
   ```
4. Pull `useModels` to build `modelLabels: Record<string, string>`.
5. Insert the `<ExperimentTabStrip ... />` between `<ReviewBar />` and the `<div className="rev-body">`. Only render the strip when `experiments.list.length > 0`.
6. Pass `entities={displayEntities}` and `readOnly={readOnly}` into `<FieldEditor>`.

Concretely, in the JSX (after `<ReviewBar … />`):

```tsx
{experimentSlice && experimentSlice.list.length > 0 && (
  <ExperimentTabStrip
    activeTabKey={activeTabKey}
    attachedExperimentIds={attachedExperimentIds}
    availableExperiments={experimentSlice.list}
    onSwitch={setActiveTab}
    onAttach={(eid) => void attachExperiment(eid)}
    onDetach={detachExperiment}
    modelLabels={modelLabels}
  />
)}
```

Then in the FieldEditor invocation (the form half of `rev-body`):

```tsx
<FieldEditor
  entities={displayEntities}
  schema={schema}
  evidence={evidence}
  notes={notes}
  setField={setField}
  setNote={setNote}
  addEntity={addEntity}
  removeEntity={removeEntity}
  forceOpen={forceOpen}
  readOnly={readOnly}
/>
```

- [ ] **Step 4: Add `readOnly` to `FieldEditor`**

Edit `frontend/src/components/ReviewMode/FieldEditor.tsx`:

1. Add `readOnly?: boolean` to the `Props` type.
2. Plumb it down to `<FieldRow>` (and `ObjectField` / `ArrayField` as needed — they all render inputs).
3. Each `<input>` / `<textarea>` element gets `readOnly={readOnly}` and `disabled={readOnly}` (text inputs already support `readOnly`; selects/checkboxes need `disabled`).
4. Hide the "+ entity" / "remove entity" buttons when `readOnly`.

Mirror similarly in `FieldRow.tsx`, `ObjectField.tsx`, `ArrayField.tsx`, `JsonView.tsx` (the JSON view can show the JSON either way, but the editor that's open should respect the flag).

- [ ] **Step 5: Hide save button in ReviewBar when not on active tab**

Edit `frontend/src/components/ReviewMode/ReviewBar.tsx`:
1. Accept new prop `canSave: boolean` (controlled by parent: `canSave = activeTabKey === 'active'`).
2. When `!canSave`, render the save button as disabled with a hint tooltip "save lives on the ⭐ Active tab".

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npm test -- ReviewMode`
Expected: all PASS, no regressions in pre-existing review-mode tests (any inputs that were not previously read-only continue to work as before).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ReviewMode/ReviewOverlay.tsx \
        frontend/src/components/ReviewMode/FieldEditor.tsx \
        frontend/src/components/ReviewMode/FieldRow.tsx \
        frontend/src/components/ReviewMode/ObjectField.tsx \
        frontend/src/components/ReviewMode/ArrayField.tsx \
        frontend/src/components/ReviewMode/JsonView.tsx \
        frontend/src/components/ReviewMode/ReviewBar.tsx \
        frontend/tests/unit/ReviewMode/ReviewOverlay.test.tsx
git commit -m "feat(m9.3): ReviewOverlay mounts ExperimentTabStrip + read-only experiment tabs"
```

---

## Task 16: FSSpine `experiments/` group

**Files:**
- Modify: `frontend/src/components/Spine/FSSpine.tsx`
- Modify: `frontend/tests/unit/Spine/FSSpine.test.tsx`

- [ ] **Step 1: Write the failing test**

Append to `frontend/tests/unit/Spine/FSSpine.test.tsx`:

```tsx
it('renders experiments/ group with experiment_id rows and status', () => {
  useExperiments.setState({
    byProject: { 'p_x': {
      list: [
        { experiment_id: 'ex_a', label: 'try gemma', prompt_id: 'pr', model_id: 'm',
          status: 'ran', created_at: '2026-05-13', score: 0.91 },
        { experiment_id: 'ex_b', label: 'try notes', prompt_id: 'pr', model_id: 'm',
          status: 'draft', created_at: '2026-05-13', score: null },
      ],
      loading: false, err: null, loadedAt: Date.now(),
    }},
  })
  render(<FSSpine projectId="p_x" />)
  // Click the experiments/ group to expand it
  fireEvent.click(screen.getByText(/experiments\//))
  expect(screen.getByText('try gemma')).toBeInTheDocument()
  expect(screen.getByText('try notes')).toBeInTheDocument()
  expect(screen.getByText(/0\.91/)).toBeInTheDocument()  // score badge
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- FSSpine`
Expected: FAIL — no `experiments/` group rendered yet.

- [ ] **Step 3: Add the group to FSSpine**

Edit `frontend/src/components/Spine/FSSpine.tsx`. Find the existing render for `prompts/` and `models/` groups (added in M9.2). Add an analogous `experiments/` group below `models/`. Each row shows: `{label}` plus a small `[status]` chip and, if `score != null`, a faded `· {score.toFixed(2)}`. Rows are inert click-wise for M9.3 (no detail sheet yet — that's an M9.x follow-up). Make sure `useExperiments.load(pid)` is called when the project loads (you may already have an effect that loads schemas/prompts/models; extend it).

- [ ] **Step 4: Run tests to verify pass**

Run: `cd frontend && npm test -- FSSpine`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Spine/FSSpine.tsx \
        frontend/tests/unit/Spine/FSSpine.test.tsx
git commit -m "feat(m9.3): FSSpine — experiments/ group with status + score"
```

---

## Task 17: E2E spec — seed experiment + attach + switch

**Files:**
- Create: `frontend/tests/e2e/experiment-tabs.spec.ts`
- Modify (if needed): `frontend/tests/e2e/_seeds/<seed dir>` — add a fixture project with an experiment + per-doc extract, OR set up via stubbed test-mode routes

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/e2e/experiment-tabs.spec.ts`:

```ts
import { test, expect } from '@playwright/test'

// This relies on the `EMERGE_TEST_MODE=1` stub routes that other e2e specs use.
// Look at `chat-history.spec.ts` (M8) and `schema-quicklook.spec.ts` (M9.0) for
// the seed-route pattern.

test('attach experiment to review tab and switch shows experiment extract', async ({ page }) => {
  // Seed: a project with 1 doc, 1 reviewed/prediction, 1 experiment with 1 extract
  await page.goto('/?test-seed=experiment-tabs')

  // Open review on the seeded doc
  await page.getByRole('button', { name: /reviewing|review/i }).click()
  // strip is visible
  await expect(page.getByRole('tablist')).toBeVisible()

  // [+] popover lists the seeded experiment
  await page.getByRole('button', { name: '+' }).click()
  await page.getByRole('menuitem', { name: /try-gemma/i }).click()

  // tab appears, click it
  const tab = page.getByRole('tab', { name: /try-gemma/i })
  await expect(tab).toBeVisible()
  await tab.click()

  // field shows experiment's value, NOT the active prediction's
  await expect(page.getByDisplayValue('FROM_EXPERIMENT')).toBeVisible()

  // save button is disabled
  await expect(page.getByRole('button', { name: /save/i })).toBeDisabled()

  // switching back to ⭐ Active restores writable inputs
  await page.getByRole('tab', { name: /Active/i }).click()
  await expect(page.getByRole('button', { name: /save/i })).toBeEnabled()
})
```

- [ ] **Step 2: Add the seed**

Find the existing `_test_stubs.py` (backend) — extend the seed registry it uses (the `chat-history.spec.ts` and `schema-quicklook.spec.ts` patterns from M8/M9.0 added their own seeds). Add an `experiment-tabs` seed that drops a project with:
- 1 doc (1 reviewed payload, 1 prediction)
- 1 prompt (active) — schema = `[{name: "supplier", type: "string", ...}]`
- 1 model (active)
- 1 experiment in status="ran" with `extracts/{doc_id}.json` containing `{entities: [{supplier: "FROM_EXPERIMENT"}]}`

- [ ] **Step 3: Run the e2e to verify it fails initially, then passes**

Run: `cd frontend && npm run e2e -- experiment-tabs`
Expected: PASS once the seed is in place and the prior tasks are committed. If it fails, capture screenshots via Playwright's built-in `--trace=on-first-retry` and investigate.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/e2e/experiment-tabs.spec.ts \
        backend/app/api/routes/_test_stubs.py  # (if you extended it)
git commit -m "test(m9.3): e2e — attach experiment tab + switch shows extract"
```

---

## Task 18: Live verify + ROADMAP closeout

**Files:**
- Manual live verify on a real project (us-invoice or fresh)
- Modify: `docs/superpowers/plans/ROADMAP.md` (update M9.x family entry + add M9.3 shipped row)
- Modify: `docs/design-decisions.md` (append entry — see Task)
- Add: `docs/screenshots/2026-05-13-m9-3-*.png` for at least: the FSSpine `experiments/` group; the Review tab strip with ⭐ Active + 2 tabs; a switched-to-experiment tab showing read-only inputs

- [ ] **Step 1: Start backend + frontend**

Run (in two terminals):
```bash
cd backend && uv run uvicorn app.main:app --reload
cd frontend && npm run dev
```

- [ ] **Step 2: End-to-end scenario walkthrough (scenario §4.3 from the spec)**

In the running app:
1. Open the `us-invoice` project (or any post-M9.2 project with reviewed docs).
2. In chat: ask the agent to `create_experiment` with the current active prompt + a new model (`m_gemma4` if not present, fall back to a quick `create_model` + experiment).
3. Confirm `experiments/` group appears in FSSpine with the new experiment row.
4. Click `Reviewing` and open any doc.
5. Click `[+]`, attach the new experiment.
6. Verify the new tab is read-only (try clicking an input — should be disabled).
7. Switch back to `⭐ Active`, edit a field, save — confirm save succeeds and `reviewed/` updates.
8. In chat: ask the agent to `run_experiment_eval` on the experiment. Confirm the resulting eval blob is reasonable (`score`, `per_doc`, `coverage`).
9. In chat: ask the agent to `promote_experiment`. Confirm:
   - `active_prompt_id` in `project.json` now matches the experiment's prompt.
   - `predictions/_draft/` now contains files matching the experiment's `extracts/`.
   - Re-open Review on a previously-extracted doc: data matches the experiment's prior extract.
10. Try `delete_prompt` / `delete_model` on the experiment's prompt/model via chat — confirm the agent reports `referenced by experiment ex_…`.
11. Archive that experiment; retry the delete — succeeds.

- [ ] **Step 3: Capture screenshots**

Save to `docs/screenshots/`:
- `2026-05-13-m9-3-fsspine-experiments.png` — FSSpine showing the experiments/ group with the new row
- `2026-05-13-m9-3-tab-strip-active.png` — Review with the tab strip, ⭐ Active selected
- `2026-05-13-m9-3-tab-strip-experiment.png` — Review with the experiment tab selected, fields read-only
- `2026-05-13-m9-3-promote-applied.png` — FSSpine `prompts/` shows new active after promote

- [ ] **Step 4: Update `docs/design-decisions.md`**

Append a new entry following the existing format. Cover:
- The "extend useReview vs new useExperimentReview store" decision (rationale per the plan's Decision 1)
- The "run_experiment_eval is inline foreground, not a job" decision (per Decision 2)
- The "promote re-seeds predictions/_draft/" UX decision (per Decision 3)
- The "delete_prompt/delete_model blocked by non-archived experiments" rule (per Decision 4)
- ✅ resolution for the M9.2 follow-up note about `delete_prompt` / `delete_model` not checking experiment references

- [ ] **Step 5: Update `docs/superpowers/plans/ROADMAP.md`**

In the Status table:
- Add a new row `**M9.3** — experiments axis + review-mode multi-tab (tools + routes + UI + delete-ref check)` with the plan file + ✅ shipped + commit range
- Update the M9.x family entry to note that the prompt/model/experiment trio is now complete; the remaining M9.x work is autoresearch path migration (M9.4), cross-project fork (M9.5), and readiness loosening (M9.6).

In the "What each milestone delivers" section, add a new subsection for M9.3 summarising the scope, the M9.2 follow-up closures, and the deferred items (autoresearch migration, fork_project, readiness loosening, field-diff view).

- [ ] **Step 6: Run the full backend + frontend test suite once more for regression safety**

```bash
cd backend && uv run pytest -v
cd frontend && npm test
cd frontend && npm run e2e
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add docs/design-decisions.md docs/superpowers/plans/ROADMAP.md \
        docs/screenshots/2026-05-13-m9-3-*.png
git commit -m "docs(m9.3): live-verified, screenshots, ROADMAP closeout"
```

---

## Self-review checklist

After all tasks land, before reporting done:

- **Spec coverage:**
  - §3.3 tools — 7 tools ✓ (Tasks 3–7, registered in Task 9)
  - §3.5 `promote_experiment` semantics — re-seeds predictions/_draft, marks promoted, atomic under lock ✓ (Task 6)
  - §7.4 review-mode tab strip — segmented strip, ⭐ Active read-write, others read-only, `[+]` popover excludes archived ✓ (Tasks 13–15)
  - §3.1 / §3.2 — `delete_prompt` / `delete_model` blocked by non-archived experiments ✓ (Task 7)
  - §2.2 pydantic models — `Experiment` + `ExperimentEval` ✓ (Task 1)
  - §4 scenario walkthroughs — scenario 3 (prompt-variant A/B) and scenario 4 (model A/B) verified via live test in Task 18

- **Hard rules cross-check:**
  - Publish fast-path 0 change ✓ — no files under `backend/app/api/routes/publish.py` or `versions/` touched
  - reviewed/ unchanged shape ✓ — only its consumers (extract loop in `run_experiment_eval`) read it
  - Experiment never auto-promote ✓ — `promote_experiment` is the only path that flips active and it requires user-mediated tool call
  - task-type-agnostic UI vocabulary ✓ — "experiment" is a generic verb (the chrome doesn't say "extract experiment")
  - Agent brain ↔ Extract LLM separation ✓ — `extract_with_experiment` uses provider adapter directly, never re-enters the SDK
  - secret hygiene ✓ — no `_keys.json` interaction; experiment meta carries no secrets

- **Placeholder scan:**
  - No `TBD` / `TODO` left in any task. Every code block is a real implementation, no `# ...`. Test code is real, not skeletal.

- **Type consistency:**
  - `experiment_id` always `ex_<12 chars>` (consistent across pydantic, tool, HTTP, frontend types)
  - `ExperimentSummary` (frontend) field names match what `list_experiments` returns from the backend
  - `ExperimentExtractPayload` mirrors `ExtractionOutput.model_dump(by_alias=True, exclude_none=True)` shape — `entities`, optional `_evidence`, optional `_notes`

- **Cross-store invalidation (INSIGHTS #9):**
  - `useExperiments.refresh` hooked into `useChat.handleToolResult` for the 5 mutating tools
  - `usePrompts` / `useModels` refresh on `promote_experiment` since active changes

- **Tests run green:**
  - `cd backend && uv run pytest -v` — all PASS
  - `cd frontend && npm test` — all PASS
  - `cd frontend && npm run e2e` — all PASS

---

## Execution

Per CLAUDE.md collaboration norm + memory `feedback_default_execution_mode.md`: this plan executes under **subagent-driven-development** without asking. Dispatch fresh subagents per task with two-stage review between tasks.
