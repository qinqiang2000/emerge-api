# M9.4 — Cross-project fork + import_prompt

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ship two cross-project clone-at-time tools — `fork_project(src_pid, name, include_docs)` clones a project's prompt/model setup into a fresh `pid`; `import_prompt(src_pid, src_prompt_id, into_pid, new_label?)` clones one prompt file into an existing project. Both produce independent disk state with `derived_from` lineage; neither creates a live link.

**Architecture:** mostly backend. New tool functions in `app/tools/fork.py` (fork) and `app/tools/prompt.py` (import) compose existing helpers (`atomic_write_json`, `migrate_project_if_needed`, `project_lock`). Two thin HTTP routes provide an e2e drive surface. Two MCP wrappers expose the tools to the agent. Skill markdown gains a "Cross-project clone" section. Frontend change is a one-file cross-store refresh wiring (`useChat.handleToolResult` for the two new tool names) — no new UI surface; fork & import are chat-mediated.

**Tech Stack:** FastAPI · `claude_agent_sdk` · pydantic v2 · pytest · `shutil` / `os.link` for the actual clone ops. Uses real PDF samples under `/Users/qinqiang02/job/产品/文档AI/海外发票样本/荣耀_金蝶发票测试样例_1.20/英德法V1/` for the live dogfood (spec §4.1 scenario).

---

## Disk-layout decision matrix (fork_project)

The spec (§3.4) says "不拷 chats / _keys / predictions/_draft / reviewed (除非 user 显式要)" but doesn't pin down `experiments/`, `versions/`, `metrics/`, `jobs/`, autoresearch staging dirs. Decisions for this plan (use a copy **whitelist** — SSU; small explicit list beats long exclusion list):

