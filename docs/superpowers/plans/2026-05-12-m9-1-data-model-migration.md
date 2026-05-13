# M9.1 — Data Model Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** introduce the new disk layout (`prompts/`, `models/` per project; `active_prompt_id` + `active_model_id` in `project.json`) and reroute all internal read/write paths to use it, while keeping the agent's `write_schema` MCP tool wire-compatible via a thin wrapper. Lazy-migrate legacy projects on first read. **Backend only — no UI changes** (those land in M9.2).

**Architecture:** add two new pydantic models (`PromptVariant`, `ModelConfig`) and two new tool modules (`tools/prompt.py`, `tools/model.py`) holding the read/write helpers. A new `workspace/migrate.py` provides an idempotent `migrate_project_if_needed()` that double-checks under `project_lock` before building `prompts/pr_baseline.json` + `models/m_default.json` from legacy `schema.json` + `global_notes.md` + `project.json.extract_model`. Existing read paths (`read_schema`, `extract_one`, `freeze_version`, HTTP routes, `_project_status`) all refactor to call the new helpers, which trigger migration transparently. `create_project` is the last task: once all reads work against the new layout, it stops writing `schema.json` for new projects. `schema.json` and `global_notes.md` are not deleted by migration — they linger on disk as stale breadcrumbs until a later cleanup milestone removes them safely.

**Tech Stack:** FastAPI + pydantic v2 + `claude_agent_sdk` MCP integration; tests via pytest with the per-test `workspace` fixture from `backend/tests/conftest.py` (already auto-sets `EMERGE_WORKSPACE_ROOT`).

**Reference docs:**
- Spec: `docs/superpowers/specs/2026-05-12-extraction-comparability-design.md` (committed `bd88af8`)
- INSIGHTS to respect (no behavior change in M9.1): #1 (`can_use_tool`), #2 (`setting_sources=[]`), #4 (Gemini `additionalProperties`), #8 (`safe_project_id`), #11 (`resume=...` + session sidecar)
- CLAUDE.md hard rules — particularly **publish fast-path 0 改动** and **schema.json 只通过 write_schema 修改** (演化版本：M9.1 之后 `schema.json` 物理上 retire；新写入只通过 `write_prompt` 落 `prompts/{id}.json`，`write_schema` MCP tool 保留为 thin wrapper 委托 `write_prompt`)

**Conventions:**
- Backend test command: `cd backend && uv run pytest <path> -v`
- Every task ends with a single `git commit` using `feat(m9.1):` or `test(m9.1):` or `refactor(m9.1):` prefix
- Async test functions need NO `@pytest.mark.asyncio` decorator — `pyproject.toml` sets `asyncio_mode = "auto"`
- The `workspace` fixture (`tmp_path / "workspace"`, auto-isolated) is in `conftest.py`; reuse it

**Scope boundary (out of scope for M9.1, save for later plans):**
- New MCP tool registrations (`write_prompt`, `create_prompt`, `list_prompts`, `switch_active_prompt`, model tools, experiment tools): **M9.2**
- `experiments/` directory + per-doc extract storage: **M9.3**
- Autoresearch path migration (`versions/_candidate/` → `prompts/_candidate/`): **M9.4**
- `fork_project` / `import_prompt`: **M9.5**
- `readiness_check` rules loosening: **M9.6**
- All frontend changes: M9.2+

---

## File structure

**New files:**
- `backend/app/schemas/prompt_variant.py` — `PromptVariant` pydantic model
- `backend/app/schemas/model_config.py` — `ModelConfig` pydantic model + `infer_provider_from_model_id()` helper
- `backend/app/tools/prompt.py` — `read_prompt` / `write_prompt` / `read_active_prompt` / `list_prompts` (Python functions; not MCP-registered yet)
- `backend/app/tools/model.py` — `read_model` / `write_model` / `read_active_model` / `list_models` / `create_model` (Python functions; not MCP-registered yet)
- `backend/app/workspace/migrate.py` — `migrate_project_if_needed()` idempotent migration
- `backend/tests/unit/test_schemas_prompt_variant.py`
- `backend/tests/unit/test_schemas_model_config.py`
- `backend/tests/unit/test_tool_prompt.py`
- `backend/tests/unit/test_tool_model.py`
- `backend/tests/unit/test_workspace_migrate.py`
- `backend/tests/integration/test_m9_1_lazy_migration.py`

**Modified files:**
- `backend/app/workspace/paths.py` — add `prompts_dir`, `prompt_path`, `models_dir`, `model_path` helpers
- `backend/app/workspace/ids.py` — add `new_prompt_id`, `new_model_id`
- `backend/app/tools/schema.py` — `read_schema` reads from active prompt; `write_schema` becomes thin wrapper to `write_prompt`
- `backend/app/tools/extract.py` — `extract_one` / `extract_one_with_schema` use active prompt + active model via helpers
- `backend/app/tools/publish.py` — `freeze_version` writes `derived_from` audit field; reads schema via `read_schema`, model via `read_active_model`; `readiness_check` reads schema via `read_schema`
- `backend/app/tools/projects.py` — `create_project` writes new layout (no `schema.json`); `_project_status` reads active prompt; `list_projects` triggers migration
- `backend/app/api/routes/projects.py` — `get_project` triggers migration; `get_project_schema` reads via `read_schema`
- `backend/app/api/routes/schema.py` — `get_project_schema_raw` reads via `read_schema` (PlainTextResponse formatting unchanged)
- `backend/tests/unit/test_paths.py` — add path helper assertions
- `backend/tests/unit/test_ids.py` — add id generator assertions
- `backend/tests/unit/test_tool_projects.py` — adjust expectations for new layout
- `backend/tests/unit/test_tool_schema.py` — adjust expectations (no longer writes `schema.json`)
- `backend/tests/unit/test_tool_extract.py` — adjust expectations
- `backend/tests/unit/test_tool_publish_freeze.py` — assert `derived_from` audit field present

---

## Task 1: Paths and ID helpers

**Files:**
- Modify: `backend/app/workspace/paths.py` (add helpers near `versions_dir` block)
- Modify: `backend/app/workspace/ids.py` (add 2 new generators)
- Modify: `backend/tests/unit/test_paths.py` (add assertions at the bottom)
- Modify: `backend/tests/unit/test_ids.py` (add assertions)

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_paths.py` (append at bottom):

```python
def test_prompts_dir(workspace: Path) -> None:
    from app.workspace.paths import prompts_dir
    assert prompts_dir(workspace, "p_abc") == workspace / "p_abc" / "prompts"


def test_prompt_path(workspace: Path) -> None:
    from app.workspace.paths import prompt_path
    assert prompt_path(workspace, "p_abc", "pr_baseline") == workspace / "p_abc" / "prompts" / "pr_baseline.json"


def test_models_dir(workspace: Path) -> None:
    from app.workspace.paths import models_dir
    assert models_dir(workspace, "p_abc") == workspace / "p_abc" / "models"


def test_model_path(workspace: Path) -> None:
    from app.workspace.paths import model_path
    assert model_path(workspace, "p_abc", "m_default") == workspace / "p_abc" / "models" / "m_default.json"
```

Add to `backend/tests/unit/test_ids.py` (append at bottom):

```python
import re

from app.workspace.ids import new_prompt_id, new_model_id


def test_new_prompt_id_format() -> None:
    pid = new_prompt_id()
    assert re.match(r"^pr_[0-9a-z]{12}$", pid)


def test_new_model_id_format() -> None:
    mid = new_model_id()
    assert re.match(r"^m_[0-9a-z]{12}$", mid)


def test_new_prompt_id_unique() -> None:
    ids = {new_prompt_id() for _ in range(50)}
    assert len(ids) == 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_paths.py tests/unit/test_ids.py -v -k "prompts_dir or prompt_path or models_dir or model_path or new_prompt_id or new_model_id"`
Expected: FAIL (ImportError — helpers don't exist yet)

- [ ] **Step 3: Add helpers to `backend/app/workspace/paths.py`**

Append after the `versions_dir` function (around line 38):

```python
def prompts_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "prompts"


def prompt_path(workspace: Path, project_id: str, prompt_id: str) -> Path:
    return prompts_dir(workspace, project_id) / f"{prompt_id}.json"


def models_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "models"


def model_path(workspace: Path, project_id: str, model_id: str) -> Path:
    return models_dir(workspace, project_id) / f"{model_id}.json"
```

- [ ] **Step 4: Add id generators to `backend/app/workspace/ids.py`**

Append at the bottom:

```python
def new_prompt_id() -> str:
    return _new("pr")


def new_model_id() -> str:
    return _new("m")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_paths.py tests/unit/test_ids.py -v -k "prompts_dir or prompt_path or models_dir or model_path or new_prompt_id or new_model_id"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/workspace/paths.py backend/app/workspace/ids.py backend/tests/unit/test_paths.py backend/tests/unit/test_ids.py
git commit -m "feat(m9.1): paths and id helpers for prompts/ and models/"
```

---

## Task 2: PromptVariant pydantic model

**Files:**
- Create: `backend/app/schemas/prompt_variant.py`
- Create: `backend/tests/unit/test_schemas_prompt_variant.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_schemas_prompt_variant.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.prompt_variant import PromptVariant
from app.schemas.schema_field import FieldType, SchemaField


def _field(name: str = "invoice_no") -> SchemaField:
    return SchemaField(name=name, type=FieldType.STRING, description="d")


