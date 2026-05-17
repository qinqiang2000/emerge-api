# M9.2 — Prompt/Model Axis Tools + UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** expose the prompt/model axes built in M9.1 as first-class user surfaces — MCP tools the agent can call from chat (`write_prompt`, `create_prompt`, `list_prompts`, `switch_active_prompt`, `delete_prompt` + model equivalents), HTTP endpoints the frontend reads from, and FSSpine + ContextSurface + Quick-look UI that show `prompts/` and `models/` as expandable, active-marked groups (replacing the now-retired `schema.json` row).

**Architecture:** thin layer on top of M9.1. Three new Python helpers (`create_prompt`, `switch_active_prompt`, `delete_prompt`) live in `app/tools/prompt.py`; two (`switch_active_model`, `delete_model`) in `app/tools/model.py`. The MCP server in `app/tools/__init__.py` gains 10 new `@tool` registrations. Two new HTTP routes (`/lab/projects/{pid}/prompts*`, `/lab/projects/{pid}/models*`) expose the read paths to the frontend. Frontend gets two new Zustand stores (`usePrompts`, `useModels`) and four touched components (`FSSpine`, `ContextSurface`, `QuickLookHeader`, copy strings). One bug fix: the `t_contract_diff` MCP tool still reads `schema.json` directly (broken since M9.1) — route it through `read_schema`.

**Tech Stack:** FastAPI + pydantic v2 + `claude_agent_sdk` (backend) ; React 19 + TypeScript + Zustand + Vite + Vitest + RTL + Playwright (frontend). CSS tokens from `frontend/src/theme/tokens.css` (`--ink-*`, `--paper-*`, `--ochre`, `--moss`, `--rose`).

**Reference docs:**
- Spec: `docs/superpowers/specs/2026-05-12-extraction-comparability-design.md` (sections §3.1, §3.2, §7.1, §7.2, §7.3)
- Predecessor plan: `docs/superpowers/plans/2026-05-12-m9-1-data-model-migration.md` (M9.1, shipped — provides `PromptVariant`, `ModelConfig`, `read_prompt`, `write_prompt`, `list_prompts`, `read_model`, `write_model`, `list_models`, `create_model`, `migrate_project_if_needed`)
- M9.0 plan for UI conventions: `docs/superpowers/plans/2026-05-12-m9-0-schema-quicklook.md`
- INSIGHTS to respect: #1 (`can_use_tool`), #4 (Gemini `additionalProperties`), #8 (`safe_project_id`), #9 (frontend cross-store refresh)
- CLAUDE.md hard rules — **publish fast-path 0 改动**, **task-type-agnostic UI vocabulary** (chrome verbs only; specialized "Schema"→"Prompt" wording is content/help layer, not chrome)

**Conventions:**
- Backend test command: `cd backend && uv run pytest <path> -v`
- Frontend unit-test command: `cd frontend && npm test -- <pattern>` (uses `vitest run`)
- Frontend e2e command: `cd frontend && npm run e2e -- <pattern>`
- Async backend tests need NO `@pytest.mark.asyncio` — `pyproject.toml` sets `asyncio_mode="auto"`
- The `workspace` fixture lives in `backend/tests/conftest.py`
- Every task ends with a single `git commit` using `feat(m9.2):`, `refactor(m9.2):`, `test(m9.2):`, `fix(m9.2):`, or `docs(m9.2):` prefix.

**Scope boundary (explicit out of scope for M9.2, save for later plans):**
- Experiment axis (`create_experiment`, `extract_with_experiment`, `run_experiment_eval`, `promote_experiment`, `archive_experiment`, `list_experiments`, `delete_experiment`) → **M9.3**
- Review-mode multi-tab UI (`[ + ]` attach experiment, tab strip overflow) → **M9.3**
- Autoresearch path migration (`versions/_candidate/` → `prompts/_candidate/`) → **M9.4**
- `fork_project`, `import_prompt` (cross-project clone) → **M9.5**
- `readiness_check` rule loosening (move some hard fails to soft warns) → **M9.6**
- Field-diff power-user view (spec §7.4.1) → M9.x follow-up
- `delete_prompt` / `delete_model` experiment-reference check (no experiments exist yet in M9.2; included in this plan with a relaxed check that only blocks deletion of active prompt/model — M9.3 augments)
- Models card detail editor — M9.2 shows read-only summary; editing models is via chat tool only (matches M9.0 schema affordance)

---

## File structure