| Subdir / file | Action | Reason |
|---|---|---|
| `project.json` | **copy + rewrite** | new pid; new name (= `name` arg); `active_version_id` reset to `None`; preserve `active_prompt_id`/`active_model_id`/`autoresearch_proposer_model`/`extract_model`/`extract_params` |
| `prompts/*.json` (named variants) | **copy** | the whole point — fork starts from src's prompt set; original `prompt_id`s preserved; `derived_from` chains stay valid intra-project |
| `prompts/_candidate/` | skip | autoresearch staging is session-bound to the src project; cloning mid-run is meaningless |
| `models/*.json` | **copy** | model configs are cheap and the fork user intent is "same setup, new domain" |
| `experiments/` | skip | per-doc extracts depend on docs (not copied); meta-only copy would dangle. User re-creates experiments fresh in the new project |
| `versions/` (incl `v{N}.json`, `_candidate/`) | skip | each project has its own publish lineage starting at v1; fork lineage is recorded in `versions/v{N}.derived_from` audit field (spec §6.1) when the fork later publishes |
| `predictions/_draft/` | skip | per spec §3.4 |
| `reviewed/` | skip | ground truth tied to source docs which aren't copied (this milestone defers the spec's "除非 user 显式要" opt-in; raise as follow-up if user demand surfaces) |
| `docs/` | skip default; **hardlink-or-copy** when `include_docs=True` | per spec §3.4; per-file `os.link` with `shutil.copy2` fallback on `OSError` (cross-device, permission, etc) |
| `chats/` | skip | conversation history is personal/session state; never crosses projects (chat redactor would also leak between forks otherwise) |
| `metrics/` | skip | depends on reviewed eval; meaningless without reviewed |
| `jobs/` | skip | in-flight job logs are tied to src project session |
| legacy `schema.json` / `global_notes.md` | skip | lazy migration runs on src before fork; post-migration these are gone (M9.1 migrate script keeps them as dead files for one milestone, but a *forked* project shouldn't carry that transition cruft) |
| `_keys.json` (workspace-global) | skip | hard rule — keys never fork |

`include_docs=True` strategy: `for f in src/docs: try os.link(f, dst); except OSError: shutil.copy2(f, dst)`. Both `.pdf` and `.meta.json` siblings hardlink fine — `.meta.json` is immutable post-upload.

---

## File map

**Create:**
- `backend/app/tools/fork.py` — `fork_project()` (kept separate from `projects.py` because it composes prompt + model reads and is long enough to be its own unit; `projects.py` stays focused on create/list/update)
- `backend/tests/unit/test_tool_fork.py`
- `backend/tests/unit/test_tool_import_prompt.py`
- `backend/tests/integration/test_routes_fork_and_import.py`
- `docs/screenshots/2026-05-14-m9-4-uk-invoice-fork.png` (created by T7 dogfood; just a placeholder mention here)

**Modify:**
- `backend/app/tools/prompt.py` — append `import_prompt()` function (alongside `create_prompt`)
- `backend/app/api/routes/projects.py` — add `POST /lab/projects/fork`
- `backend/app/api/routes/prompts.py` — add `POST /lab/projects/{pid}/prompts/import`
- `backend/app/tools/__init__.py` — register `t_fork_project` + `t_import_prompt`; append both names to `_EMERGE_TOOL_NAMES`
- `backend/app/skills/emerge_extractor.md` — add "Cross-project clone (fork & import)" section + risk-gate entries
- `frontend/src/stores/chat.ts` — `handleToolResult` two new tool-name branches (`fork_project` → `useProjects.refresh()`; `import_prompt` → `usePrompts.invalidate/load(projectId)`)
- `docs/superpowers/plans/ROADMAP.md` — append M9.4 row + "what each milestone delivers"
- `docs/design-decisions.md` — append M9.4 entry (closeout)

---

## Task list

### Task 1: `fork_project` function — whitelist-driven directory clone

**Files:**
- Create: `backend/app/tools/fork.py`
- Create: `backend/tests/unit/test_tool_fork.py`

- [ ] **Step 1: Write failing test — fork copies prompts + models + rewrites project.json**

Create `backend/tests/unit/test_tool_fork.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.tools.fork import fork_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    docs_dir,
    model_path,
    models_dir,
    project_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_src(workspace: Path, src_pid: str) -> None:
    """A migrated source project: project.json + 2 prompts + 2 models +
    one stray subdir that should NOT be copied."""
    pdir = workspace / src_pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    models_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    docs_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    (pdir / "chats").mkdir(exist_ok=True)
    (pdir / "predictions" / "_draft").mkdir(parents=True, exist_ok=True)
    (pdir / "reviewed").mkdir(exist_ok=True)
    (pdir / "experiments" / "ex_foo").mkdir(parents=True, exist_ok=True)
    (pdir / "versions").mkdir(exist_ok=True)
    (pdir / "metrics").mkdir(exist_ok=True)

    atomic_write_json(project_json_path(workspace, src_pid), {
        "name": "us-invoice",
        "project_type": "extraction",
        "created_at": _now(),
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": "v3",
        "extract_model": "gemini-2.5-flash",
        "extract_params": {"temperature": 0.0},
    })
    for pid_name in ("pr_baseline", "pr_variant"):
        atomic_write_json(prompt_path(workspace, src_pid, pid_name), {
            "prompt_id": pid_name,
            "label": f"L({pid_name})",
            "schema": [],
            "global_notes": "src notes",
            "derived_from": None,
            "created_at": _now(),
            "updated_at": _now(),
        })
    for mid_name in ("m_default", "m_alt"):
        atomic_write_json(model_path(workspace, src_pid, mid_name), {
            "model_id": mid_name,
            "label": f"M({mid_name})",
            "provider": "google",
            "provider_model_id": "gemini-2.5-flash",
            "params": {"temperature": 0.0},
            "created_at": _now(),
        })
    # stray content that must NOT be copied
    (pdir / "chats" / "c_abc.jsonl").write_text("ignored")
    (pdir / "predictions" / "_draft" / "d_x.json").write_text("{}")
    (pdir / "reviewed" / "d_x.json").write_text("{}")
    (pdir / "experiments" / "ex_foo" / "meta.json").write_text("{}")
    (pdir / "versions" / "v3.json").write_text("{}")
    (pdir / "metrics" / "eval_1.json").write_text("{}")


async def test_fork_copies_prompts_models_rewrites_project_json(workspace: Path) -> None:
    src_pid = "p_src123456789"  # NOTE: doesn't match safe_project_id regex — that's fine for the tool unit; routes apply safety.
    _seed_src(workspace, src_pid)

    new_pid = await fork_project(workspace, src_pid=src_pid, name="uk-invoice")

    # New pid format
    assert new_pid.startswith("p_") and new_pid != src_pid
    new_dir = project_dir(workspace, new_pid)

    # Whitelist: project.json + prompts/ + models/
    new_blob = json.loads(project_json_path(workspace, new_pid).read_text())
    assert new_blob["name"] == "uk-invoice"
    assert new_blob["active_version_id"] is None
    assert new_blob["active_prompt_id"] == "pr_baseline"
    assert new_blob["active_model_id"] == "m_default"
    assert "created_at" in new_blob

    assert prompt_path(workspace, new_pid, "pr_baseline").exists()
    assert prompt_path(workspace, new_pid, "pr_variant").exists()
    assert model_path(workspace, new_pid, "m_default").exists()
    assert model_path(workspace, new_pid, "m_alt").exists()

    # Blacklist: nothing else copied
    assert not (new_dir / "chats").exists()
    assert not (new_dir / "predictions").exists()
    assert not (new_dir / "reviewed").exists()
    assert not (new_dir / "experiments").exists()
    assert not (new_dir / "versions").exists()
    assert not (new_dir / "metrics").exists()
    # docs/ is created (empty) for the new project even without include_docs
    assert (new_dir / "docs").exists()
    assert list((new_dir / "docs").iterdir()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_tool_fork.py -v`
Expected: FAIL with `ModuleNotFoundError: app.tools.fork`

- [ ] **Step 3: Create `backend/app/tools/fork.py` with the whitelist implementation**

```python
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_project_id
from app.workspace.lock import project_lock
from app.workspace.paths import (
    chats_dir,
    docs_dir,
    model_path,
    models_dir,
    predictions_draft_dir,
    project_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
    versions_dir,
)


class ForkSourceNotFoundError(Exception):
    """Raised when fork_project is called with a src_pid that has no project.json."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def fork_project(
    workspace: Path,
    *,
    src_pid: str,
    name: str,
    include_docs: bool = False,
) -> str:
    """Clone-at-time fork of src_pid into a fresh project_id.

    Whitelist of what gets cloned:
      - project.json   (rewritten: new pid, new name, active_version_id=None)
      - prompts/*.json (all named variants; _candidate/ skipped)
      - models/*.json
      - docs/*         (skipped unless include_docs=True; then hardlink+fallback)

    Everything else (chats, reviewed, predictions/_draft, experiments, versions,
    metrics, jobs, legacy schema.json/global_notes.md) is deliberately not
    cloned — see docs/superpowers/plans/2026-05-14-m9-4-fork-and-import.md
    decision matrix.
    """
    from app.workspace.migrate import migrate_project_if_needed

    src_pj = project_json_path(workspace, src_pid)
    if not src_pj.exists():
        raise ForkSourceNotFoundError(f"src project {src_pid} not found")

    # Ensure src is on current layout before we read its prompts/models dirs.
    await migrate_project_if_needed(workspace, src_pid)

    new_pid = new_project_id()
    new_dir = project_dir(workspace, new_pid)
    new_dir.mkdir(parents=True, exist_ok=False)

    async with project_lock(workspace, new_pid):
        # Bootstrap only the subdirs we populate or care about post-fork.
        # predictions/_draft, versions/, chats/ are created lazily by their
        # writers — every read path guards .exists() — so we don't pre-mkdir
        # them here. (Matches the test contract.)
        docs_dir(workspace, new_pid).mkdir(parents=True, exist_ok=True)
        prompts_dir(workspace, new_pid).mkdir(parents=True, exist_ok=True)
        models_dir(workspace, new_pid).mkdir(parents=True, exist_ok=True)

        # 1. project.json
        src_blob = json.loads(src_pj.read_text(encoding="utf-8"))
        new_blob = {
            "name": name,
            "project_type": src_blob.get("project_type", "extraction"),
            "created_at": _now_iso(),
            "active_prompt_id": src_blob.get("active_prompt_id"),
            "active_model_id": src_blob.get("active_model_id"),
            "active_version_id": None,  # fresh publish lineage in the fork
            "autoresearch_proposer_model": src_blob.get("autoresearch_proposer_model"),
            "extract_model": src_blob.get("extract_model"),
            "extract_params": src_blob.get("extract_params"),
        }
        atomic_write_json(project_json_path(workspace, new_pid), new_blob)

        # 2. prompts/*.json (top-level files only — _candidate/ subdir is skipped)
        src_prompts = prompts_dir(workspace, src_pid)
        if src_prompts.exists():
            for f in src_prompts.iterdir():
                if f.is_file() and f.name.endswith(".json"):
                    atomic_write_json(
                        prompt_path(workspace, new_pid, f.stem),
                        json.loads(f.read_text(encoding="utf-8")),
                    )

        # 3. models/*.json
        src_models = models_dir(workspace, src_pid)
        if src_models.exists():
            for f in src_models.iterdir():
                if f.is_file() and f.name.endswith(".json"):
                    atomic_write_json(
                        model_path(workspace, new_pid, f.stem),
                        json.loads(f.read_text(encoding="utf-8")),
                    )

        # 4. docs/ (optional)
        if include_docs:
            src_docs = docs_dir(workspace, src_pid)
            dst_docs = docs_dir(workspace, new_pid)
            if src_docs.exists():
                for f in src_docs.iterdir():
                    if not f.is_file():
                        continue
                    target = dst_docs / f.name
                    try:
                        target.hardlink_to(f)
                    except OSError:
                        shutil.copy2(f, target)

    return new_pid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_tool_fork.py -v`
Expected: PASS

- [ ] **Step 5: Write second failing test — `include_docs=True` hardlinks (or copies) doc files**

Append to `backend/tests/unit/test_tool_fork.py`:

```python
async def test_fork_include_docs_clones_doc_files(workspace: Path) -> None:
    src_pid = "p_src123456789"
    _seed_src(workspace, src_pid)
    # Seed two doc files
    src_docs = docs_dir(workspace, src_pid)
    (src_docs / "d_aaa.pdf").write_bytes(b"PDFCONTENT")
    (src_docs / "d_aaa.meta.json").write_text('{"original_filename": "a.pdf"}')

    new_pid = await fork_project(
        workspace, src_pid=src_pid, name="uk-invoice", include_docs=True,
    )

    new_docs = docs_dir(workspace, new_pid)
    assert (new_docs / "d_aaa.pdf").read_bytes() == b"PDFCONTENT"
    assert json.loads((new_docs / "d_aaa.meta.json").read_text())["original_filename"] == "a.pdf"


async def test_fork_default_skips_docs(workspace: Path) -> None:
    src_pid = "p_src123456789"
    _seed_src(workspace, src_pid)
    (docs_dir(workspace, src_pid) / "d_aaa.pdf").write_bytes(b"X")

    new_pid = await fork_project(workspace, src_pid=src_pid, name="uk-invoice")
    assert list(docs_dir(workspace, new_pid).iterdir()) == []


async def test_fork_missing_src_raises(workspace: Path) -> None:
    from app.tools.fork import ForkSourceNotFoundError
    with pytest.raises(ForkSourceNotFoundError):
        await fork_project(workspace, src_pid="p_doesnotexist", name="x")
```

- [ ] **Step 6: Run all fork tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_fork.py -v`
Expected: 4 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/tools/fork.py backend/tests/unit/test_tool_fork.py
git commit -m "feat(m9.4): fork_project clones project.json + prompts + models (+ optional docs)"
```

---

### Task 2: `import_prompt` function — cross-project single-prompt clone

**Files:**
- Modify: `backend/app/tools/prompt.py` (append `import_prompt` at end of file)
- Create: `backend/tests/unit/test_tool_import_prompt.py`

- [ ] **Step 1: Write failing test — import copies schema/global_notes, sets cross-project derived_from**

Create `backend/tests/unit/test_tool_import_prompt.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.tools.prompt import (
    PromptNotFoundError,
    import_prompt,
    read_prompt,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    project_json_path,
    prompt_path,
    prompts_dir,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed(workspace: Path, pid: str, prompts: dict[str, dict]) -> None:
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "name": pid,
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": None,
    })
    for prompt_id, fields_blob in prompts.items():
        atomic_write_json(prompt_path(workspace, pid, prompt_id), {
            "prompt_id": prompt_id,
            "label": fields_blob.get("label", prompt_id),
            "schema": fields_blob.get("schema", []),
            "global_notes": fields_blob.get("global_notes", ""),
            "derived_from": None,
            "created_at": _now(),
            "updated_at": _now(),
        })


async def test_import_prompt_copies_schema_and_notes(workspace: Path) -> None:
    src_pid = "p_src111111111"
    dst_pid = "p_dst222222222"
    _seed(workspace, src_pid, {
        "pr_baseline": {
            "label": "US baseline",
            "schema": [
                {"name": "invoice_no", "type": "string", "description": "d", "required": False},
            ],
            "global_notes": "us notes",
        },
    })
    _seed(workspace, dst_pid, {
        "pr_baseline": {"label": "dst baseline", "schema": []},
    })

    new_id = await import_prompt(
        workspace,
        src_pid=src_pid, src_prompt_id="pr_baseline",
        into_pid=dst_pid,
        new_label="from US",
    )

    # New id is freshly minted, not "pr_baseline" (would collide)
    assert new_id.startswith("pr_") and new_id != "pr_baseline"

    pv = await read_prompt(workspace, dst_pid, new_id)
    assert pv.label == "from US"
    assert pv.schema[0].name == "invoice_no"
    assert pv.global_notes == "us notes"
    assert pv.derived_from == f"{src_pid}/pr_baseline"
    assert pv.prompt_id == new_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_tool_import_prompt.py -v`
Expected: FAIL with `ImportError: cannot import name 'import_prompt'`

- [ ] **Step 3: Append `import_prompt` to `backend/app/tools/prompt.py`**

Append before the last line of `backend/app/tools/prompt.py`:

```python
async def import_prompt(
    workspace: Path,
    *,
    src_pid: str,
    src_prompt_id: str,
    into_pid: str,
    new_label: str | None = None,
) -> str:
    """Clone-at-time copy of a single prompt variant from src_pid to into_pid.

    - new prompt_id is freshly minted (never reuses src_prompt_id, to avoid
      collision with same-named prompts in dest)
    - schema + global_notes are copied verbatim
    - derived_from = f"{src_pid}/{src_prompt_id}" — purely informational lineage
      string; no live link
    - label defaults to src.label when new_label is None
    - autoresearch _candidate/ entries are never importable (out of scope of
      named variants; would be incoherent without the originating job context)
    """
    from app.workspace.ids import new_prompt_id
    from app.workspace.migrate import migrate_project_if_needed

    # Migrate both to current layout so legacy schema.json doesn't surprise us.
    await migrate_project_if_needed(workspace, src_pid)
    await migrate_project_if_needed(workspace, into_pid)

    src_path = prompt_path(workspace, src_pid, src_prompt_id)
    if not src_path.exists():
        raise PromptNotFoundError(
            f"source prompt {src_prompt_id} not found in project {src_pid}"
        )
    src = PromptVariant(**json.loads(src_path.read_text(encoding="utf-8")))

    dst_pj = project_json_path(workspace, into_pid)
    if not dst_pj.exists():
        raise PromptNotFoundError(
            f"destination project {into_pid} not found"
        )

    async with project_lock(workspace, into_pid):
        new_id = new_prompt_id()
        now = _now_iso()
        pv = PromptVariant(
            prompt_id=new_id,
            label=new_label if new_label else src.label,
            schema=src.schema,
            global_notes=src.global_notes,
            derived_from=f"{src_pid}/{src_prompt_id}",
            created_at=now,
            updated_at=now,
        )
        prompts_dir(workspace, into_pid).mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            prompt_path(workspace, into_pid, new_id),
            pv.model_dump(mode="json"),
        )
    return new_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_tool_import_prompt.py::test_import_prompt_copies_schema_and_notes -v`
Expected: PASS

- [ ] **Step 5: Write three more failing tests — defaults + missing-source + missing-dest**

Append to `backend/tests/unit/test_tool_import_prompt.py`:

```python
async def test_import_prompt_label_defaults_to_src_label(workspace: Path) -> None:
    src_pid = "p_src111111111"
    dst_pid = "p_dst222222222"
    _seed(workspace, src_pid, {"pr_baseline": {"label": "US baseline"}})
    _seed(workspace, dst_pid, {"pr_baseline": {"label": "dst"}})

    new_id = await import_prompt(
        workspace,
        src_pid=src_pid, src_prompt_id="pr_baseline",
        into_pid=dst_pid,
    )
    pv = await read_prompt(workspace, dst_pid, new_id)
    assert pv.label == "US baseline"


async def test_import_prompt_missing_src_raises(workspace: Path) -> None:
    src_pid = "p_src111111111"
    dst_pid = "p_dst222222222"
    _seed(workspace, src_pid, {"pr_baseline": {}})
    _seed(workspace, dst_pid, {"pr_baseline": {}})
    with pytest.raises(PromptNotFoundError):
        await import_prompt(
            workspace,
            src_pid=src_pid, src_prompt_id="pr_does_not_exist",
            into_pid=dst_pid,
        )


async def test_import_prompt_missing_dest_raises(workspace: Path) -> None:
    src_pid = "p_src111111111"
    _seed(workspace, src_pid, {"pr_baseline": {}})
    with pytest.raises(PromptNotFoundError):
        await import_prompt(
            workspace,
            src_pid=src_pid, src_prompt_id="pr_baseline",
            into_pid="p_doesnotexist",
        )
```

- [ ] **Step 6: Run all import_prompt tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_import_prompt.py -v`
Expected: 4 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/tools/prompt.py backend/tests/unit/test_tool_import_prompt.py
git commit -m "feat(m9.4): import_prompt clones a single prompt across projects with derived_from lineage"
```

---

### Task 3: HTTP routes for fork + import

**Files:**
- Modify: `backend/app/api/routes/projects.py`
- Modify: `backend/app/api/routes/prompts.py`
- Create: `backend/tests/integration/test_routes_fork_and_import.py`

- [ ] **Step 1: Write failing test — POST /lab/projects/fork**

Create `backend/tests/integration/test_routes_fork_and_import.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    model_path,
    models_dir,
    project_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_source(workspace: Path) -> str:
    src_pid = "p_src123456789"
    pdir = workspace / src_pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    models_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, src_pid), {
        "name": "us-invoice",
        "project_type": "extraction",
        "created_at": _now(),
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": "v3",
    })
    atomic_write_json(prompt_path(workspace, src_pid, "pr_baseline"), {
        "prompt_id": "pr_baseline", "label": "US baseline",
        "schema": [{"name": "invoice_no", "type": "string", "description": "d", "required": False}],
        "global_notes": "us notes", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, src_pid, "m_default"), {
        "model_id": "m_default", "label": "Default",
        "provider": "google", "provider_model_id": "gemini-2.5-flash",
        "params": {"temperature": 0.0}, "created_at": _now(),
    })
    return src_pid


def test_fork_route_creates_new_project(workspace: Path) -> None:
    src_pid = _seed_source(workspace)
    client = TestClient(app)
    r = client.post(
        "/lab/projects/fork",
        json={"src_pid": src_pid, "name": "uk-invoice"},
    )
    assert r.status_code == 200, r.text
    new_pid = r.json()["project_id"]
    assert new_pid.startswith("p_") and new_pid != src_pid

    new_blob = json.loads(project_json_path(workspace, new_pid).read_text())
    assert new_blob["name"] == "uk-invoice"
    assert new_blob["active_version_id"] is None
    assert prompt_path(workspace, new_pid, "pr_baseline").exists()
    assert model_path(workspace, new_pid, "m_default").exists()


def test_fork_route_404_on_missing_source(workspace: Path) -> None:
    client = TestClient(app)
    r = client.post(
        "/lab/projects/fork",
        json={"src_pid": "p_doesnotexist", "name": "x"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "project_not_found"


def test_fork_route_rejects_invalid_src_pid(workspace: Path) -> None:
    client = TestClient(app)
    r = client.post(
        "/lab/projects/fork",
        json={"src_pid": "../etc/passwd", "name": "x"},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run failing tests**

Run: `cd backend && uv run pytest tests/integration/test_routes_fork_and_import.py -v`
Expected: FAIL — 404 on the fork URL (route not registered)

- [ ] **Step 3: Add `POST /lab/projects/fork` to `backend/app/api/routes/projects.py`**

Append to `backend/app/api/routes/projects.py`:

```python
from pydantic import BaseModel


class _ForkProjectBody(BaseModel):
    src_pid: str
    name: str
    include_docs: bool = False


@router.post("/lab/projects/fork")
async def post_fork_project(body: _ForkProjectBody) -> dict:
    safe_project_id(body.src_pid)
    settings = get_settings()
    from app.tools.fork import ForkSourceNotFoundError, fork_project

    try:
        new_pid = await fork_project(
            settings.workspace_root,
            src_pid=body.src_pid,
            name=body.name,
            include_docs=body.include_docs,
        )
    except ForkSourceNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return {"project_id": new_pid}
```

- [ ] **Step 4: Run fork-route tests**

Run: `cd backend && uv run pytest tests/integration/test_routes_fork_and_import.py::test_fork_route_creates_new_project tests/integration/test_routes_fork_and_import.py::test_fork_route_404_on_missing_source tests/integration/test_routes_fork_and_import.py::test_fork_route_rejects_invalid_src_pid -v`
Expected: 3 PASS

- [ ] **Step 5: Append failing test — POST .../prompts/import**

Append to `backend/tests/integration/test_routes_fork_and_import.py`:

```python
def test_import_prompt_route_clones_into_dest(workspace: Path) -> None:
    src_pid = _seed_source(workspace)
    dst_pid = "p_dst123456789"
    pdir = workspace / dst_pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, dst_pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, dst_pid), {
        "name": "b-eval", "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default", "active_version_id": None,
    })
    atomic_write_json(prompt_path(workspace, dst_pid, "pr_baseline"), {
        "prompt_id": "pr_baseline", "label": "dst", "schema": [],
        "global_notes": "", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })

    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{dst_pid}/prompts/import",
        json={
            "src_pid": src_pid,
            "src_prompt_id": "pr_baseline",
            "new_label": "from US",
        },
    )
    assert r.status_code == 200, r.text
    new_id = r.json()["prompt_id"]
    assert new_id.startswith("pr_") and new_id != "pr_baseline"

    imported = json.loads(prompt_path(workspace, dst_pid, new_id).read_text())
    assert imported["label"] == "from US"
    assert imported["derived_from"] == f"{src_pid}/pr_baseline"
    assert imported["schema"][0]["name"] == "invoice_no"