def test_minimal_prompt_variant() -> None:
    pv = PromptVariant(
        prompt_id="pr_baseline",
        label="Baseline",
        schema=[_field()],
        created_at="2026-05-12T00:00:00+00:00",
        updated_at="2026-05-12T00:00:00+00:00",
    )
    assert pv.global_notes == ""
    assert pv.derived_from is None
    assert pv.schema[0].name == "invoice_no"


def test_round_trip_dump_load() -> None:
    pv = PromptVariant(
        prompt_id="pr_uk",
        label="UK adaptation",
        schema=[_field("supplier_county")],
        global_notes="UK uses county not state.",
        derived_from="pr_baseline",
        created_at="2026-05-12T00:00:00+00:00",
        updated_at="2026-05-12T00:00:00+00:00",
    )
    blob = pv.model_dump(mode="json")
    restored = PromptVariant(**blob)
    assert restored == pv


def test_cross_project_derived_from_string_ok() -> None:
    pv = PromptVariant(
        prompt_id="pr_b_from_us",
        label="from US",
        schema=[_field()],
        derived_from="p_us_invoice/pr_baseline",
        created_at="2026-05-12T00:00:00+00:00",
        updated_at="2026-05-12T00:00:00+00:00",
    )
    assert pv.derived_from == "p_us_invoice/pr_baseline"


def test_empty_schema_allowed() -> None:
    # New projects start with empty schema; not an error at model level
    pv = PromptVariant(
        prompt_id="pr_baseline",
        label="Empty",
        schema=[],
        created_at="2026-05-12T00:00:00+00:00",
        updated_at="2026-05-12T00:00:00+00:00",
    )
    assert pv.schema == []


def test_unknown_field_rejected() -> None:
    # extra="forbid" — typos in field names should error so we catch drift
    with pytest.raises(ValidationError):
        PromptVariant(
            prompt_id="pr_baseline",
            label="x",
            schema=[],
            created_at="2026-05-12T00:00:00+00:00",
            updated_at="2026-05-12T00:00:00+00:00",
            descriptions="oops typo",  # type: ignore[call-arg]
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_schemas_prompt_variant.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Create `backend/app/schemas/prompt_variant.py`**

```python
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.schema_field import SchemaField


class PromptVariant(BaseModel):
    """A versioned prompt unit: schema (fields name/type/description/required/enum/children)
    + global_notes. Stored on disk at prompts/{prompt_id}.json. Mutable on lab side
    (via write_prompt); copied into a versions/v{N}.json on freeze.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    prompt_id: str
    label: str
    schema: list[SchemaField]
    global_notes: str = ""
    # Lineage: None (root) | "pr_xxx" (same project) | "{src_pid}/{src_prompt_id}" (cross project)
    derived_from: Optional[str] = None
    created_at: str
    updated_at: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_schemas_prompt_variant.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/prompt_variant.py backend/tests/unit/test_schemas_prompt_variant.py
git commit -m "feat(m9.1): PromptVariant pydantic model"
```

---

## Task 3: ModelConfig pydantic model + provider inference

**Files:**
- Create: `backend/app/schemas/model_config.py`
- Create: `backend/tests/unit/test_schemas_model_config.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_schemas_model_config.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.model_config import ModelConfig, infer_provider_from_model_id


def test_minimal_model_config() -> None:
    mc = ModelConfig(
        model_id="m_default",
        label="Default",
        provider="google",
        provider_model_id="gemini-2.0-flash",
        created_at="2026-05-12T00:00:00+00:00",
    )
    assert mc.params == {}


def test_with_params() -> None:
    mc = ModelConfig(
        model_id="m_sonnet",
        label="Claude Sonnet",
        provider="anthropic",
        provider_model_id="claude-sonnet-4-6",
        params={"temperature": 0.0, "max_tokens": 4096},
        created_at="2026-05-12T00:00:00+00:00",
    )
    assert mc.params["temperature"] == 0.0


def test_provider_literal_constraint() -> None:
    with pytest.raises(ValidationError):
        ModelConfig(
            model_id="m_x",
            label="x",
            provider="azure",  # type: ignore[arg-type]
            provider_model_id="x",
            created_at="2026-05-12T00:00:00+00:00",
        )


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("claude-sonnet-4-6", "anthropic"),
        ("claude-opus-4-7", "anthropic"),
        ("gpt-4o-2024-08", "openai"),
        ("o1-preview", "openai"),
        ("o3-mini", "openai"),
        ("gemini-2.0-flash", "google"),
        ("gemini-2.5-pro", "google"),
        ("gemma-4-12b-it", "google"),
        ("totally-unknown-model", "google"),  # fallback
    ],
)
def test_infer_provider_from_model_id(model_id: str, expected: str) -> None:
    assert infer_provider_from_model_id(model_id) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_schemas_model_config.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Create `backend/app/schemas/model_config.py`**

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Provider = Literal["anthropic", "openai", "google"]


class ModelConfig(BaseModel):
    """A named extract-LLM config. Stored at models/{model_id}.json.
    Per project — different projects can have different m_default if they run
    Gemini vs Claude. Multiple variants per project enable model A/B (M9.3).
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    model_id: str
    label: str
    provider: Provider
    provider_model_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: str


def infer_provider_from_model_id(provider_model_id: str) -> Provider:
    """Best-effort inference of provider from a model id string.
    Used by lazy migration when the legacy project.json only has
    `extract_model` without explicit provider tagging.
    Unknown → "google" (matches the existing default_extract_model fallback).
    """
    mid = provider_model_id.lower()
    if mid.startswith("claude-"):
        return "anthropic"
    if mid.startswith("gpt-") or mid.startswith("o1-") or mid.startswith("o3-"):
        return "openai"
    if mid.startswith("gemini-") or mid.startswith("gemma-"):
        return "google"
    return "google"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_schemas_model_config.py -v`
Expected: PASS (12 tests — 3 base + 9 parametrized)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/model_config.py backend/tests/unit/test_schemas_model_config.py
git commit -m "feat(m9.1): ModelConfig + infer_provider_from_model_id"
```

---

## Task 4: Prompt read/write helpers

**Files:**
- Create: `backend/app/tools/prompt.py`
- Create: `backend/tests/unit/test_tool_prompt.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_tool_prompt.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.schemas.prompt_variant import PromptVariant
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.prompt import (
    PromptNotFoundError,
    list_prompts,
    read_active_prompt,
    read_prompt,
    write_prompt,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    project_json_path,
    prompt_path,
    prompts_dir,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_active_project(workspace: Path, pid: str, schema: list[dict] | None = None) -> None:
    """Build a minimal post-migration project on disk so tests can focus on prompt I/O."""
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "name": "test",
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": None,
    })
    atomic_write_json(prompt_path(workspace, pid, "pr_baseline"), {
        "prompt_id": "pr_baseline",
        "label": "Baseline",
        "schema": schema or [],
        "global_notes": "",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })


async def test_read_prompt_by_id(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "invoice_no", "type": "string", "description": "d", "required": False}
    ])
    pv = await read_prompt(workspace, pid, "pr_baseline")
    assert pv.prompt_id == "pr_baseline"
    assert len(pv.schema) == 1
    assert pv.schema[0].name == "invoice_no"


async def test_read_prompt_missing_raises(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await read_prompt(workspace, pid, "pr_does_not_exist")


async def test_read_active_prompt_resolves_via_project_json(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "total", "type": "number", "description": "d", "required": False}
    ])
    pv = await read_active_prompt(workspace, pid)
    assert pv.prompt_id == "pr_baseline"
    assert pv.schema[0].name == "total"


async def test_write_prompt_to_active_when_prompt_id_none(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    new_schema = [SchemaField(name="supplier", type=FieldType.STRING, description="supplier name")]
    returned_pid = await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=new_schema,
        global_notes="some notes",
    )
    assert returned_pid == "pr_baseline"
    # On disk:
    blob = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert blob["schema"][0]["name"] == "supplier"
    assert blob["global_notes"] == "some notes"
    # updated_at refreshed (different from initial)
    assert "updated_at" in blob