**New files (backend):**
- `backend/tests/unit/test_routes_prompts.py` — HTTP /prompts/* tests
- `backend/tests/unit/test_routes_models.py` — HTTP /models/* tests
- `backend/app/api/routes/prompts.py` — new router (mounted via `app/main.py`)
- `backend/app/api/routes/models.py` — new router

**Modified files (backend):**
- `backend/app/tools/prompt.py` — append `create_prompt`, `switch_active_prompt`, `delete_prompt`
- `backend/app/tools/model.py` — append `switch_active_model`, `delete_model`
- `backend/app/tools/__init__.py` — register 10 new MCP tools; fix `t_contract_diff`
- `backend/app/main.py` — mount 2 new routers
- `backend/app/skills/emerge_extractor.md` — point agent at new tool names
- `backend/tests/unit/test_tool_prompt.py` — extend with create/switch/delete tests
- `backend/tests/unit/test_tool_model.py` — extend with switch/delete tests
- `backend/tests/unit/test_tool_registration.py` — assert new tools registered

**New files (frontend):**
- `frontend/src/stores/prompts.ts` — `usePrompts` Zustand store
- `frontend/src/stores/models.ts` — `useModels` Zustand store
- `frontend/tests/unit/stores/prompts.test.ts`
- `frontend/tests/unit/stores/models.test.ts`

**Modified files (frontend):**
- `frontend/src/components/Spine/FSSpine.tsx` — replace `schema.json` row with `prompts/` + `models/` groups
- `frontend/src/components/Context/ContextSurface.tsx` — split single schema section into Prompt + Model cards
- `frontend/src/components/QuickLook/QuickLookHeader.tsx` — render real `derived_from`
- `frontend/src/components/QuickLook/SchemaQuickLook.tsx` — pass active prompt to header
- `frontend/src/components/Shell/HelpPopover.tsx` — copy: "schema.json" → "prompts/"
- `frontend/tests/unit/Spine/FSSpine.test.tsx` — adjust expectations
- `frontend/tests/unit/Context/ContextSurface.test.tsx` — adjust expectations
- `frontend/tests/unit/QuickLook/QuickLookHeader.test.tsx` — assert `derived from:` rendering

---

## Task 1: Prompt-axis Python helpers

**Files:**
- Modify: `backend/app/tools/prompt.py` (append `create_prompt`, `switch_active_prompt`, `delete_prompt`)
- Modify: `backend/tests/unit/test_tool_prompt.py` (append tests)

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_tool_prompt.py`:

```python
async def test_create_prompt_clones_active_when_derived_from_none(workspace: Path) -> None:
    """create_prompt(derived_from=None) clones the current active prompt and mints a new id."""
    from app.tools.prompt import create_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "invoice_no", "type": "string", "description": "d", "required": False}
    ])
    new_id = await create_prompt(workspace, pid, label="trial", derived_from=None)
    assert new_id.startswith("pr_")
    assert new_id != "pr_baseline"

    blob = json.loads(prompt_path(workspace, pid, new_id).read_text())
    assert blob["label"] == "trial"
    assert blob["schema"][0]["name"] == "invoice_no"  # cloned from baseline
    assert blob["derived_from"] == "pr_baseline"


async def test_create_prompt_with_explicit_derived_from(workspace: Path) -> None:
    from app.tools.prompt import create_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    # add a second prompt to derive from
    atomic_write_json(prompt_path(workspace, pid, "pr_other"), {
        "prompt_id": "pr_other",
        "label": "Other",
        "schema": [{"name": "x", "type": "string", "description": "d", "required": False}],
        "global_notes": "other notes",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    new_id = await create_prompt(workspace, pid, label="trial2", derived_from="pr_other")
    blob = json.loads(prompt_path(workspace, pid, new_id).read_text())
    assert blob["schema"][0]["name"] == "x"
    assert blob["global_notes"] == "other notes"
    assert blob["derived_from"] == "pr_other"


async def test_create_prompt_cross_project_derived_from_string(workspace: Path) -> None:
    """A {src_pid}/{src_prompt_id} string passes through as-is (M9.5 wires actual import)."""
    from app.tools.prompt import create_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    new_id = await create_prompt(
        workspace, pid,
        label="from us",
        derived_from="p_us_invoice/pr_baseline",  # cross-project literal
    )
    blob = json.loads(prompt_path(workspace, pid, new_id).read_text())
    # NOTE: schema is cloned from active (no cross-project resolution in M9.2);
    # derived_from string is recorded for lineage display only
    assert blob["derived_from"] == "p_us_invoice/pr_baseline"


async def test_switch_active_prompt(workspace: Path) -> None:
    from app.tools.prompt import switch_active_prompt, create_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    new_id = await create_prompt(workspace, pid, label="v2")
    await switch_active_prompt(workspace, pid, new_id)
    project = json.loads(project_json_path(workspace, pid).read_text())
    assert project["active_prompt_id"] == new_id


async def test_switch_active_prompt_to_nonexistent_raises(workspace: Path) -> None:
    from app.tools.prompt import PromptNotFoundError, switch_active_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await switch_active_prompt(workspace, pid, "pr_does_not_exist")


async def test_delete_prompt_removes_file(workspace: Path) -> None:
    from app.tools.prompt import create_prompt, delete_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    new_id = await create_prompt(workspace, pid, label="trial")
    assert prompt_path(workspace, pid, new_id).exists()
    await delete_prompt(workspace, pid, new_id)
    assert not prompt_path(workspace, pid, new_id).exists()


async def test_delete_prompt_blocks_active(workspace: Path) -> None:
    from app.tools.prompt import PromptInUseError, delete_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptInUseError):
        await delete_prompt(workspace, pid, "pr_baseline")


async def test_delete_prompt_missing_raises(workspace: Path) -> None:
    from app.tools.prompt import PromptNotFoundError, delete_prompt
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await delete_prompt(workspace, pid, "pr_nope")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_prompt.py -v -k "create_prompt or switch_active_prompt or delete_prompt"`
Expected: FAIL (ImportError — helpers not defined yet)

- [ ] **Step 3: Append helpers to `backend/app/tools/prompt.py`**

Append at the end of the file (after `list_prompts`):

```python
class PromptInUseError(Exception):
    """Raised when delete_prompt targets a prompt that is the active prompt
    (or, in later milestones, is referenced by a non-archived experiment).
    """


async def create_prompt(
    workspace: Path,
    project_id: str,
    *,
    label: str,
    derived_from: str | None = None,
) -> str:
    """Mint a new prompt_id, write prompts/{new_id}.json by cloning the contents
    of either the active prompt (derived_from=None) or a specified same-project
    prompt. Cross-project derived_from is recorded as-is on the new variant
    for lineage display; actual cross-project content cloning lands in M9.5
    (import_prompt). Returns the new prompt_id.
    """
    from app.workspace.ids import new_prompt_id
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)
    async with project_lock(workspace, project_id):
        if derived_from is None or "/" not in derived_from:
            # Same-project clone (or default = clone active)
            src_id = derived_from if derived_from is not None else (
                await _resolve_prompt_id(workspace, project_id, None)
            )
            src_path = prompt_path(workspace, project_id, src_id)
            if not src_path.exists():
                raise PromptNotFoundError(
                    f"derived_from prompt {src_id} not found in project {project_id}"
                )
            src = PromptVariant(**json.loads(src_path.read_text(encoding="utf-8")))
            cloned_schema = src.schema
            cloned_notes = src.global_notes
        else:
            # Cross-project literal — clone from active prompt in this project,
            # record the lineage string. M9.5 will resolve the real source.
            active = await read_active_prompt(workspace, project_id)
            cloned_schema = active.schema
            cloned_notes = active.global_notes

        new_id = new_prompt_id()
        now = _now_iso()
        pv = PromptVariant(
            prompt_id=new_id,
            label=label,
            schema=cloned_schema,
            global_notes=cloned_notes,
            derived_from=derived_from,
            created_at=now,
            updated_at=now,
        )
        prompts_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_json(prompt_path(workspace, project_id, new_id), pv.model_dump(mode="json"))
    return new_id


async def switch_active_prompt(workspace: Path, project_id: str, prompt_id: str) -> None:
    """Set project.json.active_prompt_id = prompt_id. Raises PromptNotFoundError
    if the target prompt file does not exist.
    """
    pp = prompt_path(workspace, project_id, prompt_id)
    if not pp.exists():
        raise PromptNotFoundError(
            f"cannot switch active: {prompt_id} not found in project {project_id}"
        )
    async with project_lock(workspace, project_id):
        pj = project_json_path(workspace, project_id)
        blob = json.loads(pj.read_text(encoding="utf-8"))
        blob["active_prompt_id"] = prompt_id
        atomic_write_json(pj, blob)


async def delete_prompt(workspace: Path, project_id: str, prompt_id: str) -> None:
    """Physically remove prompts/{prompt_id}.json. Blocks deletion of the active
    prompt (PromptInUseError). M9.3 will extend this with experiment-reference
    checks.
    """
    pp = prompt_path(workspace, project_id, prompt_id)
    if not pp.exists():
        raise PromptNotFoundError(f"{prompt_id} not found in project {project_id}")
    async with project_lock(workspace, project_id):
        project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
        if project.get("active_prompt_id") == prompt_id:
            raise PromptInUseError(
                f"cannot delete {prompt_id}: it is the active prompt; switch active first"
            )
        pp.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_prompt.py -v`
Expected: PASS (all original tests + 8 new tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/prompt.py backend/tests/unit/test_tool_prompt.py
git commit -m "feat(m9.2): prompt-axis Python helpers — create_prompt / switch_active_prompt / delete_prompt"
```

---

## Task 2: Model-axis Python helpers

**Files:**
- Modify: `backend/app/tools/model.py` (append `switch_active_model`, `delete_model`)
- Modify: `backend/tests/unit/test_tool_model.py` (append tests)

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_tool_model.py`:

```python
async def test_switch_active_model(workspace: Path) -> None:
    from app.tools.model import create_model, switch_active_model
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    new_mid = await create_model(
        workspace, pid,
        label="Sonnet 4.6",
        provider="anthropic",
        provider_model_id="claude-sonnet-4-6",
    )
    await switch_active_model(workspace, pid, new_mid)
    project = json.loads(project_json_path(workspace, pid).read_text())
    assert project["active_model_id"] == new_mid


async def test_switch_active_model_to_nonexistent_raises(workspace: Path) -> None:
    from app.tools.model import ModelNotFoundError, switch_active_model
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(ModelNotFoundError):
        await switch_active_model(workspace, pid, "m_nope")


async def test_delete_model_removes_file(workspace: Path) -> None:
    from app.tools.model import create_model, delete_model
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    new_mid = await create_model(
        workspace, pid,
        label="Gemma 4",
        provider="google",
        provider_model_id="gemma-4-12b-it",
    )
    assert model_path(workspace, pid, new_mid).exists()
    await delete_model(workspace, pid, new_mid)
    assert not model_path(workspace, pid, new_mid).exists()


async def test_delete_model_blocks_active(workspace: Path) -> None:
    from app.tools.model import ModelInUseError, delete_model
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(ModelInUseError):
        await delete_model(workspace, pid, "m_default")


async def test_delete_model_missing_raises(workspace: Path) -> None:
    from app.tools.model import ModelNotFoundError, delete_model
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(ModelNotFoundError):
        await delete_model(workspace, pid, "m_nope")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_model.py -v -k "switch_active_model or delete_model"`
Expected: FAIL (ImportError — helpers not defined yet)

- [ ] **Step 3: Append helpers to `backend/app/tools/model.py`**

Append at the end of the file:

```python
class ModelInUseError(Exception):
    """Raised when delete_model targets the active model (or, in later milestones,
    a model referenced by a non-archived experiment).
    """


async def switch_active_model(workspace: Path, project_id: str, model_id: str) -> None:
    """Set project.json.active_model_id = model_id. Raises ModelNotFoundError if
    the target model file does not exist.
    """
    mp = model_path(workspace, project_id, model_id)
    if not mp.exists():
        raise ModelNotFoundError(
            f"cannot switch active: {model_id} not found in project {project_id}"
        )
    async with project_lock(workspace, project_id):
        pj = project_json_path(workspace, project_id)
        blob = json.loads(pj.read_text(encoding="utf-8"))
        blob["active_model_id"] = model_id
        atomic_write_json(pj, blob)


async def delete_model(workspace: Path, project_id: str, model_id: str) -> None:
    """Physically remove models/{model_id}.json. Blocks deletion of the active
    model (ModelInUseError). M9.3 extends this with experiment-reference checks.
    """
    mp = model_path(workspace, project_id, model_id)
    if not mp.exists():
        raise ModelNotFoundError(f"{model_id} not found in project {project_id}")
    async with project_lock(workspace, project_id):
        project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
        if project.get("active_model_id") == model_id:
            raise ModelInUseError(
                f"cannot delete {model_id}: it is the active model; switch active first"
            )
        mp.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_model.py -v`
Expected: PASS (all original tests + 5 new tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/model.py backend/tests/unit/test_tool_model.py
git commit -m "feat(m9.2): model-axis Python helpers — switch_active_model / delete_model"
```

---

## Task 3: Fix `t_contract_diff` MCP tool (M9.1 bug)

The MCP tool `t_contract_diff` in `backend/app/tools/__init__.py` still reads `schema_path(workspace, pid).read_text()` directly. After M9.1, new projects no longer write `schema.json`, so calling this tool on a fresh project raises `FileNotFoundError`. No backend test currently exercises this path through the MCP entry point. We fix it before adding more tools.

**Files:**
- Modify: `backend/app/tools/__init__.py` (the `t_contract_diff` function only)
- Modify: `backend/tests/unit/test_tool_publish_contract_diff.py` (add a regression test that exercises `t_contract_diff` via the MCP entry point — or add a unit test that explicitly tests this code path)

- [ ] **Step 1: Write the failing regression test**

Append to `backend/tests/unit/test_tool_publish_contract_diff.py` (create the file if it doesn't exist; check first with `ls backend/tests/unit/test_tool_publish_contract_diff.py`):

```python
async def test_contract_diff_mcp_tool_works_on_fresh_project(
    workspace: Path,
    stub_provider,
) -> None:
    """Regression: the MCP-exposed `t_contract_diff` must read the active prompt
    via read_schema, not schema.json directly. After M9.1 new projects don't
    write schema.json, so the old code would FileNotFoundError."""
    from unittest.mock import MagicMock
    import json as _json
    from app.tools import build_emerge_mcp
    from app.tools.projects import create_project
    from app.tools.prompt import write_prompt
    from app.schemas.schema_field import FieldType, SchemaField
    import mcp.types as mcp_types

    pid = await create_project(workspace, name="x")
    await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
    )

    server = build_emerge_mcp(workspace=workspace, provider=stub_provider, job_runner=MagicMock())
    instance = server["instance"]
    call_handler = instance.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name="contract_diff", arguments={"project_id": pid}),
    )
    result = await call_handler(req)
    payload_text = result.root.content[0].text  # type: ignore[index]
    payload = _json.loads(payload_text)
    assert payload["added"] == ["invoice_no"]
    assert payload["is_breaking"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_tool_publish_contract_diff.py::test_contract_diff_mcp_tool_works_on_fresh_project -v`
Expected: FAIL with `FileNotFoundError` on `schema.json`.

- [ ] **Step 3: Fix `t_contract_diff` in `backend/app/tools/__init__.py`**

Locate the current `t_contract_diff` function body (around line 197–217). Replace the body. The full new function:

```python
    @tool(
        "contract_diff",
        "Diff current schema against the active version's frozen schema.",
        {"project_id": str},
    )
    async def t_contract_diff(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.schema import read_schema
        from app.workspace.paths import parse_version_id, project_json_path, version_path

        pid = args["project_id"]
        schema = await read_schema(workspace, pid)
        project = _json.loads(project_json_path(workspace, pid).read_text())
        active_version_id = project.get("active_version_id")
        if not active_version_id:
            out = {
                "added": [field.name for field in schema],
                "removed": [],
                "type_changed": [],
                "enum_narrowed": [],
                "is_breaking": False,
                "note": "no prior active version",
            }
        else:
            prev: list[SchemaField] = []
            n = parse_version_id(active_version_id)
            if n is not None and version_path(workspace, pid, n).exists():
                prev_blob = _json.loads(version_path(workspace, pid, n).read_text())
                prev = [SchemaField(**field) for field in prev_blob.get("schema", [])]
            out = publish_mod.contract_diff(prev, schema)
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}
```

Also remove the now-unused `schema_path` import from inside the function (it was a local import).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_publish_contract_diff.py -v`
Expected: PASS — all original tests + the new regression test.

Then run the full backend suite to make sure nothing else regressed: `cd backend && uv run pytest -v 2>&1 | tail -5`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/__init__.py backend/tests/unit/test_tool_publish_contract_diff.py
git commit -m "fix(m9.2): t_contract_diff reads via read_schema (was direct schema.json read; broke on M9.1 fresh projects)"
```

---

## Task 4: Expose prompt MCP tools

**Files:**
- Modify: `backend/app/tools/__init__.py` (add 5 new `@tool` registrations + add to `_EMERGE_TOOL_NAMES`)
- Modify: `backend/tests/unit/test_tool_registration.py` (assert new tools are listed)

- [ ] **Step 1: Write failing test**

Append to `backend/tests/unit/test_tool_registration.py`:

```python
async def test_prompt_axis_tools_are_registered(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert {
        "write_prompt",
        "create_prompt",
        "switch_active_prompt",
        "list_prompts",
        "delete_prompt",
    }.issubset(names), names


def test_prompt_axis_tools_in_emerge_tool_names() -> None:
    names = _emerge_tool_names()
    for n in ("write_prompt", "create_prompt", "switch_active_prompt", "list_prompts", "delete_prompt"):
        assert n in names, f"missing {n!r} in _EMERGE_TOOL_NAMES"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v -k "prompt_axis"`
Expected: FAIL (the new tool names aren't registered yet).

- [ ] **Step 3: Add 5 new `@tool` registrations to `backend/app/tools/__init__.py`**

At the top of the file, add a module import alongside the existing `from app.tools import schema as schema_mod`:

```python
from app.tools import prompt as prompt_mod
```

Inside `build_emerge_mcp`, after the existing `t_write_schema` block, add:

```python
    @tool(
        "write_prompt",
        "Write fields + global_notes to an existing prompt variant. "
        "prompt_id=null targets the active prompt. Use this instead of write_schema "
        "for any new code path — write_schema is the legacy wrapper.",
        {
            "project_id": str,
            "prompt_id": str,  # accept "" for None (claude-agent-sdk doesn't pass typed null)
            "schema": list,
            "global_notes": str,
        },
    )
    async def t_write_prompt(args: dict[str, Any]) -> dict[str, Any]:
        raw_pid_arg = args.get("prompt_id") or None  # "" → None
        fields = [SchemaField(**f) for f in args["schema"]]
        resolved = await prompt_mod.write_prompt(
            workspace,
            args["project_id"],
            prompt_id=raw_pid_arg,
            schema=fields,
            global_notes=args.get("global_notes", ""),
        )
        return {"content": [{"type": "text", "text": resolved}]}

    @tool(
        "create_prompt",
        "Create a new prompt variant by cloning either the current active prompt "
        "(derived_from='') or a specific prompt_id. Cross-project lineage strings "
        "({src_pid}/{src_prompt_id}) are recorded for display; actual cross-project "
        "import lands in M9.5.",
        {"project_id": str, "label": str, "derived_from": str},
    )
    async def t_create_prompt(args: dict[str, Any]) -> dict[str, Any]:
        derived = args.get("derived_from") or None
        new_id = await prompt_mod.create_prompt(
            workspace,
            args["project_id"],
            label=args["label"],
            derived_from=derived,
        )
        return {"content": [{"type": "text", "text": new_id}]}

    @tool(
        "switch_active_prompt",
        "Set the project's active prompt to the given prompt_id. Affects all "
        "subsequent reads of the active prompt (extract, freeze, etc).",
        {"project_id": str, "prompt_id": str},
    )
    async def t_switch_active_prompt(args: dict[str, Any]) -> dict[str, Any]:
        await prompt_mod.switch_active_prompt(
            workspace, args["project_id"], args["prompt_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "list_prompts",
        "List all prompt variants in a project with is_active flag.",
        {"project_id": str},
    )
    async def t_list_prompts(args: dict[str, Any]) -> dict[str, Any]:
        items = await prompt_mod.list_prompts(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": _json.dumps(items)}]}

    @tool(
        "delete_prompt",
        "Physically remove a prompt variant file. Cannot delete the active prompt "
        "(switch active first).",
        {"project_id": str, "prompt_id": str},
    )
    async def t_delete_prompt(args: dict[str, Any]) -> dict[str, Any]:
        await prompt_mod.delete_prompt(
            workspace, args["project_id"], args["prompt_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}
```

Add the 5 new tool callables to the `tools=[...]` list passed to `create_sdk_mcp_server` (insert after `t_write_schema`):

```python
            t_write_schema,
            t_write_prompt,
            t_create_prompt,
            t_switch_active_prompt,
            t_list_prompts,
            t_delete_prompt,
            t_extract_one,
```

Add the 5 new tool name strings to `_EMERGE_TOOL_NAMES` tuple:

```python
_EMERGE_TOOL_NAMES = (
    "create_project", "list_projects", "upload_doc", "list_docs", "pdf_render_page",
    "derive_schema", "read_schema", "write_schema",
    "write_prompt", "create_prompt", "switch_active_prompt", "list_prompts", "delete_prompt",
    "extract_one", "extract_batch",
    "save_reviewed", "list_reviewed", "get_reviewed", "get_prediction",
    "score",
    "start_job", "get_job", "pause_job", "resume_job", "cancel_job",
    "readiness_check", "contract_diff", "freeze_version", "issue_api_key",
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`
Expected: PASS.

Also run: `cd backend && uv run pytest -v 2>&1 | tail -5`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/__init__.py backend/tests/unit/test_tool_registration.py
git commit -m "feat(m9.2): expose prompt-axis MCP tools (write_prompt / create_prompt / switch_active_prompt / list_prompts / delete_prompt)"
```

---

## Task 5: Expose model MCP tools

**Files:**
- Modify: `backend/app/tools/__init__.py` (add 5 new `@tool` registrations + add to `_EMERGE_TOOL_NAMES`)
- Modify: `backend/tests/unit/test_tool_registration.py` (assert new tools are listed)

- [ ] **Step 1: Write failing test**

Append to `backend/tests/unit/test_tool_registration.py`:

```python
async def test_model_axis_tools_are_registered(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert {
        "write_model",
        "create_model",
        "switch_active_model",
        "list_models",
        "delete_model",
    }.issubset(names), names


def test_model_axis_tools_in_emerge_tool_names() -> None:
    names = _emerge_tool_names()
    for n in ("write_model", "create_model", "switch_active_model", "list_models", "delete_model"):
        assert n in names, f"missing {n!r} in _EMERGE_TOOL_NAMES"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v -k "model_axis"`
Expected: FAIL.

- [ ] **Step 3: Add 5 new `@tool` registrations to `backend/app/tools/__init__.py`**

At the top of the file, add:

```python
from app.tools import model as model_mod
```

Inside `build_emerge_mcp`, after the new prompt tools (after `t_delete_prompt`), add:

```python
    @tool(
        "write_model",
        "Upsert a model config (create if missing, otherwise update label/params/provider_model_id). "
        "provider is one of 'anthropic'|'openai'|'google'.",
        {
            "project_id": str,
            "model_id": str,
            "label": str,
            "provider": str,
            "provider_model_id": str,
            "params": dict,
        },
    )
    async def t_write_model(args: dict[str, Any]) -> dict[str, Any]:
        await model_mod.write_model(
            workspace,
            args["project_id"],
            model_id=args["model_id"],
            label=args["label"],
            provider=args["provider"],  # type: ignore[arg-type]
            provider_model_id=args["provider_model_id"],
            params=args.get("params") or {},
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "create_model",
        "Create a new model config with an auto-minted model_id. Returns the new model_id.",
        {
            "project_id": str,
            "label": str,
            "provider": str,
            "provider_model_id": str,
            "params": dict,
        },
    )
    async def t_create_model(args: dict[str, Any]) -> dict[str, Any]:
        new_mid = await model_mod.create_model(
            workspace,
            args["project_id"],
            label=args["label"],
            provider=args["provider"],  # type: ignore[arg-type]
            provider_model_id=args["provider_model_id"],
            params=args.get("params") or {},
        )
        return {"content": [{"type": "text", "text": new_mid}]}

    @tool(
        "switch_active_model",
        "Set the project's active model to the given model_id. Affects all "
        "subsequent extract calls when model_id arg is not explicitly provided.",
        {"project_id": str, "model_id": str},
    )
    async def t_switch_active_model(args: dict[str, Any]) -> dict[str, Any]:
        await model_mod.switch_active_model(
            workspace, args["project_id"], args["model_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "list_models",
        "List all model configs in a project with is_active flag.",
        {"project_id": str},
    )
    async def t_list_models(args: dict[str, Any]) -> dict[str, Any]:
        items = await model_mod.list_models(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": _json.dumps(items)}]}

    @tool(
        "delete_model",
        "Physically remove a model config file. Cannot delete the active model "
        "(switch active first).",
        {"project_id": str, "model_id": str},
    )
    async def t_delete_model(args: dict[str, Any]) -> dict[str, Any]:
        await model_mod.delete_model(
            workspace, args["project_id"], args["model_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}
```

Add the 5 new tool callables to the `tools=[...]` list (insert after `t_delete_prompt`):

```python
            t_delete_prompt,
            t_write_model,
            t_create_model,
            t_switch_active_model,
            t_list_models,
            t_delete_model,
            t_extract_one,
```

Update `_EMERGE_TOOL_NAMES`:

```python
_EMERGE_TOOL_NAMES = (
    "create_project", "list_projects", "upload_doc", "list_docs", "pdf_render_page",
    "derive_schema", "read_schema", "write_schema",
    "write_prompt", "create_prompt", "switch_active_prompt", "list_prompts", "delete_prompt",
    "write_model", "create_model", "switch_active_model", "list_models", "delete_model",
    "extract_one", "extract_batch",
    "save_reviewed", "list_reviewed", "get_reviewed", "get_prediction",
    "score",
    "start_job", "get_job", "pause_job", "resume_job", "cancel_job",
    "readiness_check", "contract_diff", "freeze_version", "issue_api_key",
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`
Expected: PASS.

Then run full suite: `cd backend && uv run pytest -v 2>&1 | tail -5`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/__init__.py backend/tests/unit/test_tool_registration.py
git commit -m "feat(m9.2): expose model-axis MCP tools (write_model / create_model / switch_active_model / list_models / delete_model)"
```

---

## Task 6: HTTP endpoints — `/lab/projects/{pid}/prompts*`

**Files:**
- Create: `backend/app/api/routes/prompts.py`
- Modify: `backend/app/main.py` (mount new router)
- Create: `backend/tests/unit/test_routes_prompts.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_routes_prompts.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    return TestClient(app)


def test_list_prompts_returns_active_marker(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create
    from app.tools.prompt import create_prompt as _create_prompt

    pid = asyncio.run(_create(tmp_path, name="t"))
    asyncio.run(_create_prompt(tmp_path, pid, label="trial"))

    r = client.get(f"/lab/projects/{pid}/prompts")
    assert r.status_code == 200
    rows = r.json()
    by_label = {row["label"]: row for row in rows}
    assert by_label["Baseline"]["is_active"] is True
    assert by_label["trial"]["is_active"] is False


def test_get_active_prompt_returns_full_blob_with_derived_from(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create
    from app.tools.prompt import create_prompt as _create_prompt, switch_active_prompt as _switch

    pid = asyncio.run(_create(tmp_path, name="t"))
    new_id = asyncio.run(_create_prompt(tmp_path, pid, label="trial"))
    asyncio.run(_switch(tmp_path, pid, new_id))

    r = client.get(f"/lab/projects/{pid}/prompts/active")
    assert r.status_code == 200
    blob = r.json()
    assert blob["prompt_id"] == new_id
    assert blob["label"] == "trial"
    assert blob["derived_from"] == "pr_baseline"
    assert "schema" in blob
    assert "global_notes" in blob


def test_get_prompt_by_id(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))
    r = client.get(f"/lab/projects/{pid}/prompts/pr_baseline")
    assert r.status_code == 200
    blob = r.json()
    assert blob["prompt_id"] == "pr_baseline"


def test_get_prompt_missing_404(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))
    r = client.get(f"/lab/projects/{pid}/prompts/pr_nope")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "prompt_not_found"


def test_list_prompts_legacy_project_migrates_first(client: TestClient, tmp_path: Path) -> None:
    pid = "p_legacyhttp02"
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
        "extract_model": "gemini-2.5-flash",
        "extract_params": {"temperature": 0.0},
        "active_version_id": None,
    }))
    (pdir / "schema.json").write_text(json.dumps([
        {"name": "x", "type": "string", "description": "d", "required": False},
    ]))

    r = client.get(f"/lab/projects/{pid}/prompts")
    assert r.status_code == 200
    assert (pdir / "prompts" / "pr_baseline.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_routes_prompts.py -v`
Expected: FAIL (router not mounted yet → 404 on all requests).

- [ ] **Step 3: Create `backend/app/api/routes/prompts.py`**

```python
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.tools.prompt import (
    PromptNotFoundError,
    list_prompts,
    read_active_prompt,
    read_prompt,
)
from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import project_json_path


router = APIRouter()


def _project_or_404(pid: str) -> Path:
    safe_project_id(pid)
    settings = get_settings()
    pj = project_json_path(settings.workspace_root, pid)
    if not pj.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return settings.workspace_root


@router.get("/lab/projects/{project_id}/prompts")
async def get_project_prompts(project_id: str) -> list[dict]:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    return await list_prompts(workspace, project_id)


@router.get("/lab/projects/{project_id}/prompts/active")
async def get_project_active_prompt(project_id: str) -> dict:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    pv = await read_active_prompt(workspace, project_id)
    return pv.model_dump(mode="json")


@router.get("/lab/projects/{project_id}/prompts/{prompt_id}")
async def get_project_prompt_by_id(project_id: str, prompt_id: str) -> dict:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    try:
        pv = await read_prompt(workspace, project_id, prompt_id)
    except PromptNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "prompt_not_found"},
        )
    return pv.model_dump(mode="json")
```

- [ ] **Step 4: Mount the router in `backend/app/main.py`**

Locate the section where existing routers are included. Add the new one alongside (find the existing schema router include and add):

```python
from app.api.routes import prompts as prompts_routes
app.include_router(prompts_routes.router)
```

Place the include next to the other `/lab/projects/{pid}/...` routers (typically in alphabetical order or grouped near `schema_routes`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_routes_prompts.py -v`
Expected: PASS (5 tests).

Also run full suite: `cd backend && uv run pytest -v 2>&1 | tail -5`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/prompts.py backend/app/main.py backend/tests/unit/test_routes_prompts.py
git commit -m "feat(m9.2): HTTP endpoints — /lab/projects/{pid}/prompts (list/active/by-id)"
```

---

## Task 7: HTTP endpoints — `/lab/projects/{pid}/models*`

**Files:**
- Create: `backend/app/api/routes/models.py`
- Modify: `backend/app/main.py` (mount new router)
- Create: `backend/tests/unit/test_routes_models.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_routes_models.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    return TestClient(app)


def test_list_models_returns_active_marker(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create
    from app.tools.model import create_model as _create_model

    pid = asyncio.run(_create(tmp_path, name="t"))
    asyncio.run(_create_model(
        tmp_path, pid,
        label="Sonnet 4.6", provider="anthropic", provider_model_id="claude-sonnet-4-6",
    ))
    r = client.get(f"/lab/projects/{pid}/models")
    assert r.status_code == 200
    rows = r.json()
    by_label = {row["label"]: row for row in rows}
    assert by_label["Default (gemini-2.5-flash)"]["is_active"] is True
    assert by_label["Sonnet 4.6"]["is_active"] is False


def test_get_active_model_returns_full_blob(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))
    r = client.get(f"/lab/projects/{pid}/models/active")
    assert r.status_code == 200
    blob = r.json()
    assert blob["model_id"] == "m_default"
    assert blob["provider"] == "google"
    assert blob["provider_model_id"] == "gemini-2.5-flash"


def test_get_model_by_id(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))
    r = client.get(f"/lab/projects/{pid}/models/m_default")
    assert r.status_code == 200
    blob = r.json()
    assert blob["model_id"] == "m_default"


def test_get_model_missing_404(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))
    r = client.get(f"/lab/projects/{pid}/models/m_nope")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "model_not_found"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_routes_models.py -v`
Expected: FAIL (404 on all).

- [ ] **Step 3: Create `backend/app/api/routes/models.py`**

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.tools.model import (
    ModelNotFoundError,
    list_models,
    read_active_model,
    read_model,
)
from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import project_json_path


router = APIRouter()


def _project_or_404(pid: str) -> Path:
    safe_project_id(pid)
    settings = get_settings()
    pj = project_json_path(settings.workspace_root, pid)
    if not pj.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return settings.workspace_root


@router.get("/lab/projects/{project_id}/models")
async def get_project_models(project_id: str) -> list[dict]:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    return await list_models(workspace, project_id)


@router.get("/lab/projects/{project_id}/models/active")
async def get_project_active_model(project_id: str) -> dict:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    mc = await read_active_model(workspace, project_id)
    return mc.model_dump(mode="json")


@router.get("/lab/projects/{project_id}/models/{model_id}")
async def get_project_model_by_id(project_id: str, model_id: str) -> dict:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    try:
        mc = await read_model(workspace, project_id, model_id)
    except ModelNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "model_not_found"},
        )
    return mc.model_dump(mode="json")
```

- [ ] **Step 4: Mount the router in `backend/app/main.py`**

Add next to the prompts router:

```python
from app.api.routes import models as models_routes
app.include_router(models_routes.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_routes_models.py -v`
Expected: PASS (4 tests).

Then full suite: `cd backend && uv run pytest -v 2>&1 | tail -5`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/models.py backend/app/main.py backend/tests/unit/test_routes_models.py
git commit -m "feat(m9.2): HTTP endpoints — /lab/projects/{pid}/models (list/active/by-id)"
```

---

## Task 8: Update agent SKILL to use new tool names

**Files:**
- Modify: `backend/app/skills/emerge_extractor.md`

- [ ] **Step 1: Read the current SKILL**

Re-read `backend/app/skills/emerge_extractor.md`. Key references to update:
- Line 19: `schema.json is mutated only via the write_schema tool.` — outdated phrasing
- Lines 23, 27, 37, 41, 43: references to `write_schema(allow_structural=...)`, `read_schema`
- The agent should know **`write_schema` is the legacy compat wrapper**, **`write_prompt` is the canonical write path**, and that creating a variant for A/B testing uses `create_prompt`/`switch_active_prompt`.

- [ ] **Step 2: Update `emerge_extractor.md`** — apply these targeted edits:

Replace the line:
```
- `schema.json` is mutated only via the `write_schema` tool.
```
with:
```
- The active prompt's schema + global_notes are mutated only via `write_prompt` (preferred)
  or `write_schema` (legacy wrapper kept for backward compat). The on-disk file
  is `prompts/{active_prompt_id}.json`. `schema.json` is retired for new projects.
```

Replace the "Risk gates" bullet:
```
- Structural schema changes: `write_schema` with `allow_structural=true`
  when adding, removing, renaming, or retyping a field. Pure description-text
  edits do NOT require confirmation.
```
with:
```
- Structural prompt changes: `write_prompt` (or legacy `write_schema`) with
  `allow_structural=true` when adding, removing, renaming, or retyping a field.
  Pure description-text edits do NOT require confirmation. (`write_prompt` does
  not yet take `allow_structural`; for structural changes, prefer the
  `write_schema` wrapper one more milestone.)
- Switching active prompt or model (`switch_active_prompt` / `switch_active_model`):
  confirm with the user — these change what every subsequent extract uses.
- Deleting a prompt or model (`delete_prompt` / `delete_model`): always confirm.
```

In "Free-form intent routing" bullet 1, replace the bootstrap chain:
```
   `create_project` → `upload_doc × N` → `derive_schema(sample=3, intent=...)`
   → `write_schema(allow_structural=true, reason="initial bootstrap")` →
   `extract_batch`. Summarize results in chat.
```
with:
```
   `create_project` → `upload_doc × N` → `derive_schema(sample=3, intent=...)`
   → `write_schema(allow_structural=true, reason="initial bootstrap")` (writes
   to the freshly-minted active prompt `pr_baseline`) → `extract_batch`.
   Summarize results in chat.
```

In bullet 2, replace:
```
   wait for confirmation before `write_schema(allow_structural=true)`.
```
with:
```
   wait for confirmation before `write_schema(allow_structural=true)`. For
   isolated A/B testing of a description tweak, prefer
   `create_prompt(label="…", derived_from="")` → `write_prompt(prompt_id=<new>, …)`
   → user later promotes via `switch_active_prompt`. (Experiments + eval comparison
   land in M9.3.)
```

In bullet 3, leave existing as-is — description-only edits via `write_schema` still work.

Add a new top-level section after "Tool usage hints" titled "## Prompt and model axes (M9.2+)":

```
## Prompt and model axes (M9.2+)

A project has two independent axes that affect extraction behavior:

1. **Prompts** (`prompts/{prompt_id}.json`) — bundles fields, descriptions, and
   `global_notes` into a single named unit. `pr_baseline` is the default;
   `create_prompt(label, derived_from)` mints additional variants. The active
   one is recorded in `project.json.active_prompt_id`. Use `list_prompts` to
   enumerate, `switch_active_prompt(prompt_id)` to select.
2. **Models** (`models/{model_id}.json`) — `(provider, provider_model_id, params)`
   triple. `m_default` is the default; `create_model(label, provider, …)` adds
   more. The active one is recorded in `project.json.active_model_id`. Use
   `list_models` and `switch_active_model`.

When the user describes wanting to A/B test something ("试一下 Gemma 4", "改个
描述看看效果"), prefer creating a fresh variant on the relevant axis rather
than mutating the active one. This keeps a known-good baseline for comparison.
Comparing extract outputs from two prompt/model combinations on the same docs
is the *experiment* abstraction — that lands in M9.3. In M9.2 you can switch
active back-and-forth to compare manually, but warn the user that
`predictions/_draft/` will be overwritten by the latest extract.
```

- [ ] **Step 3: Manually sanity-check via grep**

Run: `grep -n "schema.json\|write_schema" backend/app/skills/emerge_extractor.md`
Each remaining reference should now have either a "(legacy …)" qualifier or appear in the bootstrap chain context.

- [ ] **Step 4: Commit**

```bash
git add backend/app/skills/emerge_extractor.md
git commit -m "docs(m9.2): SKILL — point agent at write_prompt / create_prompt / switch_active_* tools"
```

---

## Task 9: Frontend stores — `usePrompts` + `useModels`

**Files:**
- Create: `frontend/src/stores/prompts.ts`
- Create: `frontend/src/stores/models.ts`
- Create: `frontend/tests/unit/stores/prompts.test.ts`
- Create: `frontend/tests/unit/stores/models.test.ts`

- [ ] **Step 1: Write failing test for `usePrompts`**

Create `frontend/tests/unit/stores/prompts.test.ts`:

```typescript
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { usePrompts } from '../../../src/stores/prompts'

describe('usePrompts', () => {
  beforeEach(() => {
    usePrompts.getState().reset()
    vi.restoreAllMocks()
  })

  it('loads list + active for a project', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async (input: any) => {
      const url = typeof input === 'string' ? input : input.url
      if (url.endsWith('/prompts')) {
        return new Response(JSON.stringify([
          { prompt_id: 'pr_baseline', label: 'Baseline', derived_from: null,
            is_active: true, created_at: 'x', updated_at: 'x' },
          { prompt_id: 'pr_other', label: 'Other', derived_from: 'pr_baseline',
            is_active: false, created_at: 'x', updated_at: 'x' },
        ]), { status: 200 })
      }
      if (url.endsWith('/prompts/active')) {
        return new Response(JSON.stringify({
          prompt_id: 'pr_baseline',
          label: 'Baseline',
          schema: [{ name: 'x', type: 'string', description: 'd' }],
          global_notes: '',
          derived_from: null,
          created_at: 'x',
          updated_at: 'x',
        }), { status: 200 })
      }
      return new Response('not found', { status: 404 })
    })

    await usePrompts.getState().load('p_abc')
    const state = usePrompts.getState()
    expect(state.list['p_abc']).toHaveLength(2)
    expect(state.activeByProject['p_abc']?.prompt_id).toBe('pr_baseline')
    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })

  it('dedupes concurrent loads', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async (input: any) => {
      const url = typeof input === 'string' ? input : input.url
      if (url.endsWith('/prompts')) {
        return new Response('[]', { status: 200 })
      }
      return new Response('{"prompt_id":"x","label":"x","schema":[],"global_notes":"","derived_from":null,"created_at":"x","updated_at":"x"}', { status: 200 })
    })
    await Promise.all([
      usePrompts.getState().load('p_abc'),
      usePrompts.getState().load('p_abc'),
    ])
    // 2 endpoints × 1 (deduped) = 2 fetches, NOT 4
    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })

  it('invalidate clears project entry', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async () =>
      new Response('[]', { status: 200 }),
    )
    await usePrompts.getState().load('p_abc')
    usePrompts.getState().invalidate('p_abc')
    expect(usePrompts.getState().list['p_abc']).toBeUndefined()
  })
})
```

- [ ] **Step 2: Write failing test for `useModels`**

Create `frontend/tests/unit/stores/models.test.ts` (mirrors `prompts.test.ts`):

```typescript
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useModels } from '../../../src/stores/models'

describe('useModels', () => {
  beforeEach(() => {
    useModels.getState().reset()
    vi.restoreAllMocks()
  })

  it('loads list + active for a project', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (input: any) => {
      const url = typeof input === 'string' ? input : input.url
      if (url.endsWith('/models')) {
        return new Response(JSON.stringify([
          { model_id: 'm_default', label: 'Default', provider: 'google',
            provider_model_id: 'gemini-2.5-flash', is_active: true, created_at: 'x' },
          { model_id: 'm_sonnet', label: 'Sonnet 4.6', provider: 'anthropic',
            provider_model_id: 'claude-sonnet-4-6', is_active: false, created_at: 'x' },
        ]), { status: 200 })
      }
      if (url.endsWith('/models/active')) {
        return new Response(JSON.stringify({
          model_id: 'm_default',
          label: 'Default',
          provider: 'google',
          provider_model_id: 'gemini-2.5-flash',
          params: { temperature: 0 },
          created_at: 'x',
        }), { status: 200 })
      }
      return new Response('not found', { status: 404 })
    })

    await useModels.getState().load('p_abc')
    const state = useModels.getState()
    expect(state.list['p_abc']).toHaveLength(2)
    expect(state.activeByProject['p_abc']?.provider_model_id).toBe('gemini-2.5-flash')
  })
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm test -- prompts.test.ts models.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 4: Implement `frontend/src/stores/prompts.ts`**

```typescript
import { create } from 'zustand'
import type { SchemaField } from './schema'

export interface PromptRow {
  prompt_id: string
  label: string
  derived_from: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ActivePrompt {
  prompt_id: string
  label: string
  schema: SchemaField[]
  global_notes: string
  derived_from: string | null
  created_at: string
  updated_at: string
}

interface State {
  list: Record<string, PromptRow[]>
  activeByProject: Record<string, ActivePrompt | undefined>
  loading: Record<string, boolean>
  load: (projectId: string) => Promise<void>
  invalidate: (projectId: string) => void
  reset: () => void
}

export const usePrompts = create<State>((set, get) => ({
  list: {},
  activeByProject: {},
  loading: {},

  reset: () => set({ list: {}, activeByProject: {}, loading: {} }),

  invalidate: (projectId) =>
    set((s) => {
      const list = { ...s.list }; delete list[projectId]
      const active = { ...s.activeByProject }; delete active[projectId]
      return { list, activeByProject: active }
    }),

  load: async (projectId) => {
    if (get().loading[projectId]) {
      // dedupe in-flight
      return new Promise<void>((resolve) => {
        const unsub = usePrompts.subscribe((s) => {
          if (!s.loading[projectId]) { unsub(); resolve() }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    try {
      const [listResp, activeResp] = await Promise.all([
        fetch(`/lab/projects/${projectId}/prompts`),
        fetch(`/lab/projects/${projectId}/prompts/active`),
      ])
      const list = listResp.ok ? (await listResp.json() as PromptRow[]) : []
      const active = activeResp.ok ? (await activeResp.json() as ActivePrompt) : undefined
      set((s) => ({
        list: { ...s.list, [projectId]: list },
        activeByProject: { ...s.activeByProject, [projectId]: active },
      }))
    } finally {
      set((s) => {
        const next = { ...s.loading }; delete next[projectId]
        return { loading: next }
      })
    }
  },
}))
```

- [ ] **Step 5: Implement `frontend/src/stores/models.ts`** (mirror structure)

```typescript
import { create } from 'zustand'

export interface ModelRow {
  model_id: string
  label: string
  provider: 'anthropic' | 'openai' | 'google'
  provider_model_id: string
  is_active: boolean
  created_at: string
}

export interface ActiveModel {
  model_id: string
  label: string
  provider: 'anthropic' | 'openai' | 'google'
  provider_model_id: string
  params: Record<string, unknown>
  created_at: string
}

interface State {
  list: Record<string, ModelRow[]>
  activeByProject: Record<string, ActiveModel | undefined>
  loading: Record<string, boolean>
  load: (projectId: string) => Promise<void>
  invalidate: (projectId: string) => void
  reset: () => void
}

export const useModels = create<State>((set, get) => ({
  list: {},
  activeByProject: {},
  loading: {},

  reset: () => set({ list: {}, activeByProject: {}, loading: {} }),

  invalidate: (projectId) =>
    set((s) => {
      const list = { ...s.list }; delete list[projectId]
      const active = { ...s.activeByProject }; delete active[projectId]
      return { list, activeByProject: active }
    }),

  load: async (projectId) => {
    if (get().loading[projectId]) {
      return new Promise<void>((resolve) => {
        const unsub = useModels.subscribe((s) => {
          if (!s.loading[projectId]) { unsub(); resolve() }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    try {
      const [listResp, activeResp] = await Promise.all([
        fetch(`/lab/projects/${projectId}/models`),
        fetch(`/lab/projects/${projectId}/models/active`),
      ])
      const list = listResp.ok ? (await listResp.json() as ModelRow[]) : []
      const active = activeResp.ok ? (await activeResp.json() as ActiveModel) : undefined
      set((s) => ({
        list: { ...s.list, [projectId]: list },
        activeByProject: { ...s.activeByProject, [projectId]: active },
      }))
    } finally {
      set((s) => {
        const next = { ...s.loading }; delete next[projectId]
        return { loading: next }
      })
    }
  },
}))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npm test -- prompts.test.ts models.test.ts`
Expected: PASS.

Also run the full frontend suite: `cd frontend && npm test`
Expected: All pass — adding new files should not regress others.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/stores/prompts.ts frontend/src/stores/models.ts \
        frontend/tests/unit/stores/prompts.test.ts frontend/tests/unit/stores/models.test.ts
git commit -m "feat(m9.2): usePrompts + useModels Zustand stores (list + active per project)"
```

---

## Task 10: FSSpine — `prompts/` + `models/` groups

**Files:**
- Modify: `frontend/src/components/Spine/FSSpine.tsx`
- Modify: `frontend/tests/unit/Spine/FSSpine.test.tsx` (or wherever the existing FSSpine unit tests live; check `ls frontend/tests/unit/Spine/`)

- [ ] **Step 1: Inventory existing FSSpine tests**

Run: `find frontend/tests -name "FSSpine*"` and read each match. Note current assertions on the tree shape (especially the `schema.json` row).

- [ ] **Step 2: Write failing tests asserting new tree shape**

Replace assertions about the `schema.json` row with assertions about `prompts/` and `models/` groups. Concretely, where the current test does:

```typescript
expect(screen.getByText('schema.json')).toBeInTheDocument()
```

replace with (depending on the open/closed default — we keep both groups CLOSED by default, matching `versions/`):

```typescript
expect(screen.queryByText('schema.json')).not.toBeInTheDocument()
expect(screen.getByText('prompts/')).toBeInTheDocument()
expect(screen.getByText('models/')).toBeInTheDocument()
```

Add a new test that, with mocked stores providing 2 prompts (one active) and 2 models (one active), expanding `prompts/` shows the row labels with ⭐ for the active one. (Use the same store-mocking pattern the existing FSSpine tests use — likely via `vi.mock('../../../src/stores/...')` or store `reset` + `setState`.)

Example test sketch:

```typescript
it('expands prompts/ and marks active row with star', async () => {
  // ... mount FSSpine with a project that has 2 prompts pre-loaded ...
  fireEvent.click(screen.getByText('prompts/'))
  expect(screen.getByText('pr_baseline')).toBeInTheDocument()
  // active marker (⭐ unicode or class)
  expect(screen.getByText('pr_baseline').parentElement).toHaveClass('active-prompt')
})
```

If the existing test file imports `useSchema` as the data source and the new behavior depends on `usePrompts` + `useModels`, mock those instead.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm test -- FSSpine`
Expected: FAIL.

- [ ] **Step 4: Refactor `frontend/src/components/Spine/FSSpine.tsx`**

Drive `prompts/` and `models/` from `usePrompts` / `useModels`. Keep the existing tree shape pattern (DirGroup + LeafNode). The full refactor:

```typescript
// frontend/src/components/Spine/FSSpine.tsx
import { useEffect, useMemo, useState } from 'react'
import './spine.css'

import { useProjects } from '../../stores/projects'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'
import { usePrompts } from '../../stores/prompts'
import { useModels } from '../../stores/models'
import { useQuickLook } from '../../stores/quicklook'

type FileNode  = { kind: 'file';  name: string; stamp: string; active?: boolean; onClick?: () => void }
type GhostNode = { kind: 'ghost'; name: string }
type LeafNode  = FileNode | GhostNode
type DirGroup  = { name: string; count: number; items: LeafNode[] }
interface BuiltTree { groups: DirGroup[]; rootFiles: FileNode[] }

const STATUS_DOT: Record<string, string> = {
  live: 'var(--moss)',
  draft: 'var(--ochre)',
  empty: 'var(--ink-5)',
}

function buildTree(
  docs: import('../../types/review').DocSummary[],
  activeVersionId: string | null,
  prompts: import('../../stores/prompts').PromptRow[],
  models: import('../../stores/models').ModelRow[],
  onOpenSchema: () => void,
): BuiltTree {
  // ── docs/ ──────────────────────────────────────────────────────────────
  const docsItems: LeafNode[] = []
  const first5 = docs.slice(0, 5)
  for (const doc of first5) {
    let stamp: string
    if (doc.has_reviewed) stamp = 'reviewed'
    else if (doc.has_prediction) stamp = 'pending'
    else stamp = 'new'
    docsItems.push({ kind: 'file', name: doc.filename, stamp })
  }
  const remaining = docs.length - first5.length
  if (remaining > 0) docsItems.push({ kind: 'ghost', name: `… ${remaining} more` })

  // ── reviewed/ ──────────────────────────────────────────────────────────
  const reviewedDocs = docs.filter(d => d.has_reviewed)
  const reviewedItems: LeafNode[] = []
  const first5Reviewed = reviewedDocs.slice(0, 5)
  for (const doc of first5Reviewed) reviewedItems.push({ kind: 'file', name: doc.filename, stamp: '' })
  const remainingReviewed = reviewedDocs.length - first5Reviewed.length
  if (remainingReviewed > 0) reviewedItems.push({ kind: 'ghost', name: `… ${remainingReviewed} more` })
  else if (reviewedDocs.length === 0) reviewedItems.push({ kind: 'ghost', name: '(none yet)' })

  // ── prompts/ ───────────────────────────────────────────────────────────
  const promptItems: LeafNode[] = prompts.length === 0
    ? [{ kind: 'ghost', name: '(none yet)' }]
    : prompts.map(p => ({
        kind: 'file' as const,
        name: p.label,
        stamp: p.is_active ? 'active' : '',
        active: p.is_active,
        // Clicking the active prompt opens quick-look. Non-active for now: no-op
        // (M9.3 will add explicit "preview variant" affordance).
        onClick: p.is_active ? onOpenSchema : undefined,
      }))

  // ── models/ ────────────────────────────────────────────────────────────
  const modelItems: LeafNode[] = models.length === 0
    ? [{ kind: 'ghost', name: '(none yet)' }]
    : models.map(m => ({
        kind: 'file' as const,
        name: m.label,
        stamp: m.is_active ? 'active' : '',
        active: m.is_active,
      }))

  // ── versions/ ──────────────────────────────────────────────────────────
  const versionItems: LeafNode[] = activeVersionId
    ? [{ kind: 'file', name: activeVersionId, stamp: 'frozen' }]
    : [{ kind: 'ghost', name: '(no versions yet)' }]

  // ── trailing root files ────────────────────────────────────────────────
  const rootFiles: FileNode[] = [
    { kind: 'file', name: 'README.md', stamp: '' },
  ]

  return {
    groups: [
      { name: 'docs/', count: docs.length, items: docsItems },
      { name: 'reviewed/', count: reviewedDocs.length, items: reviewedItems },
      { name: 'prompts/', count: prompts.length, items: promptItems },
      { name: 'models/', count: models.length, items: modelItems },
      { name: 'versions/', count: activeVersionId ? 1 : 0, items: versionItems },
    ],
    rootFiles,
  }
}

export default function FSSpine() {
  const projects = useProjects(s => s.projects)
  const selectedId = useProjects(s => s.selectedId)

  const docsByProject = useDocs(s => s.byProject)
  const promptsList = usePrompts(s => s.list)
  const modelsList = useModels(s => s.list)

  const openSchema = useQuickLook(s => s.openSchema)
  const openVersion = useQuickLook(s => s.openVersion)

  const [openDirs, setOpenDirs] = useState<Record<string, boolean>>({ 'docs/': true })
  const toggleDir = (name: string) => setOpenDirs(s => ({ ...s, [name]: !s[name] }))

  useEffect(() => { void useProjects.getState().refresh() }, [])

  // When active project changes: load docs + schema + prompts + models
  useEffect(() => {
    if (!selectedId) return
    void useDocs.getState().refresh(selectedId)
    void useSchema.getState().load(selectedId)
    void usePrompts.getState().load(selectedId)
    void useModels.getState().load(selectedId)
  }, [selectedId])

  const activeDocs = selectedId ? (docsByProject[selectedId] ?? []) : []
  const activePrompts = selectedId ? (promptsList[selectedId] ?? []) : []
  const activeModels = selectedId ? (modelsList[selectedId] ?? []) : []
  const activeProject = projects.find(p => p.project_id === selectedId) ?? null

  const tree = useMemo<BuiltTree | null>(
    () => (activeProject && selectedId)
      ? buildTree(
          activeDocs,
          activeProject.active_version_id ?? null,
          activePrompts,
          activeModels,
          () => openSchema(selectedId),
        )
      : null,
    [activeProject, selectedId, activeDocs, activePrompts, activeModels, openSchema],
  )

  return (
    <div className="fs">
      <div className="fs-head">
        ~/projects <span className="small">{projects.length}</span>
      </div>

      {projects.length === 0 && (
        <div className="ghost" style={{ padding: '4px 16px' }}>no projects yet</div>
      )}
      {projects.map(p => {
        const isActive = p.project_id === selectedId
        return (
          <div
            key={p.project_id}
            className={'proj' + (isActive ? ' active' : '')}
            onClick={() => useProjects.getState().select(p.project_id)}
          >
            <span className="glyph">{isActive ? '▸' : '·'}</span>
            <span>{p.name}/</span>
            {isActive && (
              <span
                className="status-dot"
                title={p.status ?? 'empty'}
                style={{ background: STATUS_DOT[p.status ?? 'empty'] ?? 'var(--ink-5)' }}
              />
            )}
          </div>
        )
      })}

      <div
        className="proj"
        onClick={() => useProjects.getState().select(null)}
        style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}
      >
        <span className="glyph">+</span>
        <span>new project…</span>
      </div>

      {activeProject && tree && (
        <>
          <hr />
          <div className="fs-head">
            {activeProject.name}/ <span className="small">ls</span>
          </div>
          <div className="tree">
            {tree.groups.map(g => {
              const open = !!openDirs[g.name]
              return (
                <div key={g.name}>
                  <div className="branch dir" onClick={() => toggleDir(g.name)}>
                    <span className="arrow">{open ? '▾' : '▸'}</span>
                    <span>{g.name}</span>
                    <span className="stamp">{g.count}</span>
                  </div>
                  {open && g.items.map((n, j) => {
                    if (n.kind === 'ghost') return <div key={j} className="ghost">{n.name}</div>
                    const isVersion = g.name === 'versions/' && selectedId
                    const onClickFn = isVersion
                      ? () => openVersion(selectedId!, n.name)
                      : n.onClick
                    return (
                      <div
                        key={j}
                        className={'branch file' + (n.active ? ' active-row' : '')}
                        onClick={onClickFn}
                        role={onClickFn ? 'button' : undefined}
                        tabIndex={onClickFn ? 0 : undefined}
                        onKeyDown={onClickFn ? e => { if (e.key === 'Enter' || e.key === ' ') onClickFn() } : undefined}
                        style={onClickFn ? { cursor: 'pointer' } : undefined}
                      >
                        <span style={{ color: 'var(--ink-5)' }}>{n.active ? '⭐' : '·'}</span>
                        <span>{n.name}</span>
                        {n.stamp && <span className="stamp">{n.stamp}</span>}
                      </div>
                    )
                  })}
                </div>
              )
            })}
            {tree.rootFiles.map((n, k) => (
              <div key={'r' + k} className="branch file" style={{ paddingLeft: 18 }}>
                <span style={{ color: 'var(--ink-5)' }}>·</span>
                <span>{n.name}</span>
                {n.stamp && <span className="stamp">{n.stamp}</span>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
```

Note: the existing `useSchema` import is kept (it still drives ContextSurface's quick-look prefetch via the legacy path). Removing it requires touching ContextSurface in the next task.

If there's a per-row active CSS class in `spine.css` referenced by tests (`active-prompt`, `active-model`), keep the class name `active-row` (generic) — adjust test assertion to match. If the test you wrote in Step 2 used `active-prompt`, update it to `active-row` so it matches what we render.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test -- FSSpine`
Expected: PASS.

Then full frontend suite: `cd frontend && npm test`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Spine/FSSpine.tsx frontend/tests/unit/Spine/
git commit -m "feat(m9.2): FSSpine — prompts/ + models/ groups (replaces schema.json row)"
```

---

## Task 11: ContextSurface — Prompt + Model cards

**Files:**
- Modify: `frontend/src/components/Context/ContextSurface.tsx`
- Modify: `frontend/tests/unit/Context/ContextSurface.test.tsx`

- [ ] **Step 1: Read existing ContextSurface tests**

Run: `find frontend/tests -name "ContextSurface*"` and read them. The existing tests assert on the `schema.json` section header text + field rows. We'll preserve "field rows" semantics but rename header.

- [ ] **Step 2: Write failing tests asserting new shape**

Replace assertions for `schema.json` header with `Prompt` (or `Prompt: pr_baseline`). Add a new test asserting the Model card renders the active model's label + provider_model_id.

Example sketch:

```typescript
it('renders Prompt card with active prompt id + field count', async () => {
  // ... mount with mocked usePrompts.activeByProject and useSchema for the field rows ...
  expect(screen.getByText(/Prompt:.*pr_baseline/)).toBeInTheDocument()
  expect(screen.getByText(/8 fields/)).toBeInTheDocument()
})

it('renders Model card with active model label + provider_model_id', async () => {
  // ... mount with mocked useModels.activeByProject ...
  expect(screen.getByText('Model')).toBeInTheDocument()
  expect(screen.getByText('gemini-2.5-flash')).toBeInTheDocument()
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm test -- ContextSurface`
Expected: FAIL.

- [ ] **Step 4: Refactor `frontend/src/components/Context/ContextSurface.tsx`**

Replace the existing section 1 (`schema.json`) block with two side-by-side or stacked cards. The minimal-change approach: keep the existing CSS grid; introduce 2 `.ctx-section` blocks back-to-back instead of one. Add `usePrompts` + `useModels` imports and pull from `activeByProject`.

Full replacement of the file (only section 1 changes; sections 2 + 3 stay identical):

```typescript
// frontend/src/components/Context/ContextSurface.tsx
import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'

import { useProjects } from '../../stores/projects'
import { useSchema } from '../../stores/schema'
import { usePrompts } from '../../stores/prompts'
import { useModels } from '../../stores/models'
import { useDocs } from '../../stores/docs'
import { useEval } from '../../stores/eval'
import { useReview } from '../../stores/review'
import { useQuickLook } from '../../stores/quicklook'
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

interface MetricRow { k: string; v: string; tone: MetricTone }

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

  const activePrompt = usePrompts(s => (pid ? s.activeByProject[pid] : undefined))
  const loadPrompts = usePrompts(s => s.load)

  const activeModel = useModels(s => (pid ? s.activeByProject[pid] : undefined))
  const loadModels = useModels(s => s.load)

  const docs = useDocs(useShallow(s => s.byProject[pid] ?? []))
  const refreshDocs = useDocs(s => s.refresh)

  const evalSnap = useEval(s => (pid ? s.byProject[pid] : undefined))
  const loadEval = useEval(s => s.load)

  const { open: openReview } = useReview()
  const openQuickLook = useQuickLook(s => s.openSchema)
  const project = projects.find(p => p.project_id === pid) ?? null

  useEffect(() => {
    if (!pid) return
    void loadSchema(pid)
    void loadPrompts(pid)
    void loadModels(pid)
    void refreshDocs(pid)
    void loadEval(pid)
  }, [pid, loadSchema, loadPrompts, loadModels, refreshDocs, loadEval])

  const versionStr = project?.active_version_id
    ? `${project.active_version_id} frozen`
    : 'v0 draft'
  const promptLabel = activePrompt?.prompt_id ?? 'pr_baseline'
  const promptHint = `${fields.length} fields · ${versionStr}`
  const modelHint = activeModel?.provider_model_id ?? '—'
  const modelLabel = activeModel?.label ?? 'Default'

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

  const metrics = evalSnap ? deriveMetrics(evalSnap) : null
  const metricsHint = metrics?.hint ?? 'latest eval'

  return (
    <div className="ctx">
      {/* ── section 1a: Prompt ──────────────────────────────────── */}
      <div className="ctx-section">
        <div
          className="ctx-h"
          onClick={() => openQuickLook(pid)}
          role="button"
          tabIndex={0}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') openQuickLook(pid) }}
          style={{ cursor: 'pointer' }}
        >
          <span>Prompt: {promptLabel}</span>
          <span className="small">{promptHint}</span>
        </div>
        <div className="ctx-card">
          {fields.length === 0 ? (
            <div className="schemaRow" style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}>
              no fields yet — type /init in the chat
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
            </>
          )}
        </div>
        <p className="micro" style={{ marginTop: 8 }}>
          The prompt (fields + descriptions + global notes) becomes the agent's
          instruction at publish time. Edit through conversation.
        </p>
      </div>

      {/* ── section 1b: Model ───────────────────────────────────── */}
      <div className="ctx-section">
        <div className="ctx-h">
          <span>Model: {modelLabel}</span>
          <span className="small">{modelHint}</span>
        </div>
        <div className="ctx-card">
          <div className="schemaRow">
            <span>{activeModel?.provider ?? '—'}</span>
            <span className="typ">{activeModel?.provider_model_id ?? '—'}</span>
          </div>
        </div>
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

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test -- ContextSurface`
Expected: PASS.

Then full frontend suite: `cd frontend && npm test`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Context/ContextSurface.tsx frontend/tests/unit/Context/
git commit -m "feat(m9.2): ContextSurface — Prompt + Model cards (replaces single schema section)"
```