def test_import_prompt_route_404_on_missing_src_prompt(workspace: Path) -> None:
    src_pid = _seed_source(workspace)
    dst_pid = "p_dst123456789"
    pdir = workspace / dst_pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, dst_pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, dst_pid), {
        "name": "x", "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default", "active_version_id": None,
    })
    atomic_write_json(prompt_path(workspace, dst_pid, "pr_baseline"), {
        "prompt_id": "pr_baseline", "label": "x", "schema": [],
        "global_notes": "", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })

    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{dst_pid}/prompts/import",
        json={
            "src_pid": src_pid,
            "src_prompt_id": "pr_does_not_exist",
        },
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "prompt_not_found"
```

- [ ] **Step 6: Run failing import-route tests**

Run: `cd backend && uv run pytest tests/integration/test_routes_fork_and_import.py -v`
Expected: 2 new tests FAIL (404 on the import URL)

- [ ] **Step 7: Add `POST .../prompts/import` to `backend/app/api/routes/prompts.py`**

Append to `backend/app/api/routes/prompts.py`:

```python
from pydantic import BaseModel

from app.tools.prompt import import_prompt


class _ImportPromptBody(BaseModel):
    src_pid: str
    src_prompt_id: str
    new_label: str | None = None


@router.post("/lab/projects/{project_id}/prompts/import")
async def post_import_prompt(project_id: str, body: _ImportPromptBody) -> dict:
    workspace = _project_or_404(project_id)
    safe_project_id(body.src_pid)
    try:
        new_id = await import_prompt(
            workspace,
            src_pid=body.src_pid,
            src_prompt_id=body.src_prompt_id,
            into_pid=project_id,
            new_label=body.new_label,
        )
    except PromptNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "prompt_not_found"},
        )
    return {"prompt_id": new_id}