async def test_write_prompt_preserves_derived_from_and_created_at(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    # First, manually set a derived_from + created_at on the existing prompt
    pp = prompt_path(workspace, pid, "pr_baseline")
    blob = json.loads(pp.read_text())
    blob["derived_from"] = "pr_parent"
    blob["created_at"] = "2026-01-01T00:00:00+00:00"
    atomic_write_json(pp, blob)

    await write_prompt(
        workspace, pid,
        prompt_id="pr_baseline",
        schema=[SchemaField(name="x", type=FieldType.STRING, description="d")],
        global_notes="",
    )
    after = json.loads(pp.read_text())
    assert after["derived_from"] == "pr_parent"
    assert after["created_at"] == "2026-01-01T00:00:00+00:00"
    # but updated_at changed
    assert after["updated_at"] != "2026-01-01T00:00:00+00:00"


async def test_write_prompt_to_nonexistent_raises(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await write_prompt(
            workspace, pid,
            prompt_id="pr_nope",
            schema=[],
            global_notes="",
        )


async def test_list_prompts_marks_active(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    # add a second prompt manually
    atomic_write_json(prompt_path(workspace, pid, "pr_other"), {
        "prompt_id": "pr_other",
        "label": "Other",
        "schema": [],
        "global_notes": "",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    items = await list_prompts(workspace, pid)
    by_id = {p["prompt_id"]: p for p in items}
    assert by_id["pr_baseline"]["is_active"] is True
    assert by_id["pr_other"]["is_active"] is False
    assert len(items) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_prompt.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Create `backend/app/tools/prompt.py`**

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.prompt_variant import PromptVariant
from app.schemas.schema_field import SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    project_json_path,
    prompt_path,
    prompts_dir,
)


class PromptNotFoundError(Exception):
    """Raised when read_prompt or write_prompt targets a prompt_id that does not exist on disk."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _resolve_prompt_id(workspace: Path, project_id: str, prompt_id: str | None) -> str:
    if prompt_id is not None:
        return prompt_id
    project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    active = project.get("active_prompt_id")
    if not active:
        raise PromptNotFoundError(
            f"project {project_id} has no active_prompt_id; cannot resolve None"
        )
    return active


async def read_prompt(workspace: Path, project_id: str, prompt_id: str) -> PromptVariant:
    pp = prompt_path(workspace, project_id, prompt_id)
    if not pp.exists():
        raise PromptNotFoundError(f"{prompt_id} not found in project {project_id}")
    blob = json.loads(pp.read_text(encoding="utf-8"))
    return PromptVariant(**blob)


async def read_active_prompt(workspace: Path, project_id: str) -> PromptVariant:
    resolved = await _resolve_prompt_id(workspace, project_id, None)
    return await read_prompt(workspace, project_id, resolved)


async def write_prompt(
    workspace: Path,
    project_id: str,
    *,
    prompt_id: str | None,
    schema: list[SchemaField],
    global_notes: str = "",
) -> str:
    """Mutate an existing prompt variant. Returns the resolved prompt_id.

    - prompt_id=None resolves to project.active_prompt_id
    - prompt_id must reference an existing prompts/{id}.json — raises PromptNotFoundError otherwise
      (use create_prompt to make a new variant; that lands in M9.5)
    - preserves prompt_id, label, derived_from, created_at; refreshes updated_at
    """
    async with project_lock(workspace, project_id):
        resolved = await _resolve_prompt_id(workspace, project_id, prompt_id)
        pp = prompt_path(workspace, project_id, resolved)
        if not pp.exists():
            raise PromptNotFoundError(f"{resolved} not found in project {project_id}")
        existing = PromptVariant(**json.loads(pp.read_text(encoding="utf-8")))
        updated = PromptVariant(
            prompt_id=existing.prompt_id,
            label=existing.label,
            schema=schema,
            global_notes=global_notes,
            derived_from=existing.derived_from,
            created_at=existing.created_at,
            updated_at=_now_iso(),
        )
        atomic_write_json(pp, updated.model_dump(mode="json"))
    return resolved


async def list_prompts(workspace: Path, project_id: str) -> list[dict]:
    """Returns one row per prompt variant on disk, marking the active one."""
    pd = prompts_dir(workspace, project_id)
    if not pd.exists():
        return []
    project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    active = project.get("active_prompt_id")
    out: list[dict] = []
    for child in sorted(pd.iterdir()):
        if not child.is_file() or not child.name.endswith(".json"):
            continue
        try:
            pv = PromptVariant(**json.loads(child.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "prompt_id": pv.prompt_id,
            "label": pv.label,
            "derived_from": pv.derived_from,
            "is_active": pv.prompt_id == active,
            "created_at": pv.created_at,
            "updated_at": pv.updated_at,
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_prompt.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/prompt.py backend/tests/unit/test_tool_prompt.py
git commit -m "feat(m9.1): prompt read/write helpers (Python tier; MCP exposure deferred to M9.2)"
```

---

## Task 5: Model read/write helpers

**Files:**
- Create: `backend/app/tools/model.py`
- Create: `backend/tests/unit/test_tool_model.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_tool_model.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.tools.model import (
    ModelNotFoundError,
    create_model,
    list_models,
    read_active_model,
    read_model,
    write_model,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import model_path, models_dir, project_json_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_active_project(workspace: Path, pid: str) -> None:
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    models_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "name": "t",
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": None,
    })
    atomic_write_json(model_path(workspace, pid, "m_default"), {
        "model_id": "m_default",
        "label": "Default (gemini-2.0-flash)",
        "provider": "google",
        "provider_model_id": "gemini-2.0-flash",
        "params": {"temperature": 0.0},
        "created_at": _now(),
    })


async def test_read_model_by_id(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    mc = await read_model(workspace, pid, "m_default")
    assert mc.provider_model_id == "gemini-2.0-flash"
    assert mc.provider == "google"


async def test_read_model_missing_raises(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(ModelNotFoundError):
        await read_model(workspace, pid, "m_nope")


async def test_read_active_model(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    mc = await read_active_model(workspace, pid)
    assert mc.model_id == "m_default"


async def test_create_model_returns_id_with_prefix(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    mid = await create_model(
        workspace, pid,
        label="Gemma 4",
        provider="google",
        provider_model_id="gemma-4-12b-it",
        params={"temperature": 0.0},
    )
    assert mid.startswith("m_")
    mc = await read_model(workspace, pid, mid)
    assert mc.label == "Gemma 4"
    assert mc.provider_model_id == "gemma-4-12b-it"


async def test_write_model_upserts(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    # upsert with new label
    await write_model(
        workspace, pid,
        model_id="m_default",
        label="Default (renamed)",
        provider="google",
        provider_model_id="gemini-2.0-flash",
        params={"temperature": 0.1},
    )
    mc = await read_model(workspace, pid, "m_default")
    assert mc.label == "Default (renamed)"
    assert mc.params["temperature"] == 0.1


async def test_list_models_marks_active(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    await create_model(
        workspace, pid,
        label="Sonnet",
        provider="anthropic",
        provider_model_id="claude-sonnet-4-6",
    )
    rows = await list_models(workspace, pid)
    assert len(rows) == 2
    by_label = {r["label"]: r for r in rows}
    assert by_label["Default (gemini-2.0-flash)"]["is_active"] is True
    assert by_label["Sonnet"]["is_active"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_model.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Create `backend/app/tools/model.py`**

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.model_config import ModelConfig, Provider
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_model_id
from app.workspace.lock import project_lock
from app.workspace.paths import (
    model_path,
    models_dir,
    project_json_path,
)


class ModelNotFoundError(Exception):
    """Raised when read_model targets a model_id that does not exist on disk."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def read_model(workspace: Path, project_id: str, model_id: str) -> ModelConfig:
    mp = model_path(workspace, project_id, model_id)
    if not mp.exists():
        raise ModelNotFoundError(f"{model_id} not found in project {project_id}")
    return ModelConfig(**json.loads(mp.read_text(encoding="utf-8")))


async def read_active_model(workspace: Path, project_id: str) -> ModelConfig:
    project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    active = project.get("active_model_id")
    if not active:
        raise ModelNotFoundError(
            f"project {project_id} has no active_model_id; cannot resolve active model"
        )
    return await read_model(workspace, project_id, active)


async def write_model(
    workspace: Path,
    project_id: str,
    *,
    model_id: str,
    label: str,
    provider: Provider,
    provider_model_id: str,
    params: dict[str, Any] | None = None,
) -> None:
    """Upsert a model config. created_at is preserved on update, set fresh on create."""
    async with project_lock(workspace, project_id):
        mp = model_path(workspace, project_id, model_id)
        models_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        if mp.exists():
            existing = ModelConfig(**json.loads(mp.read_text(encoding="utf-8")))
            created = existing.created_at
        else:
            created = _now_iso()
        mc = ModelConfig(
            model_id=model_id,
            label=label,
            provider=provider,
            provider_model_id=provider_model_id,
            params=params or {},
            created_at=created,
        )
        atomic_write_json(mp, mc.model_dump(mode="json"))


async def create_model(
    workspace: Path,
    project_id: str,
    *,
    label: str,
    provider: Provider,
    provider_model_id: str,
    params: dict[str, Any] | None = None,
) -> str:
    """Mint a new model_id and write the config. Returns the new model_id."""
    mid = new_model_id()
    await write_model(
        workspace, project_id,
        model_id=mid,
        label=label,
        provider=provider,
        provider_model_id=provider_model_id,
        params=params,
    )
    return mid


async def list_models(workspace: Path, project_id: str) -> list[dict]:
    md = models_dir(workspace, project_id)
    if not md.exists():
        return []
    project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    active = project.get("active_model_id")
    out: list[dict] = []
    for child in sorted(md.iterdir()):
        if not child.is_file() or not child.name.endswith(".json"):
            continue
        try:
            mc = ModelConfig(**json.loads(child.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "model_id": mc.model_id,
            "label": mc.label,
            "provider": mc.provider,
            "provider_model_id": mc.provider_model_id,
            "is_active": mc.model_id == active,
            "created_at": mc.created_at,
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_model.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/model.py backend/tests/unit/test_tool_model.py
git commit -m "feat(m9.1): model read/write helpers (Python tier; MCP exposure deferred to M9.2)"
```

---

## Task 6: Lazy migration function

**Files:**
- Create: `backend/app/workspace/migrate.py`
- Create: `backend/tests/unit/test_workspace_migrate.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_workspace_migrate.py`:

```python
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import (
    model_path,
    models_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
    schema_path,
)


def _build_legacy_project(workspace: Path, pid: str = "p_legacy00abcd") -> str:
    """Hand-build a pre-M9.1 layout on disk."""
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=False)
    (pdir / "docs").mkdir()
    (pdir / "predictions" / "_draft").mkdir(parents=True)
    (pdir / "versions").mkdir()
    (pdir / "chats").mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "name": "Legacy invoice",
        "project_type": "extraction",
        "created_at": "2026-05-01T00:00:00+00:00",
        "extract_model": "gemini-2.0-flash",
        "extract_params": {"temperature": 0.0},
        "active_version_id": None,
    }), encoding="utf-8")
    (pdir / "schema.json").write_text(json.dumps([
        {"name": "invoice_no", "type": "string", "description": "Invoice number", "required": False},
        {"name": "total", "type": "number", "description": "Total amount", "required": True},
    ]), encoding="utf-8")
    (pdir / "global_notes.md").write_text("This is a US invoice.\nUSD only.", encoding="utf-8")
    return pid


async def test_migrate_builds_prompts_and_models(workspace: Path) -> None:
    pid = _build_legacy_project(workspace)
    await migrate_project_if_needed(workspace, pid)

    pp = prompt_path(workspace, pid, "pr_baseline")
    assert pp.exists()
    pv = json.loads(pp.read_text())
    assert pv["prompt_id"] == "pr_baseline"
    assert pv["label"] == "Baseline"
    assert len(pv["schema"]) == 2
    assert pv["schema"][0]["name"] == "invoice_no"
    assert pv["global_notes"] == "This is a US invoice.\nUSD only."
    assert pv["derived_from"] is None
    assert "created_at" in pv and "updated_at" in pv


async def test_migrate_builds_default_model(workspace: Path) -> None:
    pid = _build_legacy_project(workspace)
    await migrate_project_if_needed(workspace, pid)

    mp = model_path(workspace, pid, "m_default")
    assert mp.exists()
    mc = json.loads(mp.read_text())
    assert mc["model_id"] == "m_default"
    assert mc["provider"] == "google"
    assert mc["provider_model_id"] == "gemini-2.0-flash"
    assert mc["params"] == {"temperature": 0.0}


async def test_migrate_updates_project_json_active_pointers(workspace: Path) -> None:
    pid = _build_legacy_project(workspace)
    await migrate_project_if_needed(workspace, pid)

    blob = json.loads(project_json_path(workspace, pid).read_text())
    assert blob["active_prompt_id"] == "pr_baseline"
    assert blob["active_model_id"] == "m_default"
    # legacy fields preserved for transition-period fallback
    assert blob["extract_model"] == "gemini-2.0-flash"
    assert blob["extract_params"] == {"temperature": 0.0}


async def test_migrate_does_not_delete_legacy_files(workspace: Path) -> None:
    pid = _build_legacy_project(workspace)
    await migrate_project_if_needed(workspace, pid)

    # schema.json and global_notes.md linger on disk (cleanup deferred to later milestone)
    assert schema_path(workspace, pid).exists()
    assert (workspace / pid / "global_notes.md").exists()


async def test_migrate_idempotent_when_prompts_dir_exists(workspace: Path) -> None:
    pid = _build_legacy_project(workspace)
    await migrate_project_if_needed(workspace, pid)
    # Mutate the migrated prompt
    pp = prompt_path(workspace, pid, "pr_baseline")
    pv = json.loads(pp.read_text())
    pv["schema"][0]["description"] = "manually edited"
    pp.write_text(json.dumps(pv), encoding="utf-8")

    # Second migration must be a no-op
    await migrate_project_if_needed(workspace, pid)
    pv2 = json.loads(pp.read_text())
    assert pv2["schema"][0]["description"] == "manually edited"


async def test_migrate_handles_missing_global_notes(workspace: Path) -> None:
    """Legacy projects without global_notes.md still migrate, with empty notes."""
    pid = _build_legacy_project(workspace)
    (workspace / pid / "global_notes.md").unlink()
    await migrate_project_if_needed(workspace, pid)

    pv = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert pv["global_notes"] == ""


async def test_migrate_concurrent_safe(workspace: Path) -> None:
    """Two concurrent migrate calls on the same project must serialize via project_lock
    and produce exactly one set of new layout files (no torn writes, no double-mint)."""
    pid = _build_legacy_project(workspace)
    await asyncio.gather(
        migrate_project_if_needed(workspace, pid),
        migrate_project_if_needed(workspace, pid),
        migrate_project_if_needed(workspace, pid),
    )
    # One pr_baseline + one m_default
    pd = prompts_dir(workspace, pid)
    md = models_dir(workspace, pid)
    assert sorted(p.name for p in pd.iterdir() if p.is_file()) == ["pr_baseline.json"]
    assert sorted(p.name for p in md.iterdir() if p.is_file()) == ["m_default.json"]


async def test_migrate_noop_on_missing_project(workspace: Path) -> None:
    """If pid directory doesn't exist, migrate is a silent no-op (no crash)."""
    await migrate_project_if_needed(workspace, "p_does_not_exist00")
    # nothing to assert besides no exception


async def test_migrate_handles_no_extract_model(workspace: Path) -> None:
    """A degenerate legacy project.json without extract_model still produces a usable m_default."""
    pid = _build_legacy_project(workspace)
    pj = project_json_path(workspace, pid)
    blob = json.loads(pj.read_text())
    del blob["extract_model"]
    pj.write_text(json.dumps(blob), encoding="utf-8")

    await migrate_project_if_needed(workspace, pid)
    mc = json.loads(model_path(workspace, pid, "m_default").read_text())
    # Falls back to settings default
    assert mc["provider_model_id"]  # non-empty
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_workspace_migrate.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Create `backend/app/workspace/migrate.py`**

```python
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.schemas.model_config import ModelConfig, infer_provider_from_model_id
from app.schemas.prompt_variant import PromptVariant
from app.schemas.schema_field import SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    model_path,
    models_dir,
    project_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
    schema_path,
)


_log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _global_notes_path(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "global_notes.md"


async def migrate_project_if_needed(workspace: Path, project_id: str) -> None:
    """Idempotent lazy migration from pre-M9.1 layout to the prompts/+models/ layout.

    Trigger this at every read entry point that touches schema or model config.
    Safe under concurrent invocations: uses project_lock + double-check.

    What it does (only when prompts/ does not exist):
      1. Reads legacy schema.json → builds prompts/pr_baseline.json
      2. Reads legacy global_notes.md (if present) → folds into pr_baseline.global_notes
      3. Reads legacy project.extract_model + extract_params → builds models/m_default.json
      4. Stamps project.json with active_prompt_id='pr_baseline', active_model_id='m_default'
      5. Leaves schema.json + global_notes.md on disk (cleanup deferred to later milestone)
    """
    pdir = project_dir(workspace, project_id)
    if not pdir.exists():
        return  # nothing to migrate
    if prompts_dir(workspace, project_id).exists():
        return  # fast path: already migrated

    async with project_lock(workspace, project_id):
        # Re-check under lock
        if prompts_dir(workspace, project_id).exists():
            return

        # Read legacy state
        pj_path = project_json_path(workspace, project_id)
        if not pj_path.exists():
            _log.warning("migrate: project.json missing for %s; skipping", project_id)
            return
        project = json.loads(pj_path.read_text(encoding="utf-8"))

        sp = schema_path(workspace, project_id)
        if sp.exists():
            raw_schema = json.loads(sp.read_text(encoding="utf-8"))
        else:
            raw_schema = []

        gn_path = _global_notes_path(workspace, project_id)
        global_notes = gn_path.read_text(encoding="utf-8") if gn_path.exists() else ""

        # Build pr_baseline
        prompts_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        models_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        # Validate schema entries — drop unparseable ones silently rather than crashing
        # migration on a stale field shape (this is best-effort lazy migration).
        parsed_fields: list[SchemaField] = []
        for entry in raw_schema:
            try:
                parsed_fields.append(SchemaField(**entry))
            except Exception:
                _log.warning(
                    "migrate: dropping unparseable schema entry in %s: %r",
                    project_id, entry,
                )
                continue
        now = _now_iso()
        pv = PromptVariant(
            prompt_id="pr_baseline",
            label="Baseline",
            schema=parsed_fields,
            global_notes=global_notes,
            derived_from=None,
            created_at=project.get("created_at") or now,
            updated_at=now,
        )
        atomic_write_json(prompt_path(workspace, project_id, "pr_baseline"), pv.model_dump(mode="json"))

        # Build m_default
        settings = get_settings()
        legacy_model = project.get("extract_model") or settings.default_extract_model
        legacy_params = project.get("extract_params") or {"temperature": 0.0}
        mc = ModelConfig(
            model_id="m_default",
            label=f"Default ({legacy_model})",
            provider=infer_provider_from_model_id(legacy_model),
            provider_model_id=legacy_model,
            params=legacy_params,
            created_at=project.get("created_at") or now,
        )
        atomic_write_json(model_path(workspace, project_id, "m_default"), mc.model_dump(mode="json"))

        # Stamp project.json with active pointers (preserve legacy fields for transition)
        project["active_prompt_id"] = "pr_baseline"
        project["active_model_id"] = "m_default"
        atomic_write_json(pj_path, project)

        _log.info(
            "migrate: project %s -> prompts/pr_baseline.json + models/m_default.json (provider=%s)",
            project_id, mc.provider,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_workspace_migrate.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace/migrate.py backend/tests/unit/test_workspace_migrate.py
git commit -m "feat(m9.1): migrate_project_if_needed — idempotent lazy migration"
```

---

## Task 7: Refactor `read_schema` + `write_schema` to use active prompt

**Files:**
- Modify: `backend/app/tools/schema.py`
- Modify: `backend/tests/unit/test_tool_schema.py` (a couple of test names change; existing semantics preserved)

- [ ] **Step 1: Read current expectations to understand which existing tests must still pass**

Re-read `backend/tests/unit/test_tool_schema.py` — current tests assert: write/read round trip; structural-change gate blocks new fields without `allow_structural=True`; description edits succeed without gate. These semantics MUST be preserved by the wrapper (the gate is the only behavior the agent's chat flow depends on).

- [ ] **Step 2: Write additional failing test for the new internal behavior**

Append to `backend/tests/unit/test_tool_schema.py`:

```python
async def test_write_schema_writes_to_active_prompt_not_schema_json(workspace: Path) -> None:
    """After M9.1, write_schema is a thin wrapper over write_prompt; the canonical
    storage for active descriptions is prompts/{active}.json, not schema.json."""
    from app.workspace.paths import prompt_path
    pid = await create_project(workspace, name="x")
    await write_schema(
        workspace, pid,
        [_f("invoice_no")],
        reason="initial",
        allow_structural=True,
    )
    pp = prompt_path(workspace, pid, "pr_baseline")
    assert pp.exists()
    pv = json.loads(pp.read_text())
    assert len(pv["schema"]) == 1
    assert pv["schema"][0]["name"] == "invoice_no"


async def test_write_schema_preserves_global_notes(workspace: Path) -> None:
    """The wrapper must NOT clobber global_notes when only fields are being updated."""
    from app.tools.prompt import write_prompt
    from app.schemas.schema_field import FieldType, SchemaField
    from app.workspace.paths import prompt_path
    pid = await create_project(workspace, name="x")
    # Seed global_notes via write_prompt directly (since M9.1 has no MCP exposure for notes yet)
    await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=[SchemaField(name="a", type=FieldType.STRING, description="d")],
        global_notes="some legacy notes",
    )
    # Now agent does a schema-only change through write_schema
    await write_schema(
        workspace, pid,
        [_f("a", description="new")],
        reason="edit",
    )
    pv = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert pv["global_notes"] == "some legacy notes"
    assert pv["schema"][0]["description"] == "new"
```

- [ ] **Step 3: Run new tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_schema.py::test_write_schema_writes_to_active_prompt_not_schema_json tests/unit/test_tool_schema.py::test_write_schema_preserves_global_notes -v`
Expected: FAIL (functions not refactored yet)

- [ ] **Step 4: Refactor `backend/app/tools/schema.py`**

Replace the `read_schema` and `write_schema` functions (keep `StructuralChangeError`, `_is_structural_change`, `derive_schema` etc. unchanged). Find this block:

```python
async def read_schema(workspace: Path, project_id: str) -> list[SchemaField]:
    raw = json.loads(schema_path(workspace, project_id).read_text())
    return [SchemaField(**f) for f in raw]
```

Replace with:

```python
async def read_schema(workspace: Path, project_id: str) -> list[SchemaField]:
    """Return the SchemaField list from the project's active prompt.

    M9.1+: this is sourced from prompts/{active_prompt_id}.json, not schema.json.
    Triggers lazy migration if the project still has legacy layout.
    """
    from app.tools.prompt import read_active_prompt
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)
    pv = await read_active_prompt(workspace, project_id)
    return pv.schema
```

Then find:

```python
async def write_schema(
    workspace: Path,
    project_id: str,
    schema: list[SchemaField],
    *,
    reason: str,
    allow_structural: bool = False,
) -> None:
    async with project_lock(workspace, project_id):
        sp = schema_path(workspace, project_id)
        if sp.exists():
            old = [SchemaField(**f) for f in json.loads(sp.read_text())]
            if _is_structural_change(old, schema) and not allow_structural:
                raise StructuralChangeError(
                    "structural change requires allow_structural=True (gated by agent)"
                )
        payload = [f.model_dump(mode="json") for f in schema]
        atomic_write_json(sp, payload)
```

Replace with:

```python
async def write_schema(
    workspace: Path,
    project_id: str,
    schema: list[SchemaField],
    *,
    reason: str,
    allow_structural: bool = False,
) -> None:
    """Thin wrapper over write_prompt — kept for one milestone for chat-tool backward compat.

    After M9.1, schema lives in prompts/{active}.json. The structural-change gate
    is preserved at this layer so the existing accept_candidate route and chat
    flow keep their safety net. New code should call write_prompt directly.

    The `reason` parameter is currently ignored (kept for signature compat).
    """
    from app.tools.prompt import read_active_prompt, write_prompt
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)
    async with project_lock(workspace, project_id):
        old_pv = await read_active_prompt(workspace, project_id)
        if _is_structural_change(old_pv.schema, schema) and not allow_structural:
            raise StructuralChangeError(
                "structural change requires allow_structural=True (gated by agent)"
            )
        await write_prompt(
            workspace, project_id,
            prompt_id=None,
            schema=schema,
            global_notes=old_pv.global_notes,
        )
```

Then at the top of the file, the existing imports include `from app.workspace.paths import doc_meta_path, schema_path`. Update to remove `schema_path` since it's no longer used here:

```python
from app.workspace.paths import doc_meta_path
```

(Lock import `project_lock` stays.)

- [ ] **Step 5: Run the full `test_tool_schema.py` to verify all tests pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_schema.py -v`
Expected: PASS — all original tests still pass (round trip, structural gate, derive_schema) AND the 2 new tests pass.

If a pre-existing test broke because it asserts `schema.json` file contents directly, update it to assert against `prompt_path(..., "pr_baseline")` instead. The existing test `test_create_project_writes_empty_schema` in `test_tool_projects.py` will fail in Task 11 — leave it alone for now.

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/schema.py backend/tests/unit/test_tool_schema.py
git commit -m "refactor(m9.1): read_schema/write_schema delegate to prompts/{active}.json"
```

---

## Task 8: Refactor `extract.py` to use active prompt + active model

**Files:**
- Modify: `backend/app/tools/extract.py`
- Modify: `backend/tests/unit/test_tool_extract.py` (update one expectation if needed)

- [ ] **Step 1: Read current `extract.py` to locate the schema_path + extract_model read**

Open `backend/app/tools/extract.py`. The function `extract_one` currently does (around line 110–114):

```python
schema = [SchemaField(**f) for f in json.loads(schema_path(workspace, project_id).read_text())]
if not schema:
    raise ValueError("project has empty schema; nothing to extract")
project = json.loads(project_json_path(workspace, project_id).read_text())
mid = model_id or project["extract_model"]
```

- [ ] **Step 2: Add a failing test for the new behavior**

Open `backend/tests/unit/test_tool_extract.py` and append:

```python
async def test_extract_one_reads_schema_from_active_prompt(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    """After M9.1, extract_one sources its schema from prompts/{active}.json
    via read_schema (not directly from schema.json)."""
    from app.tools.extract import extract_one
    from app.tools.docs import upload_doc
    from app.tools.prompt import write_prompt
    from app.tools.projects import create_project
    from app.schemas.schema_field import FieldType, SchemaField
    from tests.conftest import make_provider_result

    pid = await create_project(workspace, name="x")
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    did = await upload_doc(workspace, pid, pdf_bytes, "a.pdf")
    await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
    )
    stub_provider.extract.return_value = make_provider_result({"invoice_no": "X-1"})

    out = await extract_one(workspace, pid, did, provider=stub_provider)
    assert out["invoice_no"] == "X-1"
    stub_provider.extract.assert_awaited_once()


async def test_extract_one_uses_active_model_id(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    """When model_id arg is None, extract_one reads project.active_model_id
    and resolves the provider_model_id from models/{active}.json."""
    from app.tools.extract import extract_one
    from app.tools.docs import upload_doc
    from app.tools.model import create_model
    from app.tools.projects import create_project, update_project
    from app.tools.prompt import write_prompt
    from app.schemas.schema_field import FieldType, SchemaField
    from tests.conftest import make_provider_result

    pid = await create_project(workspace, name="x")
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    did = await upload_doc(workspace, pid, pdf_bytes, "a.pdf")
    # Create a second model and switch active
    new_mid = await create_model(
        workspace, pid,
        label="Sonnet 4.6",
        provider="anthropic",
        provider_model_id="claude-sonnet-4-6",
    )
    await update_project(workspace, pid, {"active_model_id": new_mid})
    await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
    )
    stub_provider.extract.return_value = make_provider_result({"invoice_no": "X-1"})

    await extract_one(workspace, pid, did, provider=stub_provider)

    # The provider was invoked with the active model's provider_model_id, not the legacy field
    call = stub_provider.extract.await_args
    assert call.kwargs["model_id"] == "claude-sonnet-4-6"
```

- [ ] **Step 3: Run new tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_extract.py -v -k "active_prompt or active_model_id"`
Expected: FAIL (extract_one still reads from schema_path / extract_model directly)

- [ ] **Step 4: Refactor `extract_one` in `backend/app/tools/extract.py`**

In `backend/app/tools/extract.py`, find the `extract_one` body that does the direct file reads, and replace those lines with calls to the new helpers. The full replaced function:

```python
async def extract_one(
    workspace: Path,
    project_id: str,
    doc_id: str,
    *,
    provider: Provider,
    model_id: str | None = None,
) -> dict[str, Any]:
    from app.tools.model import read_active_model
    from app.tools.schema import read_schema
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)
    schema = await read_schema(workspace, project_id)
    if not schema:
        raise ValueError("project has empty schema; nothing to extract")
    if model_id is None:
        mc = await read_active_model(workspace, project_id)
        mid = mc.provider_model_id
    else:
        mid = model_id

    user_blocks: list[ContentBlock] = [
        TextBlock(text=_build_field_instructions(schema)),
        await _doc_to_block(workspace, project_id, doc_id),
    ]
    response_schema = _build_response_schema(schema)
    result = await provider.extract(
        model_id=mid,
        system_prompt=_EXTRACT_SYSTEM,
        user_content=user_blocks,
        response_schema=response_schema,
    )

    output = ExtractionOutput(**result.raw_json)
    payload = output.model_dump(by_alias=True, exclude_none=True)

    async with project_lock(workspace, project_id):
        predictions_draft_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            predictions_draft_dir(workspace, project_id) / f"{doc_id}.json",
            payload,
        )
    return payload
```

Also remove the now-unused imports (`schema_path` and `project_json_path` if no other function uses them — verify by grepping the file).

`extract_one_with_schema` already takes the schema as a parameter, so it doesn't need migration — leave it as-is (its caller, autoresearch, already does its own resolution).

- [ ] **Step 5: Run all extract tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_extract.py -v`
Expected: PASS — both new tests + all existing tests pass (existing tests should still work because the test fixture goes through `create_project` which after Task 11 will write the new layout; until then, `migrate_project_if_needed` running at the head of `extract_one` reconciles).

If an existing test seeded `schema.json` by hand and expects extract_one to read from it, update the seed to also seed `prompts/pr_baseline.json` via `write_prompt`, or just call `write_schema` (the wrapper handles it).

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/extract.py backend/tests/unit/test_tool_extract.py
git commit -m "refactor(m9.1): extract_one resolves schema + model from active prompt/model"
```

---

## Task 9: Refactor `publish.freeze_version` + readiness reads

**Files:**
- Modify: `backend/app/tools/publish.py`
- Modify: `backend/tests/unit/test_tool_publish_freeze.py`

- [ ] **Step 1: Read the current freeze_version implementation**

Re-read `backend/app/tools/publish.py:303–342` (the `freeze_version` body). It currently reads `schema.json` directly and reads `project_blob["extract_model"]` + `project_blob.get("extract_params")` for the model fields. The version blob structure is:

```python
{
    "version_id": version_id,
    "schema": schema_blob,
    "global_notes": global_notes,
    "model_id": project_blob["extract_model"],
    "params": project_blob.get("extract_params") or {},
    "frozen_at": _iso_now(),
}
```

- [ ] **Step 2: Add a failing test for `derived_from` audit field**

Open `backend/tests/unit/test_tool_publish_freeze.py` and append (look for the existing test that successfully freezes a version, then add):

```python
async def test_freeze_version_writes_derived_from_audit_field(
    workspace: Path,
) -> None:
    """The frozen version blob should record which active prompt/model
    it was derived from, for audit lineage. This is a non-breaking
    additive field — publish fast-path readers ignore unknown keys."""
    import json
    from app.tools.projects import create_project
    from app.tools.publish import freeze_version
    from app.tools.reviewed import save_reviewed
    from app.tools.docs import upload_doc
    from app.tools.predictions import write_prediction
    from app.tools.prompt import write_prompt
    from app.schemas.reviewed import ReviewedSource
    from app.schemas.schema_field import FieldType, SchemaField
    from app.workspace.paths import version_path

    pid = await create_project(workspace, name="x")
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    did = await upload_doc(workspace, pid, pdf_bytes, "a.pdf")
    await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="d", required=True)],
    )
    # Make readiness pass: 1 reviewed example matching the prediction
    await write_prediction(workspace, pid, did, {"invoice_no": "X-1"})
    await save_reviewed(
        workspace, pid, did,
        entities=[{"invoice_no": "X-1"}],
        source=ReviewedSource.MANUAL,
    )

    out = await freeze_version(workspace, pid, force=True)
    n = int(out["version_id"][1:])
    v_blob = json.loads(version_path(workspace, pid, n).read_text())
    assert v_blob["derived_from"]["prompt_id"] == "pr_baseline"
    assert v_blob["derived_from"]["model_id"] == "m_default"
    # experiment_id is null in M9.1 (experiments arrive in M9.3)
    assert v_blob["derived_from"]["experiment_id"] is None
    # Public-contract fields unchanged
    assert v_blob["version_id"] == out["version_id"]
    assert v_blob["model_id"]  # populated from active model's provider_model_id
    assert "schema" in v_blob
    assert "global_notes" in v_blob
```

Note: depending on the existing test file's imports for `write_prediction` — verify the helper name. If `tools.predictions` exposes a different writer, use that. (Look at `tools/predictions.py`.)

- [ ] **Step 3: Run the new test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_tool_publish_freeze.py::test_freeze_version_writes_derived_from_audit_field -v`
Expected: FAIL (`derived_from` key missing from v_blob)

- [ ] **Step 4: Refactor `freeze_version` in `backend/app/tools/publish.py`**

In `freeze_version`, replace the body that reads `schema_blob` + `global_notes` + `project_blob["extract_model"]` with calls through the new helpers, and add the `derived_from` field. The full updated function body:

```python
async def freeze_version(workspace: Path, project_id: str, *, force: bool = False) -> dict[str, str]:
    """Freeze current lab state into immutable versions/v{n}.json."""
    from app.tools.model import read_active_model
    from app.tools.prompt import read_active_prompt
    from app.workspace.migrate import migrate_project_if_needed

    if not force:
        readiness = await readiness_check(workspace, project_id)
        if not readiness["hard_pass"]:
            failed = [check for check in readiness["checks"] if check["status"] == "fail"]
            raise PublishNotReadyError(
                error_code="not_ready",
                error_message_en=f"readiness checks failed: {[check['key'] for check in failed]}",
                checks=readiness["checks"],
            )

    await migrate_project_if_needed(workspace, project_id)

    async with project_lock(workspace, project_id):
        pv = await read_active_prompt(workspace, project_id)
        mc = await read_active_model(workspace, project_id)
        schema_blob = [f.model_dump(mode="json") for f in pv.schema]

        project_blob = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))

        n = next_version_n(workspace, project_id)
        version_id = f"v{n}"
        target = version_path(workspace, project_id, n)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target, {
            "version_id": version_id,
            "schema": schema_blob,
            "global_notes": pv.global_notes,
            "model_id": mc.provider_model_id,
            "params": mc.params,
            "frozen_at": _iso_now(),
            "derived_from": {
                "prompt_id": pv.prompt_id,
                "model_id": mc.model_id,
                "experiment_id": None,  # M9.3 will populate when promoted from experiment
            },
        })
        target.chmod(0o444)

        project_blob["active_version_id"] = version_id
        atomic_write_json(project_json_path(workspace, project_id), project_blob)

    return {"version_id": version_id}