---

## Task 12: Quick-look lineage row — render real `derived_from`

**Files:**
- Modify: `frontend/src/components/QuickLook/QuickLookHeader.tsx`
- Modify: `frontend/src/components/QuickLook/SchemaQuickLook.tsx`
- Modify: `frontend/tests/unit/QuickLook/QuickLookHeader.test.tsx` (find via `find frontend/tests -name "QuickLookHeader*"`)

- [ ] **Step 1: Write failing tests**

Find the existing QuickLookHeader unit test file. The current test likely asserts `derived from: —`. Add new tests:

```typescript
it('renders real derived_from when provided', () => {
  const target = { kind: 'schema' as const, pid: 'p_abc' }
  render(
    <QuickLookHeader
      target={target}
      activeVersionId={null}
      derivedFrom="pr_baseline"
      onClose={() => {}}
    />,
  )
  expect(screen.getByText('derived from: pr_baseline')).toBeInTheDocument()
})

it('renders cross-project derived_from string', () => {
  const target = { kind: 'schema' as const, pid: 'p_abc' }
  render(
    <QuickLookHeader
      target={target}
      activeVersionId={null}
      derivedFrom="p_us_invoice/pr_baseline"
      onClose={() => {}}
    />,
  )
  expect(screen.getByText('derived from: p_us_invoice/pr_baseline')).toBeInTheDocument()
})

it('falls back to em dash when derivedFrom is null', () => {
  const target = { kind: 'schema' as const, pid: 'p_abc' }
  render(
    <QuickLookHeader
      target={target}
      activeVersionId={null}
      derivedFrom={null}
      onClose={() => {}}
    />,
  )
  expect(screen.getByText('derived from: —')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- QuickLookHeader`