```

- [ ] **Step 8: Run all route tests**

Run: `cd backend && uv run pytest tests/integration/test_routes_fork_and_import.py -v`
Expected: 5 PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/api/routes/projects.py backend/app/api/routes/prompts.py backend/tests/integration/test_routes_fork_and_import.py
git commit -m "feat(m9.4): HTTP routes — POST /lab/projects/fork + .../prompts/import"
```

---

### Task 4: MCP tool wrappers + tool-name registry

**Files:**
- Modify: `backend/app/tools/__init__.py`

- [ ] **Step 1: Write failing tool-registration test**

Append to `backend/tests/unit/test_tool_registration.py` (read it first to see the existing pattern — likely a list comparison):

```python
def test_fork_and_import_in_emerge_tool_names() -> None:
    from app.tools import _EMERGE_TOOL_NAMES
    assert "fork_project" in _EMERGE_TOOL_NAMES
    assert "import_prompt" in _EMERGE_TOOL_NAMES
```

- [ ] **Step 2: Run failing test**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py::test_fork_and_import_in_emerge_tool_names -v`
Expected: FAIL with AssertionError

- [ ] **Step 3: Add MCP wrappers to `backend/app/tools/__init__.py`**

Insert after the `t_delete_experiment` block (and before `t_extract_one`):

```python
    @tool(
        "fork_project",
        "Clone-at-time fork of an existing project. Copies project.json + "
        "prompts/ + models/ into a fresh project_id. Skips chats, reviewed, "
        "predictions/_draft, experiments, versions, metrics. Set include_docs=true "
        "to also hardlink docs/ files. Returns the new project_id.",
        {"src_pid": str, "name": str, "include_docs": bool},
    )
    async def t_fork_project(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.fork import fork_project as fork_project_impl
        new_pid = await fork_project_impl(
            workspace,
            src_pid=args["src_pid"],
            name=args["name"],
            include_docs=bool(args.get("include_docs", False)),
        )
        return {"content": [{"type": "text", "text": new_pid}]}

    @tool(
        "import_prompt",
        "Cross-project clone of a single prompt variant. Mints a fresh "
        "prompt_id in into_pid, copies schema + global_notes, sets "
        "derived_from='{src_pid}/{src_prompt_id}'. new_label defaults to "
        "the source prompt's label when empty.",
        {
            "src_pid": str, "src_prompt_id": str,
            "into_pid": str, "new_label": str,
        },
    )
    async def t_import_prompt(args: dict[str, Any]) -> dict[str, Any]:
        raw_label = args.get("new_label") or None  # "" -> None
        new_id = await prompt_mod.import_prompt(
            workspace,
            src_pid=args["src_pid"],
            src_prompt_id=args["src_prompt_id"],
            into_pid=args["into_pid"],
            new_label=raw_label,
        )
        return {"content": [{"type": "text", "text": new_id}]}
```

Add to the `tools=[...]` list (after `t_delete_experiment`):

```python
            t_fork_project,
            t_import_prompt,
```

Add to `_EMERGE_TOOL_NAMES` (after `"delete_experiment"`):

```python
    "fork_project", "import_prompt",
```

- [ ] **Step 4: Run registration test**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`
Expected: PASS (incl any pre-existing ones)

- [ ] **Step 5: Run all unit + integration tests as a regression sweep**

Run: `cd backend && uv run pytest tests/unit tests/integration -x -q`
Expected: PASS (only the new tests added, no regressions)

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/__init__.py backend/tests/unit/test_tool_registration.py
git commit -m "feat(m9.4): register fork_project + import_prompt MCP tools"
```

---

### Task 5: Frontend cross-store refresh wiring

**Files:**
- Modify: `frontend/src/stores/chat.ts` (specifically the `handleToolResult` function — extend two existing tool-branch checks)
- Modify: `frontend/src/stores/chat.test.ts` (if it exists; otherwise the live dogfood in T8 is the verification)

- [ ] **Step 1: Read the existing handleToolResult cross-store branches**

Run: `cd frontend && grep -n 'mcp__emerge_tools__' src/stores/chat.ts`
Note: This is a read step. Existing pattern: every mutating tool gets a branch that invalidates + loads the affected store. `fork_project` is shaped like `create_project` (creates a project → refresh project list); `import_prompt` is shaped like `create_prompt` (creates a prompt → invalidate + load prompts for the current project).

- [ ] **Step 2: Extend the `create_project` branch to include `fork_project`**

Find this block in `frontend/src/stores/chat.ts`:

```ts
    if (t === 'mcp__emerge_tools__create_project' || t === 'mcp__emerge_tools__freeze_version') {
      void useProjects.getState().refresh()
    }
```

Replace with:

```ts
    if (
      t === 'mcp__emerge_tools__create_project' ||
      t === 'mcp__emerge_tools__freeze_version' ||
      t === 'mcp__emerge_tools__fork_project'
    ) {
      void useProjects.getState().refresh()
    }
```

- [ ] **Step 3: Extend the prompt-mutation branch to include `import_prompt`**

Find this block:

```ts
    if (
      t === 'mcp__emerge_tools__write_prompt' ||
      t === 'mcp__emerge_tools__create_prompt' ||
      t === 'mcp__emerge_tools__switch_active_prompt' ||
      t === 'mcp__emerge_tools__delete_prompt'
    ) {
      useSchema.getState().invalidate(projectId)
      usePrompts.getState().invalidate(projectId)
      void usePrompts.getState().load(projectId)
    }
```

Replace with:

```ts
    if (
      t === 'mcp__emerge_tools__write_prompt' ||
      t === 'mcp__emerge_tools__create_prompt' ||
      t === 'mcp__emerge_tools__switch_active_prompt' ||
      t === 'mcp__emerge_tools__delete_prompt' ||
      t === 'mcp__emerge_tools__import_prompt'
    ) {
      useSchema.getState().invalidate(projectId)
      usePrompts.getState().invalidate(projectId)
      void usePrompts.getState().load(projectId)
    }
```

- [ ] **Step 4: Run the frontend type-check + tests**

Run:
```bash
cd frontend && npm run type-check 2>&1 | tail -5
cd frontend && npm test 2>&1 | tail -20
```
Expected: no new errors. If `chat.test.ts` exists and asserts a complete tool-name set, it may need a matching update — extend the asserted set if so.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/chat.ts
git commit -m "feat(m9.4): wire fork_project + import_prompt into cross-store refresh"
```

---

### Task 6: Skill markdown update — cross-project clone section + risk gates

**Files:**
- Modify: `backend/app/skills/emerge_extractor.md`

- [ ] **Step 1: Add "Cross-project clone (fork & import_prompt)" section before "Slash commands handled by this skill"**

Use Edit to insert the new section just before the `## Slash commands handled by this skill` line:

```markdown
## Cross-project clone (M9.4)

Two clone-at-time tools let a user reuse setup across projects without
creating any live link. Both are explicit user actions — NEVER fork or
import without confirmation:

- `fork_project(src_pid, name, include_docs=false)` — clones an entire
  project's prompt/model setup into a fresh `project_id`. Copies
  `project.json` (rewritten with the new name + reset `active_version_id`),
  all `prompts/*.json`, all `models/*.json`. Skips chats, reviewed,
  predictions/_draft, experiments, versions, metrics — those are
  project-bound. `include_docs=true` hardlinks every doc into the new
  project (cheap, but the user loses isolation: deleting a doc in src
  doesn't affect the fork's hardlink, but re-uploading the same doc_id
  in src diverges).
  Use when the user says "从 X 起跑新项目", "fork from X", "make a UK
  version of us-invoice".

- `import_prompt(src_pid, src_prompt_id, into_pid, new_label?)` — clones a
  single prompt variant from one project into another. Mints a fresh
  prompt_id (never reuses src_prompt_id — could collide). Sets
  `derived_from = "{src_pid}/{src_prompt_id}"` for lineage display.
  Use when the user has an existing project and wants to "试 X 项目的
  prompt 看看效果" without forking the whole project.

After an `import_prompt`, the typical workflow is:
`create_experiment(prompt_id=<imported>, model_id=active)` → user picks
a doc → `extract_with_experiment` → review the result in chat or in
the review tab strip (M9.3). If the imported prompt wins, the user
`promote_experiment`s it; otherwise `archive_experiment`.
```

Also append two new entries to the existing "Risk gates (ALWAYS confirm with user before invoking)" list (insert near other clone-shaped gates):

```markdown
- Forking a project (`fork_project`): always confirm — creates a new project
  with the same prompt/model setup. Cheap to delete but easy to confuse user
  about which pid they're working in afterwards. Confirm both `src_pid` and
  the new `name` before invoking.
- Importing a prompt (`import_prompt`): always confirm — clones a prompt
  from another project. Confirm `src_pid` + `src_prompt_id` so the user
  knows exactly what they're pulling in.
```

- [ ] **Step 2: Verify the skill markdown still parses (no syntax errors anywhere)**

Run: `cd backend && uv run python -c "from app.skills import emerge_extractor; print(len(emerge_extractor.__file__))"` 
(If skills are loaded via a different mechanism, this is just a smoke check that the file imports.) — if no `__init__` re-export, instead just:

```bash
cd backend && uv run pytest tests/unit/test_skills_loader.py -v
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/skills/emerge_extractor.md
git commit -m "docs(m9.4): emerge_extractor skill — cross-project clone section + risk gates"
```

---

### Task 7: e2e integration spec

**Files:**
- Create: `backend/tests/integration/test_lab_fork_and_import_e2e.py`

This test seeds its own source-project inline (no `e2e_seed.py` change needed; the playwright e2e seed is for the browser tests, not pytest integration).

- [ ] **Step 1: Write failing e2e spec — end-to-end fork via HTTP then import_prompt + list_prompts**

Create `backend/tests/integration/test_lab_fork_and_import_e2e.py`:

```python
"""End-to-end: fork an existing seeded project, import a prompt back into
the original, then create an experiment that references the imported
prompt — the full §4.1 + §4.2 scenario shapes from the spec."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    model_path,
    models_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_us_invoice(workspace: Path) -> str:
    """Mimic a small migrated us-invoice project — three prompt variants,
    two models, no docs."""
    src_pid = "p_us0000000001"
    pdir = workspace / src_pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    models_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, src_pid), {
        "name": "us-invoice",
        "project_type": "extraction",
        "created_at": _now(),
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": "v2",
    })
    for prompt_id, label, schema in (
        ("pr_baseline", "US baseline", [
            {"name": "invoice_no", "type": "string", "description": "", "required": False},
            {"name": "supplier_state", "type": "string", "description": "US state code", "required": False},
        ]),
        ("pr_compact", "compact descriptions", []),
        ("pr_supplier_hint", "supplier 右上角", []),
    ):
        atomic_write_json(prompt_path(workspace, src_pid, prompt_id), {
            "prompt_id": prompt_id, "label": label, "schema": schema,
            "global_notes": "us notes", "derived_from": None,
            "created_at": _now(), "updated_at": _now(),
        })
    for model_id, provider_model_id in (
        ("m_default", "gemini-2.5-flash"),
        ("m_gemma", "gemma-4-12b-it"),
    ):
        atomic_write_json(model_path(workspace, src_pid, model_id), {
            "model_id": model_id, "label": model_id,
            "provider": "google", "provider_model_id": provider_model_id,
            "params": {"temperature": 0.0}, "created_at": _now(),
        })
    return src_pid


def test_fork_then_import_then_experiment_pipeline(workspace: Path) -> None:
    src_pid = _seed_us_invoice(workspace)
    client = TestClient(app)

    # §4.1: fork into UK
    fork_resp = client.post(
        "/lab/projects/fork",
        json={"src_pid": src_pid, "name": "uk-invoice"},
    )
    assert fork_resp.status_code == 200, fork_resp.text
    uk_pid = fork_resp.json()["project_id"]

    # Forked project has the same three prompts and two models
    assert prompt_path(workspace, uk_pid, "pr_baseline").exists()
    assert prompt_path(workspace, uk_pid, "pr_supplier_hint").exists()
    assert model_path(workspace, uk_pid, "m_gemma").exists()
    uk_blob = json.loads(project_json_path(workspace, uk_pid).read_text())
    assert uk_blob["name"] == "uk-invoice"
    assert uk_blob["active_version_id"] is None

    # §4.2 shape: independently — import the UK baseline back into a third
    # project ("B vendor eval") to compare against the US baseline
    b_pid = "p_b00000000001"
    bdir = workspace / b_pid
    bdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, b_pid).mkdir(parents=True, exist_ok=True)
    models_dir(workspace, b_pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, b_pid), {
        "name": "b-eval", "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default", "active_version_id": None,
    })
    atomic_write_json(prompt_path(workspace, b_pid, "pr_baseline"), {
        "prompt_id": "pr_baseline", "label": "B baseline",
        "schema": [], "global_notes": "",
        "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, b_pid, "m_default"), {
        "model_id": "m_default", "label": "Default",
        "provider": "google", "provider_model_id": "gemini-2.5-flash",
        "params": {"temperature": 0.0}, "created_at": _now(),
    })

    # Import US baseline AND UK baseline into B
    r1 = client.post(
        f"/lab/projects/{b_pid}/prompts/import",
        json={
            "src_pid": src_pid, "src_prompt_id": "pr_baseline",
            "new_label": "from US",
        },
    )
    assert r1.status_code == 200, r1.text
    from_us_id = r1.json()["prompt_id"]

    r2 = client.post(
        f"/lab/projects/{b_pid}/prompts/import",
        json={
            "src_pid": uk_pid, "src_prompt_id": "pr_baseline",
            "new_label": "from UK",
        },
    )
    assert r2.status_code == 200, r2.text
    from_uk_id = r2.json()["prompt_id"]

    # Both imports landed with cross-project derived_from + fresh ids
    assert from_us_id != "pr_baseline" and from_uk_id != "pr_baseline"
    assert from_us_id != from_uk_id

    us_blob = json.loads(prompt_path(workspace, b_pid, from_us_id).read_text())
    assert us_blob["derived_from"] == f"{src_pid}/pr_baseline"
    uk_blob_imported = json.loads(prompt_path(workspace, b_pid, from_uk_id).read_text())
    assert uk_blob_imported["derived_from"] == f"{uk_pid}/pr_baseline"

    # Imported prompts visible via list_prompts route
    list_resp = client.get(f"/lab/projects/{b_pid}/prompts")
    assert list_resp.status_code == 200
    ids = {p["prompt_id"] for p in list_resp.json()}
    assert from_us_id in ids and from_uk_id in ids
```

- [ ] **Step 2: Run failing e2e test**

Run: `cd backend && uv run pytest tests/integration/test_lab_fork_and_import_e2e.py -v`
Expected: PASS already if T1–T4 landed cleanly; if it fails, fix the underlying tool/route — don't relax the test.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_lab_fork_and_import_e2e.py
git commit -m "test(m9.4): e2e fork → import_prompt → list_prompts pipeline (§4.1 + §4.2 shape)"
```

---

### Task 8: Live dogfood — UK invoice fork from us-invoice

**Files:** none modified by this task; produces a screenshot + design-decisions entry.

**Setup expectation:** a `us-invoice` project already exists in the live workspace (the existing M9.3 dogfood project). Real PDFs available at `/Users/qinqiang02/job/产品/文档AI/海外发票样本/荣耀_金蝶发票测试样例_1.20/英德法V1/` (GB-prefixed = UK, plus DE/FR samples).

- [ ] **Step 1: Start backend + frontend dev servers**

Run (separately, in two foreground shells the user starts):
```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

- [ ] **Step 2: Open the live us-invoice chat. In one chat turn, send:**

```
fork 一份当作 uk-invoice，从 us-invoice 起跑
```

Expected agent behavior: confirms src_pid + new name, calls `fork_project(src_pid="<p_us...>", name="uk-invoice", include_docs=false)`, prints the new `project_id`.

- [ ] **Step 3: Switch to the new uk-invoice project (left rail).**

Verify the FSSpine shows `prompts/`, `models/`, but empty `docs/`, empty `reviewed/`, empty `experiments/`, empty `versions/`. Verify `active_version_id` is null (project status badge → "draft" or "empty").

- [ ] **Step 4: Upload 3 UK invoices via drag-and-drop (e.g. GB02658589.PDF, GB10009789.PDF, plus a third GB-prefixed PDF from the sample folder).**

- [ ] **Step 5: In the chat, send:**

```
把 supplier_state 改成 county，VAT registration number 必填
```

Agent should call `write_prompt` against the active prompt (the cloned `pr_baseline`) with `allow_structural=true` after confirming. Verify the change is isolated to uk-invoice (read us-invoice's `prompts/pr_baseline.json` and confirm it still says `supplier_state`).

- [ ] **Step 6: Run `/extract` on the 3 UK docs, then `/review` and correct at least one doc.**

- [ ] **Step 7: Screenshot the final state and save under `docs/screenshots/2026-05-14-m9-4-uk-invoice-fork.png`.**

The screenshot must show: project rail listing both `us-invoice` and `uk-invoice`; the uk-invoice prompt has the updated `county` field; the right-rail prompt card shows `derived from: —` (because fork doesn't set prompt-level derived_from — that's an `import_prompt` thing; fork only changes the project, the prompts kept their original `derived_from=None`).

- [ ] **Step 8: If anything in steps 2–7 doesn't work end-to-end, file the gap as an entry in the design-decisions log and fix BEFORE proceeding. Common gaps to watch for:**
  - Agent re-emits markdown table of "fork result" — would mean a rendering-contract gap in the skill (T6); patch by adding a similar "no markdown table" instruction to T6's section.
  - `migrate_project_if_needed` not triggered on the freshly forked uk-invoice — would surface as a 500 on first chat turn; fix in the route layer or in `fork_project` itself.
  - Project rail doesn't show `uk-invoice` after the fork tool result arrives — would mean the T5 wiring missed; add `fork_project` to the `useProjects.refresh()` branch.
  - After import_prompt completes in chat, prompts/ list in right-rail / FSSpine doesn't refresh — same shape as above, on the `usePrompts.invalidate/load(projectId)` branch.

- [ ] **Step 9: Commit only the screenshot (no code in this task) and a one-line entry in design-decisions**

```bash
git add docs/screenshots/2026-05-14-m9-4-uk-invoice-fork.png docs/design-decisions.md
git commit -m "docs(m9.4): live-verify UK invoice fork from us-invoice"
```

---

### Task 9: ROADMAP + design-decisions closeout

**Files:**
- Modify: `docs/superpowers/plans/ROADMAP.md`
- Modify: `docs/design-decisions.md`

- [ ] **Step 1: Append M9.4 row to the status table in `docs/superpowers/plans/ROADMAP.md`**

Edit the status table — add a new row right after the M9.3 row:

```markdown
| **M9.4** — cross-project fork + import_prompt (clone-at-time, hard rule "no live link") | `2026-05-14-m9-4-fork-and-import.md` | ✅ shipped | `<RANGE>` (9 task commits) |
```

Replace `<RANGE>` with the actual commit range when shipping. Until then leave the column with `pending`.

- [ ] **Step 2: Append "What this milestone delivers" subsection in the same file (after the M9.3 subsection)**

```markdown
### M9.4 — cross-project fork + import_prompt

**Goal:** two clone-at-time tools — `fork_project(src_pid, name, include_docs)` produces an independent new project with the same `prompts/` + `models/` setup; `import_prompt(src_pid, src_prompt_id, into_pid, new_label?)` clones a single prompt variant into an existing project, stamping `derived_from = "{src_pid}/{src_prompt_id}"`. No live link in either tool — hard rule respected.

**Scope (see `2026-05-14-m9-4-fork-and-import.md`):**
- T1: `app/tools/fork.py::fork_project` — whitelist copy of `project.json` + `prompts/*.json` + `models/*.json`; optional hardlink-or-copy for `docs/`. Blacklist (chats / reviewed / predictions/_draft / experiments / versions / metrics / jobs / legacy schema.json) is implicit because we only copy the whitelist.
- T2: `app/tools/prompt.py::import_prompt` — mints a fresh `pr_*` id (never reuses src id), copies schema + global_notes, sets cross-project `derived_from`. `new_label` defaults to source label.
- T3: HTTP routes — `POST /lab/projects/fork` + `POST /lab/projects/{pid}/prompts/import`.
- T4: MCP wrappers + `_EMERGE_TOOL_NAMES` extension.
- T5: frontend `useChat.handleToolResult` — extends two existing branches: `create_project/freeze_version` adds `fork_project` (→ `useProjects.refresh()`); the prompt-mutation branch (`write_prompt/create_prompt/...`) adds `import_prompt` (→ `usePrompts.invalidate/load(projectId)`).
- T6: skill markdown — "Cross-project clone" section + two new risk-gate entries.
- T7: integration spec covering the §4.1 fork-then-customize and §4.2 multi-import-then-experiment shapes.
- T8: live dogfood — fork us-invoice → uk-invoice, upload 3 UK PDFs from the 海外发票 sample folder, edit supplier_state → county, verify isolation back to src.
- T9: this closeout.

**Decisions affirmed:**
- **Whitelist beats blacklist** for `fork_project`. A short explicit copy list (`project.json` + `prompts/` + `models/`) survives future disk-layout additions without growing exclusion rules.
- **`versions/` not copied.** Each project's publish lineage starts at v1. The spec §6.1 `derived_from` audit field on a future `freeze_version` in the fork records "this came from src_pid" without us having to ship pre-existing frozen versions in a project that hasn't published yet.
- **`experiments/` not copied.** Experiment per-doc extracts are tied to docs (which we don't copy); reviewed (which we don't copy) is the eval ground truth. Copying meta-only would leave dangling pointers. User re-creates experiments in the fork fresh.
- **`include_docs=True` uses hardlink with copy fallback** — cheapest "clone" of bytes; the new project owns its filesystem entries (deleting in src doesn't affect the fork's metadata). Caller risk: re-uploading the same doc_id in src diverges silently. Acceptable for now; document in skill copy.
- **`import_prompt` always mints a fresh id**, never reuses src_prompt_id — would collide when a user imports `pr_baseline` into a project that already has `pr_baseline`. Lineage is in `derived_from`, not in the id.

**Hard rules respected:**
- Forks are clone-at-time (no live link / no transclusion) — verified in T1/T2 tests.
- `_keys.json` never forks (it's workspace-global, not in either copy whitelist).
- `predictions/_draft/`, `chats/`, `reviewed/` never copied — protects audit / privacy / ground-truth boundaries.
- Publish fast-path zero changes — `versions/` skipped means no risk of frozen-version contamination across pids.
- Task-type-agnostic vocabulary — "fork" / "import" are generic verbs.

**Deferred / spun out:**
- Frontend dedicated "Fork project" / "Import prompt" button surfaces (currently chat-only; only the cross-store refresh wiring lands in T5) → follow-up; depends on user signal.
- `fork_project(..., include_reviewed=True)` opt-in flag from spec §3.4 — not implemented this milestone; raise as follow-up if user signals demand.
- Hardlink-aware "stale fork" warning (if src doc replaces a hardlinked file, fork still sees the old inode) → only relevant if hardlinking starts being default; defer.
```

- [ ] **Step 2.5: Update the M9.3 follow-ups list to mark this milestone shipped**

In `docs/superpowers/plans/ROADMAP.md`, edit the M9.3 "Deferred / spun out" line:
- Old: `- \`fork_project\` + \`import_prompt\` (cross-project clone) → **M9.4**.`
- New: `- ~~\`fork_project\` + \`import_prompt\` (cross-project clone)~~ → **closed by M9.4** (`2026-05-14-m9-4-fork-and-import.md`).`

- [ ] **Step 3: Append a dated entry to `docs/design-decisions.md` under the date 2026-05-14**

Mirror the existing M9.3 closeout shape (see the existing entries at the end of `design-decisions.md` from the M9.3 closeout for the precise format). Include:
- Plan file pointer
- Commit range (`<RANGE>` placeholder until known)
- Live-verify summary (UK-invoice fork from us-invoice; screenshot pointer)
- "Decisions affirmed" — whitelist beats blacklist; versions/ not copied; experiments/ not copied; include_docs hardlink-or-copy

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/ROADMAP.md docs/design-decisions.md
git commit -m "docs(m9.4): roadmap row + design-decisions closeout"
```

---

## Self-review

**Spec coverage check** (every locked spec item must map to a task):

| Spec item | Task |
|---|---|
| §1.4 cross-project clone-at-time fork (hard rule) | T1 |
| §3.4 `fork_project(src_pid, new_label, include_docs)` signature | T1 (renamed param `new_label` → `name` to match `create_project` style; both pass through to `project.json.name`) |
| §3.4 `import_prompt(src_pid, src_prompt_id, into_pid, new_label?)` signature | T2 |
| §3.4 skip chats / _keys / predictions/_draft / reviewed | T1 (whitelist) |
| §4.1 UK invoice fork scenario (uk-invoice from us-invoice) | T8 |
| §4.2 cross-project schema 借用试跑 (import_prompt × 3 + create_experiment) | T7 e2e |
| §5.3 import never touches `prompts/_candidate/` | T2 (function never walks _candidate/; docstring states this) |
| §10 YAGNI: cross-project axis direct reference (live link) NOT done | T1, T2 (both clone-at-time) |
| Hard rule: _keys.json never forks | T1 (workspace-global; whitelist excludes) |
| Hard rule: publish fast-path 0 改动 | T1 (versions/ skipped — see decision matrix) |
| Hard rule: experiment 永不 auto-promote | T1 (experiments/ skipped entirely from fork, so promote state can't cross projects) |
| Risk gates: fork + import confirm | T6 (skill copy adds two gate entries) |
| Cross-store refresh on tool result | T5 (frontend `handleToolResult` wiring) |

**Placeholder scan:** no `TBD` / `add appropriate` / `similar to Task N` / `fill in details` strings in the plan body. T7 step 8 lists *named* possible gaps with concrete fix hints (not generic "handle edge cases").

**Type consistency:**
- `fork_project(workspace, *, src_pid, name, include_docs)` — same signature in tool, route body model, MCP wrapper, and test.
- `import_prompt(workspace, *, src_pid, src_prompt_id, into_pid, new_label)` — same signature in tool, route body model, MCP wrapper, and test.
- `ForkSourceNotFoundError` exported from `app.tools.fork`; `PromptNotFoundError` re-used from `app.tools.prompt`.
- HTTP error envelope follows existing `{"error_code": "..."}` pattern (matches `routes/prompts.py` `prompt_not_found` and `routes/projects.py` `project_not_found` shape).

**One spec-vs-plan delta worth flagging:** the spec calls fork's project-name arg `new_label`, but our existing `create_project(name=...)` calls it `name` and writes it to `project.json.name`. The plan uses `name` for consistency with `create_project`. The MCP tool description still says "name" so the agent doesn't get confused.