```

Also locate any place in `publish.py` (e.g. `readiness_check`) that reads `schema_path(...).read_text()` directly and route them through `read_schema()` so they also benefit from migration. Use a quick grep:

Run: `grep -n "schema_path" backend/app/tools/publish.py`

For each such read, replace `[SchemaField(**f) for f in json.loads(schema_path(workspace, pid).read_text())]` with `await read_schema(workspace, pid)` (importing `from app.tools.schema import read_schema` at the top of the function or module as appropriate).

- [ ] **Step 5: Run all publish unit tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_publish_freeze.py tests/unit/test_tool_publish_readiness.py tests/unit/test_tool_publish_contract_diff.py tests/unit/test_tool_publish_issue_key.py -v`
Expected: PASS (all existing tests + new derived_from test). Adjust any test seed that wrote `schema.json` directly to use `write_schema` instead.

- [ ] **Step 6: Run the publish integration test**

Run: `cd backend && uv run pytest tests/integration/test_lab_publish_e2e.py -v`
Expected: PASS — the e2e flow exercises freeze_version end-to-end and should not regress.

- [ ] **Step 7: Commit**

```bash
git add backend/app/tools/publish.py backend/tests/unit/test_tool_publish_freeze.py
git commit -m "refactor(m9.1): freeze_version sources from active prompt/model + emits derived_from audit"
```