Expected: FAIL (prop `derivedFrom` doesn't exist yet).

- [ ] **Step 3: Update `frontend/src/components/QuickLook/QuickLookHeader.tsx`**

```typescript
import type { QuickLookTarget } from '../../stores/quicklook'

interface Props {
  target: QuickLookTarget
  activeVersionId: string | null
  derivedFrom: string | null
  onClose: () => void
}

export default function QuickLookHeader({ target, activeVersionId, derivedFrom, onClose }: Props) {
  const title = target.kind === 'schema' ? 'prompts/active' : `versions/${target.versionId}`

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
      <div className="ql-lineage">derived from: {derivedFrom ?? '—'}</div>
    </div>
  )
}
```

NOTE: Title text changed from `schema.json` → `prompts/active`. Search for any tests asserting the old title and update them. Run `grep -rn "schema.json" frontend/tests/` to find them.

- [ ] **Step 4: Wire the prop in `frontend/src/components/QuickLook/SchemaQuickLook.tsx`**

The current `SchemaQuickLook.tsx` invokes `<QuickLookHeader target={target} activeVersionId={activeVersionId} onClose={close} />`. Add a `derivedFrom` prop sourced from `usePrompts.activeByProject[target.pid]?.derived_from ?? null` (only when target.kind === 'schema'). For target.kind === 'version', look up the version blob's `derived_from.prompt_id` — but the existing flow doesn't fetch version blobs in this component. Keep version-target lineage as `null` for now (the `versions/v{N}.json` `derived_from` field exists from M9.1, but threading it through is M9.6 polish).

Patch:

```typescript
// At top of file, add:
import { usePrompts } from '../../stores/prompts'

// Inside the component, after `activeVersionId`:
const activePrompt = usePrompts(s => (target ? s.activeByProject[target.pid] : undefined))
const loadPrompts = usePrompts(s => s.load)
useEffect(() => {
  if (target && target.kind === 'schema') void loadPrompts(target.pid)
}, [target, loadPrompts])
const derivedFrom = target?.kind === 'schema' ? (activePrompt?.derived_from ?? null) : null

// And in the JSX:
<QuickLookHeader
  target={target}
  activeVersionId={activeVersionId}
  derivedFrom={derivedFrom}
  onClose={close}
/>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test -- QuickLook`
Expected: PASS — `QuickLookHeader`, `FieldsTab`, `RawJsonTab`, `SchemaQuickLook` tests all green.

Then full suite: `cd frontend && npm test`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/QuickLook/QuickLookHeader.tsx frontend/src/components/QuickLook/SchemaQuickLook.tsx frontend/tests/unit/QuickLook/
git commit -m "feat(m9.2): Quick-look lineage row binds real derived_from (active prompt)"
```

---

## Task 13: Vocabulary copy updates

**Files:**
- Modify: `frontend/src/components/Shell/HelpPopover.tsx` (any `schema.json` references in help copy)
- Modify: `frontend/src/components/QuickLook/SchemaQuickLook.tsx` (footer text references "schema")
- Modify: any other user-facing copy strings — search with grep

Per CLAUDE.md "task-type-agnostic UI vocabulary": chrome (buttons, slash menu, kind chips) keeps generic verbs. **Content / help text** is where we update extraction-specific wording to "Prompt" / "提示词".

- [ ] **Step 1: Inventory user-facing copy references**

Run: `grep -rn "schema\.json\|the schema" frontend/src/ | grep -v "\.test\."`

Each match falls into one of two buckets:
- **Identifier / API path / type name** (e.g. `kind: 'schema'`, `useSchema`, `/schema/raw`) — KEEP as-is. These are internal symbols, not user copy.
- **User-visible string** — REPLACE per the rules below.

- [ ] **Step 2: Apply targeted edits**

In `frontend/src/components/Shell/HelpPopover.tsx`, find and replace:
```
Drop documents into a folder. The agent reads them, derives a <code>schema.json</code>,
```
→
```
Drop documents into a folder. The agent reads them, derives a <code>prompt</code>,
```

In `frontend/src/components/QuickLook/SchemaQuickLook.tsx`, find:
```
description goes into the prompt at publish time. review notes (per-doc) feed
AutoResearch only — they propose description tweaks but never become prompt.
```
This text uses "the prompt" generically — no change needed.

If any other user-facing string uses "schema.json" or "the schema" in a phrase the user reads (e.g. empty-state copy, tooltips, error messages), replace with "prompt" / 中文 "提示词". Leave internal identifiers untouched.

- [ ] **Step 3: Update or extend tests**

If any test asserts a string that just changed, update the assertion. The two main tests to check:
- `frontend/tests/unit/Shell/HelpPopover.test.tsx` (if exists)
- Any e2e test that screenshots the help popover

Run: `grep -rn "schema\.json" frontend/tests/ | grep -v node_modules`
Update assertions where needed.

- [ ] **Step 4: Run full frontend suite**

Run: `cd frontend && npm test`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Shell/HelpPopover.tsx frontend/tests/unit/
git commit -m "docs(m9.2): user-facing copy — schema.json → prompt (chrome verbs unchanged)"
```

---

## Task 14: Full regression + live verify

**Files:**
- Run all tests
- Manually verify the dev server end-to-end

- [ ] **Step 1: Backend full suite**

Run: `cd backend && uv run pytest -v 2>&1 | tail -30`
Expected: 404 (from M9.1) + roughly 30–40 new tests passing, 0 failures.

If any unexpected failures, investigate. Common pitfalls:
- A test that seeds `schema.json` directly and expects `read_schema` to read it — should now go through `migrate_project_if_needed` (auto). If it fails, the seed is missing `project.json`.
- A test that asserts the exact list of `_EMERGE_TOOL_NAMES` — update the expected set.

- [ ] **Step 2: Frontend full suite**

Run: `cd frontend && npm test`
Expected: All pass.

- [ ] **Step 3: Start the dev server and live verify**

Run in two terminals:
1. `cd backend && uv run uvicorn app.main:app --reload --port 8000`
2. `cd frontend && npm run dev`

Open `http://localhost:5173` in a browser and:
- [ ] Pick an existing project. FSSpine should show `prompts/` and `models/` groups (closed by default). Click each to expand. The active prompt + active model should render with ⭐.
- [ ] ContextSurface right-rail should show two cards: `Prompt: pr_baseline` and `Model: Default (or whatever label)`. Field count + provider_model_id render.
- [ ] Click `Prompt: pr_baseline` card header → Quick-look sheet opens. Header reads `prompts/active`. Lineage row reads `derived from: —` (for an unmigrated baseline) or `derived from: pr_baseline` (for a fresh project that went through M9.1 migration with no parent).
- [ ] Type in chat: "show me my prompts" — the agent should call `list_prompts` and reply with the list. Watch the SSE stream's `tool_call` event to confirm the tool name is `mcp__emerge_tools__list_prompts`.
- [ ] Type in chat: "create a model variant called Sonnet using claude-sonnet-4-6" — the agent should call `create_model` then maybe `switch_active_model`. Refresh ContextSurface → Model card label updates.
- [ ] Pick a **legacy** (pre-M9.1) project on disk. First load should silently migrate. The Quick-look + ContextSurface should render identically to a fresh project.

If any UI step fails, fix and re-test before committing. Note failures inline if user wants them deferred.

- [ ] **Step 4: Commit dev-verify notes (optional)**

If you took screenshots (`docs/screenshots/2026-05-12-m9-2-*.png`) or noted any UX papercut for follow-up, commit them here:

```bash
# Only if there are new artifacts
git add docs/screenshots/
git commit -m "docs(m9.2): live-verify screenshots"
```

If no artifacts, skip this step.

---

## Task 15: ROADMAP closeout

**Files:**
- Modify: `docs/superpowers/plans/ROADMAP.md`

- [ ] **Step 1: Flip M9.1 to shipped + add M9.2**

Edit the M9.x table area. Change M9.1's row from "🚧 in progress" to "✅ shipped" with the commit range (find it via `git log --oneline 4cf76a5..6fe9ae4`). Add an M9.2 row:

```
| **M9.1** — data model migration (prompt/model axes on disk, lazy migration, write_schema thin wrapper; backend-only) | `2026-05-12-m9-1-data-model-migration.md` | ✅ shipped | `4cf76a5..6fe9ae4` (13 task commits; T11 fixed 4 latent direct-schema-reads in score/runner/eval/accept-candidate) |
| **M9.2** — prompt/model axis tools + UI (MCP tools + HTTP endpoints + FSSpine + ContextSurface; backend + frontend) | `2026-05-12-m9-2-axis-tools-and-ui.md` | 🚧 in progress | — |
```

Replace `🚧 in progress | —` with `✅ shipped | <commit-range>` once M9.2 finishes (at the end of the plan's execution, before this commit).

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/ROADMAP.md
git commit -m "docs(roadmap): M9.1 shipped; M9.2 axis tools + UI shipped"
```

---

## Self-review

Spec coverage cross-check:

| Spec section | Plan task(s) | Notes |
|---|---|---|
| §3.1 prompt-axis tools (`write_prompt`, `create_prompt`, `switch_active_prompt`, `list_prompts`, `delete_prompt`) | T1 Python + T4 MCP | `import_prompt` deferred to M9.5 (spec §3.4) |
| §3.2 model-axis tools (`write_model`, `create_model`, `switch_active_model`, `list_models`, `delete_model`) | T2 Python (write/create already exist from M9.1) + T5 MCP | Complete |
| §3.3 experiment tools | — | Out of scope; M9.3 |
| §3.4 fork_project | — | Out of scope; M9.5 |
| §6.1 publish fast-path 0 改动 | — (no task touches publish) | Verified — no task modifies `freeze_version` / `/v1/*` routes |
| §7.1 FSSpine prompts/ + models/ + experiments/ groups | T10 | experiments/ row deferred to M9.3 |
| §7.2 Quick-look lineage slot binding | T12 | `derived_from` real value rendered |
| §7.3 ContextSurface card splits | T11 | Single schema section → Prompt card + Model card |
| §7.4 Review-mode multi-tab | — | M9.3 |
| §8.4 write_schema compat wrapper | (kept from M9.1) | Unchanged; agent SKILL T8 documents the migration to write_prompt |
| Vocabulary "Schema" → "Prompt" / 提示词 | T13 | Chrome verbs (CLAUDE.md task-type-agnostic) untouched |
| `t_contract_diff` M9.1 bug | T3 | Fixed via `read_schema` |

Placeholder scan: no TBD / TODO / "implement later" / "add appropriate error handling" found.

Type consistency:
- `PromptVariant` field names match across backend (T1, T6) and frontend (`ActivePrompt` interface in T9)
- `ModelConfig` field names match across backend (T2, T7) and frontend (`ActiveModel` interface in T9)
- `usePrompts.activeByProject[pid]?.derived_from` matches `QuickLookHeader.derivedFrom` prop in T12
- `list_prompts` returns `[{prompt_id, label, derived_from, is_active, created_at, updated_at}]` consistently in T4 MCP tool, T6 HTTP endpoint, T9 store, T10 FSSpine
- `_EMERGE_TOOL_NAMES` updated in both T4 and T5 with no overlap

No spec gap unaccounted for within M9.2 scope. Out-of-scope items are tagged with their target milestone in the scope boundary table at top.

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-05-12-m9-2-axis-tools-and-ui.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks, fast iteration. Best for this plan because tasks 1–8 are mostly mechanical and tasks 9–13 each touch one component file independently.
2. **Inline Execution** — batch through with checkpoints; better if you want to read every diff before committing.

Per memory `feedback_default_execution_mode.md` (always subagent-driven after writing-plans; don't ask), default to subagent-driven in a new session.