---

## Task 10: HTTP routes + `_project_status`

**Files:**
- Modify: `backend/app/api/routes/projects.py`
- Modify: `backend/app/api/routes/schema.py`
- Modify: `backend/app/tools/projects.py` (`_project_status`, `list_projects`)
- Modify: `backend/tests/unit/test_schema_raw_endpoints.py` (existing test file — adjust seed)

- [ ] **Step 1: Identify HTTP read sites of schema.json**

Run: `grep -n "schema_path\|schema.json" backend/app/api/routes/`
Sites to update: `routes/projects.py:53` (`get_project_schema`), `routes/schema.py:53–60` (`get_project_schema_raw`).

- [ ] **Step 2: Write a failing integration-style test for the new behavior**

Append to `backend/tests/unit/test_schema_raw_endpoints.py`:

```python
def test_get_project_schema_reads_from_active_prompt(client: TestClient, tmp_path: Path) -> None:
    """After M9.1, GET /lab/projects/{pid}/schema reads from prompts/{active}.json."""
    import json
    from app.tools.projects import create_project as _create
    from app.tools.prompt import write_prompt as _write_prompt
    from app.schemas.schema_field import FieldType, SchemaField
    import asyncio

    pid = asyncio.run(_create(tmp_path, name="t"))
    asyncio.run(_write_prompt(
        tmp_path, pid,
        prompt_id=None,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
    ))
    r = client.get(f"/lab/projects/{pid}/schema")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "invoice_no"


def test_legacy_project_migrates_on_first_http_read(client: TestClient, tmp_path: Path) -> None:
    """A legacy project on disk migrates the first time its schema is read via HTTP."""
    import json
    pid = "p_legacyhttp01"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "docs").mkdir()
    (pdir / "predictions" / "_draft").mkdir(parents=True)
    (pdir / "versions").mkdir()
    (pdir / "chats").mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "name": "legacy",
        "project_type": "extraction",
        "created_at": "2026-05-01T00:00:00+00:00",
        "extract_model": "gemini-2.0-flash",
        "extract_params": {"temperature": 0.0},
        "active_version_id": None,
    }))
    (pdir / "schema.json").write_text(json.dumps([
        {"name": "invoice_no", "type": "string", "description": "d", "required": False}
    ]))

    r = client.get(f"/lab/projects/{pid}/schema")
    assert r.status_code == 200
    # After this call, the prompts/ + models/ layout exists
    assert (pdir / "prompts" / "pr_baseline.json").exists()
    assert (pdir / "models" / "m_default.json").exists()
```

Update the existing fixture (`client`) if needed — pin `EMERGE_WORKSPACE_ROOT` to `tmp_path`. The existing file's fixture already does similar work; reuse the conventions.

- [ ] **Step 3: Run new tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_schema_raw_endpoints.py -v -k "active_prompt or migrates"`
Expected: FAIL (routes not yet refactored)

- [ ] **Step 4: Refactor `backend/app/api/routes/projects.py`**

Replace `get_project_schema`:

```python
@router.get("/lab/projects/{project_id}/schema")
async def get_project_schema(project_id: str) -> list[dict]:
    safe_project_id(project_id)
    settings = get_settings()
    from app.tools.schema import read_schema
    from app.workspace.migrate import migrate_project_if_needed

    pj = project_json_path(settings.workspace_root, project_id)
    if not pj.exists():
        raise HTTPException(status_code=404, detail="schema_not_found")
    await migrate_project_if_needed(settings.workspace_root, project_id)
    fields = await read_schema(settings.workspace_root, project_id)
    return [f.model_dump(mode="json") for f in fields]
```

Also update `get_project` (the `/lab/projects/{pid}` route) to trigger migration so consumers reading the project blob see post-migration shape:

```python
@router.get("/lab/projects/{project_id}")
async def get_project(project_id: str) -> dict:
    safe_project_id(project_id)
    settings = get_settings()
    from app.workspace.migrate import migrate_project_if_needed

    pj = project_json_path(settings.workspace_root, project_id)
    if not pj.exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    await migrate_project_if_needed(settings.workspace_root, project_id)
    blob = json.loads(pj.read_text())
    return {"project_id": project_id, **blob}
```

Remove the now-unused `schema_path` import at the top if not referenced elsewhere in the file.

- [ ] **Step 5: Refactor `backend/app/api/routes/schema.py` `get_project_schema_raw`**

Replace it with:

```python
@router.get("/lab/projects/{project_id}/schema/raw", response_class=PlainTextResponse)
async def get_project_schema_raw(project_id: str) -> PlainTextResponse:
    safe_project_id(project_id)
    settings = get_settings()
    from app.tools.schema import read_schema
    from app.workspace.migrate import migrate_project_if_needed
    from app.workspace.paths import project_json_path

    pj = project_json_path(settings.workspace_root, project_id)
    if not pj.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "schema_not_found"},
        )
    await migrate_project_if_needed(settings.workspace_root, project_id)
    fields = await read_schema(settings.workspace_root, project_id)
    parsed = [f.model_dump(mode="json") for f in fields]
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    return PlainTextResponse(pretty, media_type="text/plain; charset=utf-8")
```

The `get_project_version_raw` route reads `versions/v{N}.json` files — those have unchanged format, so leave that route alone.

- [ ] **Step 6: Update `_project_status` and `list_projects` in `backend/app/tools/projects.py`**

Find `_project_status` and replace:

```python
def _project_status(pdir: Path, blob: dict[str, Any]) -> str:
    if blob.get("active_version_id"):
        return "live"
    # Post-M9.1: presence of non-empty schema lives in prompts/{active_prompt_id}.json
    active_pid = blob.get("active_prompt_id")
    if active_pid:
        pp = pdir / "prompts" / f"{active_pid}.json"
        if pp.exists():
            try:
                pv = json.loads(pp.read_text())
                if isinstance(pv.get("schema"), list) and len(pv["schema"]) > 0:
                    return "draft"
            except (json.JSONDecodeError, OSError):
                pass
    # Legacy fallback (pre-migration): still detect by schema.json
    sp = pdir / "schema.json"
    if sp.exists():
        try:
            fields = json.loads(sp.read_text())
            if isinstance(fields, list) and len(fields) > 0:
                return "draft"
        except (json.JSONDecodeError, OSError):
            pass
    return "empty"
```

And update `list_projects` to migrate each project as it iterates:

```python
async def list_projects(workspace: Path) -> list[dict[str, Any]]:
    from app.workspace.migrate import migrate_project_if_needed

    if not workspace.exists():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(workspace.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        pj = child / "project.json"
        if not pj.exists():
            continue
        await migrate_project_if_needed(workspace, child.name)
        blob = json.loads(pj.read_text())
        out.append({
            "project_id": child.name,
            "status": _project_status(child, blob),
            **blob,
        })
    return out
```

- [ ] **Step 7: Run new HTTP tests + existing route tests**

Run: `cd backend && uv run pytest tests/unit/test_schema_raw_endpoints.py tests/integration/test_lab_projects.py -v`
Expected: PASS.

If `test_lab_projects.py` has an assertion that depends on `extract_model` being in the project blob, it should still pass (legacy field is preserved by migration, and new projects still write it via Task 11 changes — see plan there).

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/routes/projects.py backend/app/api/routes/schema.py backend/app/tools/projects.py backend/tests/unit/test_schema_raw_endpoints.py
git commit -m "refactor(m9.1): HTTP routes + _project_status migrate-on-read; sources from active prompt"
```

---

## Task 11: `create_project` writes new layout (no schema.json) + integration test

**Files:**
- Modify: `backend/app/tools/projects.py` (`create_project`)
- Modify: `backend/tests/unit/test_tool_projects.py`
- Create: `backend/tests/integration/test_m9_1_lazy_migration.py`

- [ ] **Step 1: Adjust the existing test that asserts schema.json is empty after create**

In `backend/tests/unit/test_tool_projects.py`, the test `test_create_project_writes_empty_schema` currently asserts:

```python
async def test_create_project_writes_empty_schema(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    blob = json.loads((workspace / pid / "schema.json").read_text())
    assert blob == []
```

Replace it with:

```python
async def test_create_project_writes_active_prompt_and_model(workspace: Path) -> None:
    """Post-M9.1: create_project writes prompts/pr_baseline.json (empty schema)
    + models/m_default.json + sets project.json active pointers. schema.json
    is NOT written for fresh projects (it has retired)."""
    pid = await create_project(workspace, name="x")
    pdir = workspace / pid

    # New layout files exist
    pp = pdir / "prompts" / "pr_baseline.json"
    mp = pdir / "models" / "m_default.json"
    assert pp.exists()
    assert mp.exists()

    pv = json.loads(pp.read_text())
    assert pv["prompt_id"] == "pr_baseline"
    assert pv["schema"] == []
    assert pv["global_notes"] == ""

    mc = json.loads(mp.read_text())
    assert mc["model_id"] == "m_default"

    # project.json carries active pointers
    project = json.loads((pdir / "project.json").read_text())
    assert project["active_prompt_id"] == "pr_baseline"
    assert project["active_model_id"] == "m_default"

    # schema.json is NOT written for new projects (retired)
    assert not (pdir / "schema.json").exists()
```

Also adjust `test_create_project_writes_project_json` to assert the new fields:

```python
async def test_create_project_writes_project_json(workspace: Path) -> None:
    pid = await create_project(workspace, name="inv-MY")
    pdir = workspace / pid
    assert pdir.is_dir()
    blob = json.loads((pdir / "project.json").read_text())
    assert blob["name"] == "inv-MY"
    assert blob["project_type"] == "extraction"
    assert blob["active_version_id"] is None
    assert blob["active_prompt_id"] == "pr_baseline"
    assert blob["active_model_id"] == "m_default"
```

- [ ] **Step 2: Run tests to verify the rewrites fail (because create_project still writes the old layout)**

Run: `cd backend && uv run pytest tests/unit/test_tool_projects.py -v`
Expected: FAIL — the schema.json-related test fails (it's still being written) AND the new layout files are missing.

- [ ] **Step 3: Refactor `create_project` in `backend/app/tools/projects.py`**

Replace `create_project` with:

```python
async def create_project(
    workspace: Path,
    *,
    name: str,
    project_type: str = "extraction",
) -> str:
    from app.schemas.model_config import ModelConfig, infer_provider_from_model_id
    from app.schemas.prompt_variant import PromptVariant
    from app.workspace.paths import model_path, models_dir, prompt_path, prompts_dir

    pid = new_project_id()
    pdir = project_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=False)
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    versions_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    chats_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    models_dir(workspace, pid).mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    now = _now_iso()

    # pr_baseline (empty schema)
    pv = PromptVariant(
        prompt_id="pr_baseline",
        label="Baseline",
        schema=[],
        global_notes="",
        derived_from=None,
        created_at=now,
        updated_at=now,
    )
    atomic_write_json(prompt_path(workspace, pid, "pr_baseline"), pv.model_dump(mode="json"))

    # m_default
    mc = ModelConfig(
        model_id="m_default",
        label=f"Default ({settings.default_extract_model})",
        provider=infer_provider_from_model_id(settings.default_extract_model),
        provider_model_id=settings.default_extract_model,
        params={"temperature": 0.0},
        created_at=now,
    )
    atomic_write_json(model_path(workspace, pid, "m_default"), mc.model_dump(mode="json"))

    # project.json — new layout; legacy extract_model/extract_params still set
    # so any in-flight legacy reader (during M9.1 transition only) has a fallback.
    blob = {
        "name": name,
        "project_type": project_type,
        "created_at": now,
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": None,
        "autoresearch_proposer_model": None,
        "extract_model": settings.default_extract_model,
        "extract_params": {"temperature": 0.0},
    }
    atomic_write_json(project_json_path(workspace, pid), blob)

    # schema.json is intentionally NOT written for new projects.
    return pid
```

Remove the `schema_path` import from `backend/app/tools/projects.py` if no other function in the file uses it (the only reference will likely be in `_project_status`'s legacy fallback branch, but that uses `pdir / "schema.json"` literal — no import needed).

- [ ] **Step 4: Run the affected tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_projects.py tests/unit/test_tool_schema.py tests/unit/test_tool_extract.py tests/unit/test_tool_publish_freeze.py -v`
Expected: PASS.

- [ ] **Step 5: Write the M9.1 integration test**

Create `backend/tests/integration/test_m9_1_lazy_migration.py`:

```python
"""M9.1 — end-to-end: a legacy on-disk project transparently upgrades to the
new layout the first time its schema is touched, without any explicit migrate
step from the caller. Also covers the fresh-project happy path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _build_legacy_project(workspace: Path, pid: str) -> None:
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=False)
    (pdir / "docs").mkdir()
    (pdir / "predictions" / "_draft").mkdir(parents=True)
    (pdir / "versions").mkdir()
    (pdir / "chats").mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "name": "legacy invoice",
        "project_type": "extraction",
        "created_at": "2026-05-01T00:00:00+00:00",
        "extract_model": "gemini-2.0-flash",
        "extract_params": {"temperature": 0.0},
        "active_version_id": None,
    }), encoding="utf-8")
    (pdir / "schema.json").write_text(json.dumps([
        {"name": "invoice_no", "type": "string", "description": "Invoice number", "required": False},
        {"name": "total", "type": "number", "description": "Total amount", "required": True},
    ]), encoding="utf-8")
    (pdir / "global_notes.md").write_text("US invoice; USD only.", encoding="utf-8")


async def test_fresh_project_directly_writes_new_layout(workspace: Path) -> None:
    from app.tools.projects import create_project
    pid = await create_project(workspace, name="fresh")
    assert (workspace / pid / "prompts" / "pr_baseline.json").exists()
    assert (workspace / pid / "models" / "m_default.json").exists()
    assert not (workspace / pid / "schema.json").exists()


async def test_legacy_project_migrates_on_read_schema(workspace: Path) -> None:
    from app.tools.schema import read_schema
    pid = "p_legacy00read"
    _build_legacy_project(workspace, pid)
    fields = await read_schema(workspace, pid)
    assert len(fields) == 2
    # post-migration artifacts on disk
    assert (workspace / pid / "prompts" / "pr_baseline.json").exists()
    assert (workspace / pid / "models" / "m_default.json").exists()


async def test_legacy_project_migrates_on_list_projects(workspace: Path) -> None:
    from app.tools.projects import list_projects
    pid = "p_legacy00list"
    _build_legacy_project(workspace, pid)
    items = await list_projects(workspace)
    assert any(it["project_id"] == pid for it in items)
    # list_projects iterates with migration in the loop, so the prompts dir exists now
    assert (workspace / pid / "prompts" / "pr_baseline.json").exists()


async def test_legacy_project_write_schema_then_read_round_trips(workspace: Path) -> None:
    """Writing through the legacy write_schema entrypoint also migrates and
    leaves the canonical state in prompts/{active}.json."""
    import json
    from app.tools.schema import read_schema, write_schema
    from app.schemas.schema_field import FieldType, SchemaField

    pid = "p_legacy00wrt"
    _build_legacy_project(workspace, pid)

    await write_schema(
        workspace, pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="updated description")],
        reason="post-migration first edit",
        allow_structural=True,  # legacy had 2 fields, we're going to 1 — structural change
    )
    fields = await read_schema(workspace, pid)
    assert len(fields) == 1
    assert fields[0].description == "updated description"

    # global_notes was preserved through the wrapper (it folded the legacy global_notes.md
    # into pr_baseline.global_notes during migration, and write_schema preserved it)
    pv_blob = json.loads((workspace / pid / "prompts" / "pr_baseline.json").read_text())
    assert pv_blob["global_notes"] == "US invoice; USD only."
```

- [ ] **Step 6: Run the integration test**

Run: `cd backend && uv run pytest tests/integration/test_m9_1_lazy_migration.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Run the entire backend suite to verify no regression**

Run: `cd backend && uv run pytest -v`
Expected: PASS — all pre-existing tests still pass + new tests all pass. Note any unexpected failures and fix them before commit.

- [ ] **Step 8: Commit**

```bash
git add backend/app/tools/projects.py backend/tests/unit/test_tool_projects.py backend/tests/integration/test_m9_1_lazy_migration.py
git commit -m "feat(m9.1): create_project writes new layout; full backend regression green"
```

---

## Task 12: Update ROADMAP

**Files:**
- Modify: `docs/superpowers/plans/ROADMAP.md`

- [ ] **Step 1: Mark M9.1 status**

Open `docs/superpowers/plans/ROADMAP.md`. Find the M9.x row near line 26 (or wherever M9.x is currently rendered). Add a sub-row below it for M9.1 referencing this plan:

```
| **M9.1** — data model migration (prompt/model axes on disk, lazy migration, write_schema thin wrapper; backend-only) | `2026-05-12-m9-1-data-model-migration.md` | 🚧 in progress | — |
```

Place this in the same table format the file already uses for milestones. If M9.x row already exists with status "🧠 design-stage", keep that row above and add M9.1 below it.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/ROADMAP.md
git commit -m "docs(roadmap): add M9.1 in-progress row pointing at data-model-migration plan"
```

---

## Self-review (already performed; notes inline)

Spec coverage cross-check:

| Spec section | Plan task(s) | Notes |
|---|---|---|
| §2.1 Disk layout — `prompts/`, `models/` per project | T1 paths, T6 migration, T11 `create_project` | All new dirs created |
| §2.1 — `project.json` gains `active_prompt_id` + `active_model_id` | T6 migrate, T11 `create_project` | Legacy fields preserved during transition |
| §2.1 — `versions/v{N}.json` adds `derived_from` audit | T9 freeze refactor | `experiment_id` is null in M9.1 |
| §2.1 — `schema.json` retires (still on disk for legacy as breadcrumb) | T6 migrate (doesn't delete), T11 (new projects skip writing) | Cleanup script deferred to later milestone |
| §2.2 New pydantic models — `PromptVariant`, `ModelConfig` | T2, T3 | `Experiment` deferred to M9.3 |
| §2.2 `SchemaField` unchanged | (no task — explicit non-change) | Verified in T2 (PromptVariant.schema uses existing SchemaField) |
| §3.1 `write_prompt` (Python tier; MCP exposure later) | T4 | MCP registration is M9.2 |
| §3.2 `read_active_model` (Python tier) | T5 | MCP registration is M9.2 |
| §3.5 `promote_experiment` | (M9.3) | out of scope |
| §3.6 `extract_one`, `freeze_version` minor surface changes | T8 extract refactor, T9 publish refactor | Behavior preserved; new data source |
| §6.1 Publish fast-path 0 改动 | T9 verified by `test_lab_publish_e2e.py` re-run | `derived_from` is loose schema |
| §6.2 freeze_version data sources change | T9 | Legacy fields no longer read in freeze |
| §8.1 Lazy migration on first read | T6 migrate function + T7/T8/T9/T10 trigger sites | Idempotent + concurrent-safe |
| §8.4 write_schema thin wrapper | T7 | Structural-change gate preserved |
| §9 Hard rules — `schema.json` 只通过 write_schema 修改 (evolved) | T7 — write_schema delegates to write_prompt | All writes go through write_prompt |

Placeholder scan: no TBD / TODO / "implement later" / "add appropriate handling" found.

Type consistency:
- `PromptVariant.schema: list[SchemaField]` consistent across T2, T4, T6, T7, T9
- `ModelConfig.provider_model_id` referenced consistently in T3 (model_config), T5 (model.py), T8 (extract uses it for provider call), T9 (freeze writes it)
- `migrate_project_if_needed(workspace, project_id)` consistent signature across T6, T7, T8, T9, T10
- `read_schema(workspace, project_id) -> list[SchemaField]` consistent (T7) and consumed in T8, T9, T10
- All async functions are coroutine functions (no sync/async mismatch)

No spec gap unaccounted for in M9.1 scope. Scope holds at backend-only data layer + thin write_schema wrapper; MCP tool exposure for new tools is correctly deferred to M9.2 alongside the UI.
