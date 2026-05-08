# M1 Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End-to-end case1 steps 1–3 — drag PDFs into chat with intent → agent creates project, derives schema, runs first extraction, streams results back. No review mode, no eval, no improve, no publish (those are M2/M3/M4).

**Architecture:** FastAPI backend hosting `claude_agent_sdk` chat service + ~9 atomic tools registered as MCP. Provider adapter calls Anthropic via httpx (separate from SDK). Project state lives entirely under `workspace/{project_id}/` as plain files. Vite + React 19 frontend with three-pane shell, SSE chat, drag-drop upload, tool-call folded cards. Anthropic palette tokens.

**Tech Stack:** Python 3.12 + FastAPI + `claude_agent_sdk` + httpx + pydantic v2 + uv + pytest + pytest-asyncio + PyMuPDF / Vite + React 19 + TypeScript + Zustand + Tailwind v3 + Radix + Lucide + vitest + Playwright.

**Spec reference:** `docs/superpowers/specs/2026-05-08-agent-native-design.md` §1–§8, §10, §11 (M1 row), §12.

---

## File structure

### Backend (`backend/`)

```
backend/
├── pyproject.toml
├── uv.lock                          # generated
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py                      # FastAPI app, lifespan, CORS, route mounting
│   ├── config.py                    # Settings (workspace path, provider keys, model defaults)
│   ├── workspace/
│   │   ├── __init__.py
│   │   ├── paths.py                 # path helpers for project/doc/schema/etc.
│   │   ├── atomic.py                # atomic_write_text, atomic_write_bytes, atomic_write_json
│   │   ├── lock.py                  # async flock context manager
│   │   └── ids.py                   # project_id / doc_id / chat_id / job_id generators
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── schema_field.py          # SchemaField pydantic model (single source of truth)
│   │   ├── envelope.py              # ErrorEnvelope, ToolResult
│   │   └── extraction.py            # ExtractionOutput { entities, _evidence }
│   ├── provider/
│   │   ├── __init__.py
│   │   ├── base.py                  # Provider Protocol + ContentBlock + ProviderResult
│   │   ├── retry.py                 # exponential backoff with jitter
│   │   └── anthropic.py             # Anthropic httpx adapter (vision + tool-use JSON)
│   ├── tools/
│   │   ├── __init__.py              # build_mcp_server() — registers all tools
│   │   ├── _result.py               # tool_ok / tool_err helpers wrapping ToolResult envelope
│   │   ├── projects.py              # create_project, list_projects, update_project
│   │   ├── docs.py                  # upload_doc (used by API not by agent), list_docs, read_doc, pdf_render_page
│   │   ├── schema.py                # read_schema, write_schema, derive_schema
│   │   └── extract.py               # extract_one, extract_batch (foreground for M1)
│   ├── skills/
│   │   ├── __init__.py              # load_skill(name) -> str
│   │   └── emerge_extractor.md      # SKILL.md content
│   ├── chat/
│   │   ├── __init__.py
│   │   ├── service.py               # ChatService wrapping ClaudeSDKClient
│   │   ├── stream.py                # SSE event encoder
│   │   └── log.py                   # append-only chats/{chat_id}.jsonl writer
│   └── api/
│       ├── __init__.py
│       └── routes/
│           ├── __init__.py
│           ├── chat.py              # POST /lab/chat (SSE)
│           ├── upload.py            # POST /lab/upload
│           ├── projects.py          # GET /lab/projects, GET /lab/projects/{pid}
│           └── docs.py              # GET /lab/projects/{pid}/docs/{did}/pages/{p}
└── tests/
    ├── __init__.py
    ├── conftest.py                  # tmp workspace fixture, stub provider, stub LLM
    ├── fixtures/
    │   └── invoice_sample.pdf       # tiny real PDF for tests
    ├── unit/
    │   ├── test_atomic.py
    │   ├── test_lock.py
    │   ├── test_ids.py
    │   ├── test_paths.py
    │   ├── test_provider_retry.py
    │   ├── test_provider_anthropic.py
    │   ├── test_schemas.py
    │   ├── test_tool_projects.py
    │   ├── test_tool_docs.py
    │   ├── test_tool_schema.py
    │   └── test_tool_extract.py
    └── integration/
        ├── __init__.py
        └── test_lab_chat_flow.py    # SSE happy path with stub LLM
```

### Frontend (`frontend/`)

```
frontend/
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
├── tsconfig.json
├── tsconfig.node.json
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx                       # 3-pane layout
│   ├── index.css                     # Tailwind base + token import
│   ├── theme/
│   │   └── tokens.css                # Anthropic palette CSS vars
│   ├── lib/
│   │   ├── sse.ts                    # SSE client
│   │   ├── api.ts                    # fetch wrappers
│   │   └── ids.ts                    # client-side id (uuidv4)
│   ├── stores/
│   │   ├── chat.ts                   # Zustand chat store
│   │   └── projects.ts               # Zustand projects store
│   ├── types/
│   │   ├── chat.ts                   # ChatEvent, ToolCall, etc.
│   │   └── project.ts
│   └── components/
│       ├── ProjectList/
│       │   ├── ProjectList.tsx
│       │   └── ProjectItem.tsx
│       ├── Chat/
│       │   ├── ChatPanel.tsx
│       │   ├── MessageList.tsx
│       │   ├── ToolCallCard.tsx
│       │   ├── SlashMenu.tsx
│       │   └── Composer.tsx
│       └── DocPreview/
│           └── DocPreview.tsx
└── tests/
    ├── setup.ts
    ├── unit/
    │   ├── ToolCallCard.test.tsx
    │   └── Composer.test.tsx
    └── e2e/
        └── walking-skeleton.spec.ts
```

---

## Conventions

- **Imports**: backend uses absolute imports rooted at `app.` (e.g. `from app.workspace.atomic import atomic_write_json`).
- **Async**: all tool functions and provider methods are `async def`. Tests use `pytest.mark.asyncio` (configured in `pyproject.toml`).
- **Type hints**: required everywhere. `mypy --strict` is not configured in M1 but code aims to be strict-clean.
- **Tests**: TDD throughout. Each task lands a failing test, makes it pass, commits.
- **Commits**: conventional style: `feat:`, `test:`, `chore:`, `docs:`. Each task's commit is one logical unit.
- **Working directory**: assume engineer runs commands from `emerge-v2/` repo root unless noted.
- **Workspace path**: tests use `tmp_path` fixture; runtime defaults to `./workspace/` from `Settings.workspace_root`.

---

## Task index

Backend foundation (1–6) → schemas (7–9) → provider (10–12) → tools (13–19) → skill (20–21) → chat service (22–25) → API routes (26–28) → frontend foundation (29–32) → frontend components (33–39) → e2e (40).

---

## Phase 1 — Backend foundation

### Task 1: Backend project scaffold

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.env.example`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/config.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
# backend/pyproject.toml
[project]
name = "emerge-backend"
version = "0.0.1"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "httpx>=0.27",
    "anyio>=4.6",
    "python-multipart>=0.0.12",
    "sse-starlette>=2.1",
    "pymupdf>=1.24",
    "claude-agent-sdk>=0.1.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
    "pytest-cov>=5.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-v"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]
```

- [ ] **Step 2: Create .env.example**

```bash
# backend/.env.example
EMERGE_WORKSPACE_ROOT=./workspace
EMERGE_ANTHROPIC_API_KEY=
EMERGE_DEFAULT_EXTRACT_MODEL=claude-sonnet-4-6
EMERGE_DEFAULT_AGENT_MODEL=claude-sonnet-4-6
EMERGE_LOG_LEVEL=INFO
```

- [ ] **Step 3: Create config.py**

```python
# backend/app/config.py
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMERGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    workspace_root: Path = Path("./workspace")
    anthropic_api_key: str = ""
    default_extract_model: str = "claude-sonnet-4-6"
    default_agent_model: str = "claude-sonnet-4-6"
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Create minimal main.py**

```python
# backend/app/main.py
from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()
app = FastAPI(title="emerge", version="0.0.1")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: Create empty package init files**

```python
# backend/app/__init__.py
# (empty)
```

```python
# backend/tests/__init__.py
# (empty)
```

```python
# backend/tests/conftest.py
import os
from pathlib import Path

import pytest


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Isolated workspace root for each test."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture(autouse=True)
def env_isolation(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    """Point EMERGE_WORKSPACE_ROOT at the per-test workspace."""
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("EMERGE_ANTHROPIC_API_KEY", "sk-test-not-used")
```

- [ ] **Step 6: Install deps and verify import**

Run:
```bash
cd backend && uv sync && uv run python -c "from app.main import app; print(app.title)"
```
Expected output: `emerge`

- [ ] **Step 7: Verify pytest discovers no tests but does not error**

Run:
```bash
cd backend && uv run pytest --collect-only
```
Expected: `no tests collected` exit 5; this is fine — we add tests next.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/.env.example backend/app backend/tests backend/uv.lock
git commit -m "chore(backend): scaffold pyproject, config, fastapi app"
```

---

### Task 2: Path helpers (`workspace/paths.py`)

**Files:**
- Create: `backend/app/workspace/__init__.py`
- Create: `backend/app/workspace/paths.py`
- Test: `backend/tests/unit/test_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_paths.py
from pathlib import Path

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
)


def test_project_dir_under_workspace(workspace: Path) -> None:
    assert project_dir(workspace, "p_abc") == workspace / "p_abc"


def test_schema_path(workspace: Path) -> None:
    assert schema_path(workspace, "p_abc") == workspace / "p_abc" / "schema.json"


def test_project_json_path(workspace: Path) -> None:
    assert project_json_path(workspace, "p_abc") == workspace / "p_abc" / "project.json"


def test_docs_dir(workspace: Path) -> None:
    assert docs_dir(workspace, "p_abc") == workspace / "p_abc" / "docs"


def test_doc_path_pdf(workspace: Path) -> None:
    assert doc_path(workspace, "p_abc", "d_xyz", "pdf") == workspace / "p_abc" / "docs" / "d_xyz.pdf"


def test_doc_meta_path(workspace: Path) -> None:
    assert doc_meta_path(workspace, "p_abc", "d_xyz") == workspace / "p_abc" / "docs" / "d_xyz.meta.json"


def test_predictions_draft_dir(workspace: Path) -> None:
    assert predictions_draft_dir(workspace, "p_abc") == workspace / "p_abc" / "predictions" / "_draft"


def test_versions_dir(workspace: Path) -> None:
    assert versions_dir(workspace, "p_abc") == workspace / "p_abc" / "versions"


def test_chats_dir(workspace: Path) -> None:
    assert chats_dir(workspace, "p_abc") == workspace / "p_abc" / "chats"


def test_keys_path(workspace: Path) -> None:
    assert keys_path(workspace) == workspace / "_keys.json"


def test_job_locks_dir(workspace: Path) -> None:
    assert job_locks_dir(workspace) == workspace / "_job_locks"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_paths.py -v`
Expected: ImportError — module `app.workspace.paths` does not exist.

- [ ] **Step 3: Implement paths**

```python
# backend/app/workspace/__init__.py
# (empty)
```

```python
# backend/app/workspace/paths.py
from pathlib import Path


def project_dir(workspace: Path, project_id: str) -> Path:
    return workspace / project_id


def project_json_path(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "project.json"


def schema_path(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "schema.json"


def docs_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "docs"


def doc_path(workspace: Path, project_id: str, doc_id: str, ext: str) -> Path:
    return docs_dir(workspace, project_id) / f"{doc_id}.{ext}"


def doc_meta_path(workspace: Path, project_id: str, doc_id: str) -> Path:
    return docs_dir(workspace, project_id) / f"{doc_id}.meta.json"


def predictions_draft_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "predictions" / "_draft"


def versions_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "versions"


def chats_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "chats"


def keys_path(workspace: Path) -> Path:
    return workspace / "_keys.json"


def job_locks_dir(workspace: Path) -> Path:
    return workspace / "_job_locks"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_paths.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace backend/tests/unit/test_paths.py
git commit -m "feat(workspace): path helpers for project artefacts"
```

---

### Task 3: Atomic write (`workspace/atomic.py`)

**Files:**
- Create: `backend/app/workspace/atomic.py`
- Test: `backend/tests/unit/test_atomic.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_atomic.py
import json
from pathlib import Path

import pytest

from app.workspace.atomic import (
    atomic_write_bytes,
    atomic_write_text,
    atomic_write_json,
)


def test_atomic_write_text_creates_file(workspace: Path) -> None:
    target = workspace / "x.txt"
    atomic_write_text(target, "hello")
    assert target.read_text() == "hello"


def test_atomic_write_text_overwrites(workspace: Path) -> None:
    target = workspace / "x.txt"
    target.write_text("old")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"


def test_atomic_write_bytes(workspace: Path) -> None:
    target = workspace / "x.bin"
    atomic_write_bytes(target, b"\x00\x01\x02")
    assert target.read_bytes() == b"\x00\x01\x02"


def test_atomic_write_json_serializes(workspace: Path) -> None:
    target = workspace / "x.json"
    atomic_write_json(target, {"a": 1, "b": [2, 3]})
    assert json.loads(target.read_text()) == {"a": 1, "b": [2, 3]}


def test_atomic_write_creates_parent_dirs(workspace: Path) -> None:
    target = workspace / "deep" / "nested" / "x.json"
    atomic_write_json(target, {"k": "v"})
    assert target.exists()


def test_no_tmp_file_left_behind(workspace: Path) -> None:
    target = workspace / "x.json"
    atomic_write_json(target, {"k": 1})
    leftovers = [p for p in workspace.iterdir() if p.name.startswith(".")]
    assert leftovers == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_atomic.py -v`
Expected: ImportError — `app.workspace.atomic` not found.

- [ ] **Step 3: Implement atomic write**

```python
# backend/app/workspace/atomic.py
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _atomic_replace(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def atomic_write_bytes(target: Path, data: bytes) -> None:
    _atomic_replace(target, data)


def atomic_write_text(target: Path, text: str, encoding: str = "utf-8") -> None:
    _atomic_replace(target, text.encode(encoding))


def atomic_write_json(target: Path, data: Any) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")
    _atomic_replace(target, payload)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_atomic.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace/atomic.py backend/tests/unit/test_atomic.py
git commit -m "feat(workspace): atomic_write_{bytes,text,json} via tmp+rename"
```

---

### Task 4: Async flock (`workspace/lock.py`)

**Files:**
- Create: `backend/app/workspace/lock.py`
- Test: `backend/tests/unit/test_lock.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_lock.py
import asyncio
from pathlib import Path

import pytest

from app.workspace.lock import project_lock


async def test_project_lock_acquires_and_releases(workspace: Path) -> None:
    pid = "p_test"
    (workspace / pid).mkdir()
    async with project_lock(workspace, pid):
        pass  # no error means we acquired and released


async def test_project_lock_serializes_concurrent(workspace: Path) -> None:
    pid = "p_test"
    (workspace / pid).mkdir()
    order: list[str] = []

    async def worker(name: str, hold_for: float) -> None:
        async with project_lock(workspace, pid):
            order.append(f"start:{name}")
            await asyncio.sleep(hold_for)
            order.append(f"end:{name}")

    await asyncio.gather(worker("A", 0.1), worker("B", 0.05))

    # Either A finished entirely before B started, or vice versa
    assert order in (
        ["start:A", "end:A", "start:B", "end:B"],
        ["start:B", "end:B", "start:A", "end:A"],
    )


async def test_project_lock_creates_lock_file(workspace: Path) -> None:
    pid = "p_test"
    (workspace / pid).mkdir()
    async with project_lock(workspace, pid):
        assert (workspace / pid / ".lock").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_lock.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement async flock**

```python
# backend/app/workspace/lock.py
import asyncio
import fcntl
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from app.workspace.paths import project_dir


@asynccontextmanager
async def project_lock(workspace: Path, project_id: str) -> AsyncIterator[None]:
    """Exclusive flock on {pid}/.lock. Blocks (in a thread) until acquired."""
    pdir = project_dir(workspace, project_id)
    pdir.mkdir(parents=True, exist_ok=True)
    lock_path = pdir / ".lock"
    fd = lock_path.open("w")
    try:
        await asyncio.to_thread(fcntl.flock, fd.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    finally:
        fd.close()
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_lock.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace/lock.py backend/tests/unit/test_lock.py
git commit -m "feat(workspace): async project_lock via fcntl flock"
```

---

### Task 5: ID generators (`workspace/ids.py`)

**Files:**
- Create: `backend/app/workspace/ids.py`
- Test: `backend/tests/unit/test_ids.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_ids.py
import re

from app.workspace.ids import (
    new_project_id,
    new_doc_id,
    new_chat_id,
    new_job_id,
)


def test_project_id_format() -> None:
    pid = new_project_id()
    assert re.match(r"^p_[a-z0-9]{12}$", pid), pid


def test_doc_id_format() -> None:
    did = new_doc_id()
    assert re.match(r"^d_[a-z0-9]{12}$", did), did


def test_chat_id_format() -> None:
    cid = new_chat_id()
    assert re.match(r"^c_[a-z0-9]{12}$", cid), cid


def test_job_id_format() -> None:
    jid = new_job_id()
    assert re.match(r"^j_[a-z0-9]{12}$", jid), jid


def test_ids_are_unique() -> None:
    ids = {new_project_id() for _ in range(1000)}
    assert len(ids) == 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_ids.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement ids**

```python
# backend/app/workspace/ids.py
import secrets


def _new(prefix: str) -> str:
    # 12 chars of base36 from 60 bits of entropy
    n = secrets.randbits(60)
    s = ""
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    for _ in range(12):
        s = alphabet[n % 36] + s
        n //= 36
    return f"{prefix}_{s}"


def new_project_id() -> str:
    return _new("p")


def new_doc_id() -> str:
    return _new("d")


def new_chat_id() -> str:
    return _new("c")


def new_job_id() -> str:
    return _new("j")
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_ids.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace/ids.py backend/tests/unit/test_ids.py
git commit -m "feat(workspace): typed id generators"
```

---

### Task 6: Healthcheck integration test

**Files:**
- Create: `backend/tests/integration/__init__.py`
- Create: `backend/tests/integration/test_healthz.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/__init__.py
# (empty)
```

```python
# backend/tests/integration/test_healthz.py
from fastapi.testclient import TestClient

from app.main import app


def test_healthz() -> None:
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test**

Run: `cd backend && uv run pytest tests/integration/test_healthz.py -v`
Expected: PASS (route already exists from Task 1).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration
git commit -m "test(api): healthz integration test"
```

---

## Phase 2 — Schemas

### Task 7: SchemaField pydantic model

**Files:**
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/schema_field.py`
- Test: `backend/tests/unit/test_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_schemas.py
import pytest
from pydantic import ValidationError

from app.schemas.schema_field import SchemaField, FieldType


def test_simple_field_minimal() -> None:
    f = SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number")
    assert f.name == "invoice_no"
    assert f.type == FieldType.STRING
    assert f.required is False  # default
    assert f.examples is None
    assert f.enum is None
    assert f.children is None


def test_field_name_must_be_snake_case() -> None:
    with pytest.raises(ValidationError):
        SchemaField(name="InvoiceNo", type=FieldType.STRING, description="x")
    with pytest.raises(ValidationError):
        SchemaField(name="invoice-no", type=FieldType.STRING, description="x")


def test_enum_field() -> None:
    f = SchemaField(
        name="document_type",
        type=FieldType.STRING,
        description="kind of doc",
        enum=["invoice", "others"],
    )
    assert f.enum == ["invoice", "others"]


def test_array_object_requires_children() -> None:
    with pytest.raises(ValidationError):
        SchemaField(name="line_items", type=FieldType.ARRAY_OBJECT, description="x")


def test_array_object_with_children_ok() -> None:
    f = SchemaField(
        name="line_items",
        type=FieldType.ARRAY_OBJECT,
        description="x",
        children=[
            SchemaField(name="qty", type=FieldType.NUMBER, description="qty"),
            SchemaField(name="unit_price", type=FieldType.NUMBER, description="price"),
        ],
    )
    assert len(f.children) == 2  # type: ignore[arg-type]


def test_serializes_round_trip() -> None:
    f = SchemaField(name="x", type=FieldType.STRING, description="d", required=True)
    blob = f.model_dump()
    f2 = SchemaField(**blob)
    assert f == f2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_schemas.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement SchemaField**

```python
# backend/app/schemas/__init__.py
# (empty)
```

```python
# backend/app/schemas/schema_field.py
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    ARRAY_OBJECT = "array<object>"


class SchemaField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    name: str
    type: FieldType
    description: str
    required: bool = False
    examples: Optional[list[str]] = None
    enum: Optional[list[str]] = None
    children: Optional[list["SchemaField"]] = None

    @field_validator("name")
    @classmethod
    def name_snake_case(cls, v: str) -> str:
        if not _SNAKE_CASE.match(v):
            raise ValueError(f"field name must be snake_case: {v!r}")
        return v

    @model_validator(mode="after")
    def array_object_needs_children(self) -> "SchemaField":
        if self.type == FieldType.ARRAY_OBJECT and not self.children:
            raise ValueError("type=array<object> requires non-empty children")
        return self


SchemaField.model_rebuild()
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_schemas.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/schemas/schema_field.py backend/tests/unit/test_schemas.py
git commit -m "feat(schemas): SchemaField with snake_case + array_object validation"
```

---

### Task 8: Error envelope and tool result

**Files:**
- Create: `backend/app/schemas/envelope.py`
- Modify: `backend/tests/unit/test_schemas.py` — append test cases

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/unit/test_schemas.py`:

```python
from app.schemas.envelope import ErrorEnvelope, ToolResult


def test_error_envelope() -> None:
    e = ErrorEnvelope(error_code="provider_timeout", error_message_en="timed out")
    assert e.error_code == "provider_timeout"
    assert e.error_message_en == "timed out"


def test_tool_result_ok() -> None:
    r: ToolResult[dict] = ToolResult(ok=True, data={"x": 1})
    assert r.ok
    assert r.data == {"x": 1}
    assert r.error is None


def test_tool_result_err() -> None:
    err = ErrorEnvelope(error_code="x", error_message_en="y")
    r: ToolResult[dict] = ToolResult(ok=False, error=err)
    assert not r.ok
    assert r.data is None
    assert r.error is not None
    assert r.error.error_code == "x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_schemas.py -v`
Expected: ImportError on envelope.

- [ ] **Step 3: Implement envelope**

```python
# backend/app/schemas/envelope.py
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error_code: str
    error_message_en: str


T = TypeVar("T")


class ToolResult(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    data: Optional[T] = None
    error: Optional[ErrorEnvelope] = None
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_schemas.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/envelope.py backend/tests/unit/test_schemas.py
git commit -m "feat(schemas): ErrorEnvelope + generic ToolResult"
```

---

### Task 9: Extraction output schema

**Files:**
- Create: `backend/app/schemas/extraction.py`
- Modify: `backend/tests/unit/test_schemas.py` — append

- [ ] **Step 1: Append failing test**

```python
# (append to backend/tests/unit/test_schemas.py)
from app.schemas.extraction import ExtractionOutput


def test_extraction_output_minimal() -> None:
    o = ExtractionOutput(entities=[{"document_type": "invoice"}])
    assert o.entities == [{"document_type": "invoice"}]
    assert o.evidence is None


def test_extraction_output_with_evidence() -> None:
    o = ExtractionOutput(
        entities=[{"document_type": "invoice", "invoice_no": "INV-1"}],
        evidence=[{"document_type": 1, "invoice_no": 1}],
    )
    assert o.evidence == [{"document_type": 1, "invoice_no": 1}]


def test_extraction_evidence_must_match_entities_length() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractionOutput(
            entities=[{"a": "x"}, {"a": "y"}],
            evidence=[{"a": 1}],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_schemas.py -v`
Expected: ImportError on extraction.

- [ ] **Step 3: Implement ExtractionOutput**

```python
# backend/app/schemas/extraction.py
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractionOutput(BaseModel):
    """Wire format for extract_one / extract_batch tool output.

    Field name `evidence` serializes as `_evidence` on the wire (LLM contract).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entities: list[dict[str, Any]]
    evidence: Optional[list[dict[str, Optional[int]]]] = Field(default=None, alias="_evidence")

    @model_validator(mode="after")
    def evidence_length_matches(self) -> "ExtractionOutput":
        if self.evidence is not None and len(self.evidence) != len(self.entities):
            raise ValueError("_evidence length must equal entities length")
        return self
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_schemas.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/extraction.py backend/tests/unit/test_schemas.py
git commit -m "feat(schemas): ExtractionOutput with _evidence parallel array"
```

---

## Phase 3 — Provider adapter

### Task 10: Provider Protocol + ContentBlock

**Files:**
- Create: `backend/app/provider/__init__.py`
- Create: `backend/app/provider/base.py`

- [ ] **Step 1: Create files (no test — pure typing surface)**

```python
# backend/app/provider/__init__.py
# (empty)
```

```python
# backend/app/provider/base.py
from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text"] = "text"
    text: str


class ImageBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["image"] = "image"
    media_type: str  # "image/png", "image/jpeg"
    data_b64: str


class DocumentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["document"] = "document"
    media_type: str  # "application/pdf"
    data_b64: str


ContentBlock = TextBlock | ImageBlock | DocumentBlock


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_json: dict[str, Any]
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class Provider(Protocol):
    async def extract(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_content: list[ContentBlock],
        response_schema: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> ProviderResult:
        """Extract structured JSON from input. Adapter handles retry/backoff internally.

        Returns raw_json validated against response_schema (best-effort, may still need
        downstream pydantic validation).
        """
        ...
```

- [ ] **Step 2: Verify imports work**

Run: `cd backend && uv run python -c "from app.provider.base import Provider, TextBlock, DocumentBlock, ProviderResult; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/provider/__init__.py backend/app/provider/base.py
git commit -m "feat(provider): protocol + content block types"
```

---

### Task 11: Retry helper with exponential backoff

**Files:**
- Create: `backend/app/provider/retry.py`
- Test: `backend/tests/unit/test_provider_retry.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_provider_retry.py
import asyncio

import pytest

from app.provider.retry import retry_async, RetryableError


async def test_succeeds_on_first_try() -> None:
    calls = 0

    async def f() -> int:
        nonlocal calls
        calls += 1
        return 42

    assert await retry_async(f, max_attempts=3, base_delay=0.0) == 42
    assert calls == 1


async def test_retries_on_retryable_error() -> None:
    calls = 0

    async def f() -> int:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RetryableError("temporary")
        return 7

    result = await retry_async(f, max_attempts=5, base_delay=0.0)
    assert result == 7
    assert calls == 3


async def test_gives_up_after_max_attempts() -> None:
    calls = 0

    async def f() -> int:
        nonlocal calls
        calls += 1
        raise RetryableError("nope")

    with pytest.raises(RetryableError):
        await retry_async(f, max_attempts=3, base_delay=0.0)
    assert calls == 3


async def test_does_not_retry_non_retryable() -> None:
    calls = 0

    async def f() -> int:
        nonlocal calls
        calls += 1
        raise ValueError("hard")

    with pytest.raises(ValueError):
        await retry_async(f, max_attempts=3, base_delay=0.0)
    assert calls == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_provider_retry.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement retry**

```python
# backend/app/provider/retry.py
import asyncio
import random
from typing import Awaitable, Callable, TypeVar


class RetryableError(Exception):
    """Marker exception. retry_async will catch and retry these."""


T = TypeVar("T")


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
) -> T:
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except RetryableError as e:
            last_exc = e
            if attempt == max_attempts:
                raise
            sleep_for = min(max_delay, base_delay * (2 ** (attempt - 1)))
            sleep_for *= 0.75 + random.random() * 0.5  # jitter ±25%
            await asyncio.sleep(sleep_for)
    # unreachable
    raise last_exc  # type: ignore[misc]
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_provider_retry.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/provider/retry.py backend/tests/unit/test_provider_retry.py
git commit -m "feat(provider): async retry helper with exponential backoff + jitter"
```

---

### Task 12: Anthropic provider adapter

**Files:**
- Create: `backend/app/provider/anthropic.py`
- Test: `backend/tests/unit/test_provider_anthropic.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_provider_anthropic.py
import json

import httpx
import pytest
import respx

from app.provider.anthropic import AnthropicProvider
from app.provider.base import TextBlock, DocumentBlock
from app.provider.retry import RetryableError


SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {"type": "array"},
    },
    "required": ["entities"],
}


def _tool_use_response(payload: dict) -> dict:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "emit_extraction",
                "input": payload,
            },
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


@pytest.mark.respx(base_url="https://api.anthropic.com")
async def test_extract_happy_path(respx_mock: respx.MockRouter) -> None:
    payload = {"entities": [{"invoice_no": "INV-1"}]}
    respx_mock.post("/v1/messages").mock(
        return_value=httpx.Response(200, json=_tool_use_response(payload))
    )

    p = AnthropicProvider(api_key="sk-test")
    result = await p.extract(
        model_id="claude-sonnet-4-6",
        system_prompt="you are an extractor",
        user_content=[TextBlock(text="hi")],
        response_schema=SCHEMA,
    )
    assert result.raw_json == payload
    assert result.model_id == "claude-sonnet-4-6"
    assert result.input_tokens == 100
    assert result.output_tokens == 50


@pytest.mark.respx(base_url="https://api.anthropic.com")
async def test_extract_retries_on_429(respx_mock: respx.MockRouter) -> None:
    payload = {"entities": []}
    respx_mock.post("/v1/messages").mock(
        side_effect=[
            httpx.Response(429, json={"error": {"message": "rate"}}),
            httpx.Response(200, json=_tool_use_response(payload)),
        ]
    )

    p = AnthropicProvider(api_key="sk-test", retry_base_delay=0.0)
    result = await p.extract(
        model_id="claude-sonnet-4-6",
        system_prompt="x",
        user_content=[TextBlock(text="x")],
        response_schema=SCHEMA,
    )
    assert result.raw_json == payload


@pytest.mark.respx(base_url="https://api.anthropic.com")
async def test_extract_gives_up_after_retries(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("/v1/messages").mock(
        return_value=httpx.Response(429, json={"error": {"message": "rate"}})
    )
    p = AnthropicProvider(api_key="sk-test", retry_base_delay=0.0, retry_max_attempts=2)
    with pytest.raises(RetryableError):
        await p.extract(
            model_id="claude-sonnet-4-6",
            system_prompt="x",
            user_content=[TextBlock(text="x")],
            response_schema=SCHEMA,
        )


@pytest.mark.respx(base_url="https://api.anthropic.com")
async def test_extract_includes_document_block(respx_mock: respx.MockRouter) -> None:
    payload = {"entities": []}
    route = respx_mock.post("/v1/messages").mock(
        return_value=httpx.Response(200, json=_tool_use_response(payload))
    )
    p = AnthropicProvider(api_key="sk-test")
    await p.extract(
        model_id="claude-sonnet-4-6",
        system_prompt="x",
        user_content=[
            TextBlock(text="extract this"),
            DocumentBlock(media_type="application/pdf", data_b64="JVBERi0xLjQ="),
        ],
        response_schema=SCHEMA,
    )
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "claude-sonnet-4-6"
    user_blocks = body["messages"][0]["content"]
    assert any(b.get("type") == "document" for b in user_blocks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_provider_anthropic.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement AnthropicProvider**

```python
# backend/app/provider/anthropic.py
from __future__ import annotations

from typing import Any

import httpx

from app.provider.base import (
    ContentBlock,
    DocumentBlock,
    ImageBlock,
    Provider,
    ProviderResult,
    TextBlock,
)
from app.provider.retry import RetryableError, retry_async


_API_URL = "https://api.anthropic.com/v1/messages"
_TOOL_NAME = "emit_extraction"


def _block_to_anthropic(b: ContentBlock) -> dict[str, Any]:
    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    if isinstance(b, ImageBlock):
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": b.media_type, "data": b.data_b64},
        }
    if isinstance(b, DocumentBlock):
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": b.media_type, "data": b.data_b64},
        }
    raise ValueError(f"unknown block type: {b!r}")


class AnthropicProvider(Provider):
    def __init__(
        self,
        *,
        api_key: str,
        timeout: float = 120.0,
        retry_max_attempts: int = 3,
        retry_base_delay: float = 0.5,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._retry_max = retry_max_attempts
        self._retry_base = retry_base_delay

    async def extract(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_content: list[ContentBlock],
        response_schema: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> ProviderResult:
        params = params or {}
        body = {
            "model": model_id,
            "max_tokens": params.get("max_tokens", 4096),
            "temperature": params.get("temperature", 0.0),
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": [_block_to_anthropic(b) for b in user_content],
                }
            ],
            "tools": [
                {
                    "name": _TOOL_NAME,
                    "description": "Emit the structured extraction result.",
                    "input_schema": response_schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": _TOOL_NAME},
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async def _call() -> ProviderResult:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(_API_URL, json=body, headers=headers)
                if resp.status_code in (429, 502, 503, 504):
                    raise RetryableError(f"anthropic {resp.status_code}: {resp.text[:200]}")
                resp.raise_for_status()
                data = resp.json()
            tool_use = next(
                (c for c in data.get("content", []) if c.get("type") == "tool_use"),
                None,
            )
            if tool_use is None:
                raise RuntimeError(f"no tool_use in anthropic response: {data}")
            usage = data.get("usage", {})
            return ProviderResult(
                raw_json=tool_use["input"],
                model_id=data.get("model", model_id),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        return await retry_async(
            _call,
            max_attempts=self._retry_max,
            base_delay=self._retry_base,
        )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_provider_anthropic.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/provider/anthropic.py backend/tests/unit/test_provider_anthropic.py
git commit -m "feat(provider): Anthropic adapter with tool-use JSON output + retries"
```

---

## Phase 4 — Filesystem tools

### Task 13: Project tools (create / list / update)

**Files:**
- Create: `backend/app/tools/__init__.py`
- Create: `backend/app/tools/_result.py`
- Create: `backend/app/tools/projects.py`
- Test: `backend/tests/unit/test_tool_projects.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_tool_projects.py
import json
from pathlib import Path

from app.tools.projects import (
    create_project,
    list_projects,
    update_project,
)


async def test_create_project_writes_project_json(workspace: Path) -> None:
    pid = await create_project(workspace, name="inv-MY")
    pdir = workspace / pid
    assert pdir.is_dir()
    blob = json.loads((pdir / "project.json").read_text())
    assert blob["name"] == "inv-MY"
    assert blob["project_type"] == "extraction"
    assert blob["active_version_id"] is None


async def test_create_project_writes_empty_schema(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    blob = json.loads((workspace / pid / "schema.json").read_text())
    assert blob == []


async def test_list_projects_empty(workspace: Path) -> None:
    assert await list_projects(workspace) == []


async def test_list_projects_after_create(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    items = await list_projects(workspace)
    assert len(items) == 1
    assert items[0]["project_id"] == pid
    assert items[0]["name"] == "x"


async def test_update_project_extract_model(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await update_project(workspace, pid, {"extract_model": "gpt-4o-2024-08"})
    blob = json.loads((workspace / pid / "project.json").read_text())
    assert blob["extract_model"] == "gpt-4o-2024-08"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_tool_projects.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/tools/__init__.py
# (empty for now; MCP server registration comes in Task 20)
```

```python
# backend/app/tools/_result.py
from typing import Any

from app.schemas.envelope import ErrorEnvelope, ToolResult


def tool_ok(data: Any) -> ToolResult:
    return ToolResult(ok=True, data=data)


def tool_err(code: str, message: str) -> ToolResult:
    return ToolResult(ok=False, error=ErrorEnvelope(error_code=code, error_message_en=message))
```

```python
# backend/app/tools/projects.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_project_id
from app.workspace.lock import project_lock
from app.workspace.paths import (
    docs_dir,
    predictions_draft_dir,
    project_dir,
    project_json_path,
    schema_path,
    versions_dir,
    chats_dir,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_project(
    workspace: Path,
    *,
    name: str,
    project_type: str = "extraction",
) -> str:
    pid = new_project_id()
    pdir = project_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=False)
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    versions_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    chats_dir(workspace, pid).mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    blob = {
        "name": name,
        "project_type": project_type,
        "created_at": _now_iso(),
        "extract_model": settings.default_extract_model,
        "extract_params": {"temperature": 0.0},
        "autoresearch_proposer_model": None,
        "active_version_id": None,
    }
    atomic_write_json(project_json_path(workspace, pid), blob)
    atomic_write_json(schema_path(workspace, pid), [])
    return pid


async def list_projects(workspace: Path) -> list[dict[str, Any]]:
    if not workspace.exists():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(workspace.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        pj = child / "project.json"
        if not pj.exists():
            continue
        blob = json.loads(pj.read_text())
        out.append({"project_id": child.name, **blob})
    return out


async def update_project(workspace: Path, project_id: str, patch: dict[str, Any]) -> None:
    async with project_lock(workspace, project_id):
        pj = project_json_path(workspace, project_id)
        blob = json.loads(pj.read_text())
        blob.update(patch)
        atomic_write_json(pj, blob)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_projects.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools backend/tests/unit/test_tool_projects.py
git commit -m "feat(tools): create_project / list_projects / update_project"
```

---

### Task 14: Doc upload / list / read tools (no PDF render yet)

**Files:**
- Create: `backend/app/tools/docs.py`
- Test: `backend/tests/unit/test_tool_docs.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_tool_docs.py
import json
from pathlib import Path

import pytest

from app.tools.projects import create_project
from app.tools.docs import upload_doc, list_docs, read_doc


SAMPLE_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f\n%%EOF\n"


async def test_upload_doc_writes_file_and_meta(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, SAMPLE_PDF, "invoice-001.pdf")
    pdir = workspace / pid / "docs"
    assert (pdir / f"{did}.pdf").read_bytes() == SAMPLE_PDF
    meta = json.loads((pdir / f"{did}.meta.json").read_text())
    assert meta["filename"] == "invoice-001.pdf"
    assert meta["sha256"]
    assert meta["uploaded_at"]


async def test_upload_doc_rejects_non_pdf(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    with pytest.raises(ValueError, match="unsupported"):
        await upload_doc(workspace, pid, b"...", "weird.docx")


async def test_list_docs_returns_uploaded(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    d1 = await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    d2 = await upload_doc(workspace, pid, SAMPLE_PDF, "b.pdf")
    items = await list_docs(workspace, pid)
    ids = {it["doc_id"] for it in items}
    assert ids == {d1, d2}


async def test_read_doc_returns_bytes(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    assert await read_doc(workspace, pid, did) == SAMPLE_PDF
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_tool_docs.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/tools/docs.py
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.workspace.atomic import atomic_write_bytes, atomic_write_json
from app.workspace.ids import new_doc_id
from app.workspace.lock import project_lock
from app.workspace.paths import doc_meta_path, doc_path, docs_dir


_ALLOWED_EXT = {"pdf": "pdf", "png": "png", "jpg": "jpg", "jpeg": "jpg"}


def _ext_from_filename(filename: str) -> str:
    if "." not in filename:
        raise ValueError(f"unsupported file type: {filename!r}")
    raw = filename.rsplit(".", 1)[1].lower()
    if raw not in _ALLOWED_EXT:
        raise ValueError(f"unsupported file type: {filename!r}")
    return _ALLOWED_EXT[raw]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def upload_doc(
    workspace: Path,
    project_id: str,
    data: bytes,
    filename: str,
) -> str:
    ext = _ext_from_filename(filename)
    did = new_doc_id()
    sha = hashlib.sha256(data).hexdigest()
    page_count = _count_pages(data, ext)

    async with project_lock(workspace, project_id):
        docs_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(doc_path(workspace, project_id, did, ext), data)
        atomic_write_json(
            doc_meta_path(workspace, project_id, did),
            {
                "doc_id": did,
                "filename": filename,
                "ext": ext,
                "sha256": sha,
                "page_count": page_count,
                "uploaded_at": _now_iso(),
            },
        )
    return did


def _count_pages(data: bytes, ext: str) -> int:
    if ext != "pdf":
        return 1
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=data, filetype="pdf") as doc:
            return doc.page_count
    except Exception:
        return 1


async def list_docs(workspace: Path, project_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    d = docs_dir(workspace, project_id)
    if not d.exists():
        return out
    for meta in sorted(d.glob("*.meta.json")):
        out.append(json.loads(meta.read_text()))
    return out


async def read_doc(workspace: Path, project_id: str, doc_id: str) -> bytes:
    meta_p = doc_meta_path(workspace, project_id, doc_id)
    meta = json.loads(meta_p.read_text())
    return doc_path(workspace, project_id, doc_id, meta["ext"]).read_bytes()
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_docs.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/docs.py backend/tests/unit/test_tool_docs.py
git commit -m "feat(tools): upload_doc / list_docs / read_doc"
```

---

### Task 15: PDF page render

**Files:**
- Modify: `backend/app/tools/docs.py` — add `pdf_render_page`
- Create: `backend/tests/fixtures/invoice_sample.pdf` (tiny 1-page PDF)
- Modify: `backend/tests/unit/test_tool_docs.py` — add tests

- [ ] **Step 1: Generate fixture PDF**

```bash
cd backend && uv run python -c "
import fitz
doc = fitz.open()
page = doc.new_page()
page.insert_text((50, 100), 'Invoice INV-001\nTotal: 1250.50')
doc.save('tests/fixtures/invoice_sample.pdf')
"
mkdir -p backend/tests/fixtures
ls backend/tests/fixtures/invoice_sample.pdf
```

(if `mkdir` needs to come first, run that first.)

- [ ] **Step 2: Append failing test**

Append to `backend/tests/unit/test_tool_docs.py`:

```python
import pytest
from app.tools.docs import pdf_render_page


_FIXTURE = Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf"


async def test_pdf_render_page_writes_png(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "sample.pdf")
    png_path = await pdf_render_page(workspace, pid, did, page=1)
    assert png_path.exists()
    assert png_path.suffix == ".png"
    # Quick magic-byte check
    assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


async def test_pdf_render_page_invalid_page_raises(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "sample.pdf")
    with pytest.raises(ValueError, match="page"):
        await pdf_render_page(workspace, pid, did, page=99)
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && uv run pytest tests/unit/test_tool_docs.py::test_pdf_render_page_writes_png -v`
Expected: ImportError.

- [ ] **Step 4: Implement pdf_render_page**

Append to `backend/app/tools/docs.py`:

```python
async def pdf_render_page(
    workspace: Path,
    project_id: str,
    doc_id: str,
    *,
    page: int,
    dpi: int = 150,
) -> Path:
    """Render PDF page as PNG cached under docs/_render/{doc_id}_p{n}.png."""
    import fitz  # PyMuPDF

    meta = json.loads(doc_meta_path(workspace, project_id, doc_id).read_text())
    if meta["ext"] != "pdf":
        raise ValueError(f"doc {doc_id} is not a pdf")
    src = doc_path(workspace, project_id, doc_id, meta["ext"])

    cache_dir = docs_dir(workspace, project_id) / "_render"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{doc_id}_p{page}.png"
    if out.exists():
        return out

    with fitz.open(src) as pdf:
        if page < 1 or page > pdf.page_count:
            raise ValueError(f"page {page} out of range (1..{pdf.page_count})")
        pix = pdf[page - 1].get_pixmap(dpi=dpi)
        atomic_write_bytes(out, pix.tobytes("png"))
    return out
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_docs.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/docs.py backend/tests/unit/test_tool_docs.py backend/tests/fixtures/invoice_sample.pdf
git commit -m "feat(tools): pdf_render_page with PNG cache"
```

---

### Task 16: Schema read / write tools

**Files:**
- Create: `backend/app/tools/schema.py`
- Test: `backend/tests/unit/test_tool_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_tool_schema.py
import json
from pathlib import Path

import pytest

from app.tools.projects import create_project
from app.tools.schema import read_schema, write_schema, StructuralChangeError
from app.schemas.schema_field import FieldType, SchemaField


def _f(name: str, **kw: object) -> SchemaField:
    return SchemaField(name=name, type=FieldType.STRING, description="d", **kw)  # type: ignore[arg-type]


async def test_read_schema_empty_after_create(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    assert await read_schema(workspace, pid) == []


async def test_write_schema_persists(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await write_schema(workspace, pid, [_f("invoice_no")], reason="initial", allow_structural=True)
    got = await read_schema(workspace, pid)
    assert len(got) == 1
    assert got[0].name == "invoice_no"


async def test_write_schema_blocks_structural_change_without_flag(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await write_schema(workspace, pid, [_f("a")], reason="init", allow_structural=True)
    with pytest.raises(StructuralChangeError):
        await write_schema(workspace, pid, [_f("a"), _f("b")], reason="add b")


async def test_write_schema_allows_description_edit(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await write_schema(workspace, pid, [_f("a", description="old")], reason="init", allow_structural=True)
    await write_schema(workspace, pid, [_f("a", description="new")], reason="edit text")
    got = await read_schema(workspace, pid)
    assert got[0].description == "new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_tool_schema.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/tools/schema.py
from __future__ import annotations

import json
from pathlib import Path

from app.schemas.schema_field import SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import schema_path


class StructuralChangeError(Exception):
    """Raised when write_schema is called without allow_structural=True
    but the change adds, removes, or renames a field, or changes its type."""


async def read_schema(workspace: Path, project_id: str) -> list[SchemaField]:
    raw = json.loads(schema_path(workspace, project_id).read_text())
    return [SchemaField(**f) for f in raw]


def _is_structural_change(old: list[SchemaField], new: list[SchemaField]) -> bool:
    old_map = {f.name: f.type for f in old}
    new_map = {f.name: f.type for f in new}
    if set(old_map.keys()) != set(new_map.keys()):
        return True
    for name in old_map:
        if old_map[name] != new_map[name]:
            return True
    return False


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

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_schema.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/schema.py backend/tests/unit/test_tool_schema.py
git commit -m "feat(tools): read_schema / write_schema with structural-change gate"
```

---

### Task 17: derive_schema tool (LLM-backed)

**Files:**
- Modify: `backend/app/tools/schema.py` — add `derive_schema`
- Modify: `backend/tests/unit/test_tool_schema.py` — add stub provider test
- Modify: `backend/tests/conftest.py` — add stub provider fixture

- [ ] **Step 1: Add stub provider fixture**

Append to `backend/tests/conftest.py`:

```python
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.provider.base import Provider, ProviderResult


@pytest.fixture
def stub_provider() -> AsyncMock:
    """An AsyncMock implementing the Provider protocol. Tests set return_value."""
    mock = AsyncMock(spec=Provider)
    return mock


def make_provider_result(payload: dict[str, Any], model_id: str = "stub") -> ProviderResult:
    return ProviderResult(raw_json=payload, model_id=model_id, input_tokens=0, output_tokens=0)
```

- [ ] **Step 2: Append failing test**

Append to `backend/tests/unit/test_tool_schema.py`:

```python
from unittest.mock import AsyncMock

from app.tools.schema import derive_schema
from app.tools.docs import upload_doc
from tests.conftest import make_provider_result


async def test_derive_schema_calls_provider(workspace: Path, stub_provider: AsyncMock) -> None:
    pid = await create_project(workspace, name="x")
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    did = await upload_doc(workspace, pid, pdf_bytes, "a.pdf")

    stub_provider.extract.return_value = make_provider_result(
        {
            "fields": [
                {"name": "invoice_no", "type": "string", "description": "Invoice number", "required": True},
                {"name": "total_amount", "type": "number", "description": "Total amount", "required": True},
            ]
        }
    )

    fields = await derive_schema(
        workspace,
        pid,
        sample_doc_ids=[did],
        intent="extract core invoice info",
        provider=stub_provider,
    )
    assert len(fields) == 2
    names = {f.name for f in fields}
    assert names == {"invoice_no", "total_amount"}
    stub_provider.extract.assert_awaited_once()
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && uv run pytest tests/unit/test_tool_schema.py::test_derive_schema_calls_provider -v`
Expected: ImportError on derive_schema.

- [ ] **Step 4: Implement derive_schema**

Append to `backend/app/tools/schema.py`:

```python
import base64
from typing import Any

from app.provider.base import (
    ContentBlock,
    DocumentBlock,
    ImageBlock,
    Provider,
    TextBlock,
)
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import list_docs, read_doc
from app.workspace.paths import doc_meta_path

_DERIVE_SYSTEM = """You are designing a JSON extraction schema for a document type.
Given sample documents and a user intent, propose a list of fields to extract.

Output rules:
- snake_case English keys only
- prefer flat fields; nest only for natural arrays (line items, addresses)
- write a `description` for each field that says what to look for AND what format to output
- mark fields `required: true` only when they always appear

Use the provided tool to emit the schema."""


_DERIVE_TOOL_SCHEMA = {
    "type": "object",
    "required": ["fields"],
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "description"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["string", "number", "boolean", "date", "array<object>"]},
                    "description": {"type": "string"},
                    "required": {"type": "boolean"},
                    "examples": {"type": "array", "items": {"type": "string"}},
                    "enum": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


async def _doc_to_block(workspace: Path, project_id: str, doc_id: str) -> ContentBlock:
    import json as _json
    meta = _json.loads(doc_meta_path(workspace, project_id, doc_id).read_text())
    data = await read_doc(workspace, project_id, doc_id)
    b64 = base64.b64encode(data).decode("ascii")
    if meta["ext"] == "pdf":
        return DocumentBlock(media_type="application/pdf", data_b64=b64)
    media_type = "image/png" if meta["ext"] == "png" else "image/jpeg"
    return ImageBlock(media_type=media_type, data_b64=b64)


async def derive_schema(
    workspace: Path,
    project_id: str,
    *,
    sample_doc_ids: list[str],
    intent: str,
    provider: Provider,
    model_id: str = "claude-sonnet-4-6",
) -> list[SchemaField]:
    user_blocks: list[ContentBlock] = [TextBlock(text=f"User intent: {intent}")]
    for did in sample_doc_ids:
        user_blocks.append(await _doc_to_block(workspace, project_id, did))

    result = await provider.extract(
        model_id=model_id,
        system_prompt=_DERIVE_SYSTEM,
        user_content=user_blocks,
        response_schema=_DERIVE_TOOL_SCHEMA,
    )
    raw_fields = result.raw_json.get("fields", [])
    out: list[SchemaField] = []
    for f in raw_fields:
        out.append(SchemaField(**f))
    return out
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_schema.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/schema.py backend/tests/unit/test_tool_schema.py backend/tests/conftest.py
git commit -m "feat(tools): derive_schema via provider tool-use"
```

---

### Task 18: extract_one tool

**Files:**
- Create: `backend/app/tools/extract.py`
- Test: `backend/tests/unit/test_tool_extract.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_tool_extract.py
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.tools.projects import create_project
from app.tools.docs import upload_doc
from app.tools.schema import write_schema
from app.tools.extract import extract_one
from app.schemas.schema_field import FieldType, SchemaField
from tests.conftest import make_provider_result


_FIXTURE = Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf"


def _basic_schema() -> list[SchemaField]:
    return [
        SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number"),
        SchemaField(name="total_amount", type=FieldType.NUMBER, description="Total amount"),
    ]


async def test_extract_one_writes_prediction(workspace: Path, stub_provider: AsyncMock) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf")
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    stub_provider.extract.return_value = make_provider_result(
        {
            "entities": [{"invoice_no": "INV-1", "total_amount": 1250.5}],
            "_evidence": [{"invoice_no": 1, "total_amount": 1}],
        }
    )

    out = await extract_one(workspace, pid, did, provider=stub_provider)
    assert out["entities"][0]["invoice_no"] == "INV-1"
    assert out["_evidence"][0]["invoice_no"] == 1

    pred = json.loads((workspace / pid / "predictions" / "_draft" / f"{did}.json").read_text())
    assert pred == out


async def test_extract_one_invalid_json_returns_error(workspace: Path, stub_provider: AsyncMock) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf")
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    stub_provider.extract.return_value = make_provider_result({"wrong_top_level": "x"})

    with pytest.raises(ValueError, match="entities"):
        await extract_one(workspace, pid, did, provider=stub_provider)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_tool_extract.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement extract_one**

```python
# backend/app/tools/extract.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.provider.base import ContentBlock, Provider, TextBlock
from app.schemas.extraction import ExtractionOutput
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.schema import _doc_to_block
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    predictions_draft_dir,
    project_json_path,
    schema_path,
)


_EXTRACT_SYSTEM = """You extract structured data from a document.

Output rules:
- top-level: array of objects (entities). One PDF may contain multiple entities (e.g. multiple receipts).
- snake_case English keys only.
- omit fields when uncertain (do NOT return null or empty strings as placeholders).
- emit `_evidence` parallel to `entities`: per-entity dict mapping field_name -> page integer (1-based).
  Use the page where you saw the value. For derived fields (sums, formatted dates) emit null.

Use the emit_extraction tool to return the result."""


def _build_response_schema(schema: list[SchemaField]) -> dict[str, Any]:
    """Convert SchemaField[] to JSON schema for tool input."""
    field_props: dict[str, Any] = {}
    required: list[str] = []
    for f in schema:
        field_props[f.name] = _field_jsonschema(f)
        if f.required:
            required.append(f.name)
    entity_schema = {
        "type": "object",
        "properties": field_props,
    }
    if required:
        entity_schema["required"] = required

    return {
        "type": "object",
        "required": ["entities"],
        "properties": {
            "entities": {"type": "array", "items": entity_schema},
            "_evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": {"type": ["integer", "null"]},
                },
            },
        },
    }


def _field_jsonschema(f: SchemaField) -> dict[str, Any]:
    base: dict[str, Any]
    if f.type == FieldType.STRING:
        base = {"type": "string"}
        if f.enum:
            base["enum"] = f.enum
    elif f.type == FieldType.NUMBER:
        base = {"type": "number"}
    elif f.type == FieldType.BOOLEAN:
        base = {"type": "boolean"}
    elif f.type == FieldType.DATE:
        base = {"type": "string", "format": "date"}
    elif f.type == FieldType.ARRAY_OBJECT:
        children = f.children or []
        base = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {c.name: _field_jsonschema(c) for c in children},
            },
        }
    else:
        base = {"type": "string"}
    base["description"] = f.description
    return base


def _build_field_instructions(schema: list[SchemaField]) -> str:
    lines = ["Per-field instructions:"]
    for i, f in enumerate(schema, start=1):
        suffix = ""
        if f.examples:
            suffix += f" Examples: {', '.join(f.examples)}."
        if f.enum:
            suffix += f" Allowed values: {', '.join(f.enum)}."
        lines.append(f"{i}. `{f.name}` ({f.type.value}): {f.description}{suffix}")
    return "\n".join(lines)


async def extract_one(
    workspace: Path,
    project_id: str,
    doc_id: str,
    *,
    provider: Provider,
    model_id: str | None = None,
) -> dict[str, Any]:
    schema = [SchemaField(**f) for f in json.loads(schema_path(workspace, project_id).read_text())]
    if not schema:
        raise ValueError("project has empty schema; nothing to extract")
    project = json.loads(project_json_path(workspace, project_id).read_text())
    mid = model_id or project["extract_model"]

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

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_extract.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/extract.py backend/tests/unit/test_tool_extract.py
git commit -m "feat(tools): extract_one with response_schema + _evidence trace"
```

---

### Task 19: extract_batch tool (foreground for M1)

**Files:**
- Modify: `backend/app/tools/extract.py` — add `extract_batch`
- Modify: `backend/tests/unit/test_tool_extract.py` — add tests

For M1 we run extract_batch synchronously (sequential or parallel) inside a tool call — no JobRunner yet (that's M2). The tool returns a summary of per-doc success/failure.

- [ ] **Step 1: Append failing test**

```python
# (append to backend/tests/unit/test_tool_extract.py)
from app.tools.extract import extract_batch


async def test_extract_batch_runs_all_docs(workspace: Path, stub_provider: AsyncMock) -> None:
    pid = await create_project(workspace, name="x")
    pdf = _FIXTURE.read_bytes()
    d1 = await upload_doc(workspace, pid, pdf, "a.pdf")
    d2 = await upload_doc(workspace, pid, pdf, "b.pdf")
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "X", "total_amount": 1.0}], "_evidence": [{"invoice_no": 1, "total_amount": 1}]}
    )

    summary = await extract_batch(workspace, pid, [d1, d2], provider=stub_provider, concurrency=2)
    assert summary["ok_count"] == 2
    assert summary["err_count"] == 0
    assert set(summary["per_doc"].keys()) == {d1, d2}


async def test_extract_batch_records_per_doc_errors(workspace: Path, stub_provider: AsyncMock) -> None:
    pid = await create_project(workspace, name="x")
    pdf = _FIXTURE.read_bytes()
    d1 = await upload_doc(workspace, pid, pdf, "a.pdf")
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    stub_provider.extract.side_effect = ValueError("boom")
    summary = await extract_batch(workspace, pid, [d1], provider=stub_provider)
    assert summary["ok_count"] == 0
    assert summary["err_count"] == 1
    assert summary["per_doc"][d1]["ok"] is False
    assert "boom" in summary["per_doc"][d1]["error"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/unit/test_tool_extract.py -v`
Expected: ImportError on extract_batch.

- [ ] **Step 3: Implement extract_batch**

Append to `backend/app/tools/extract.py`:

```python
import asyncio
from typing import Any as _Any


async def extract_batch(
    workspace: Path,
    project_id: str,
    doc_ids: list[str],
    *,
    provider: Provider,
    model_id: str | None = None,
    concurrency: int = 4,
) -> dict[str, _Any]:
    sem = asyncio.Semaphore(concurrency)
    per_doc: dict[str, dict[str, _Any]] = {}

    async def _run_one(did: str) -> None:
        async with sem:
            try:
                await extract_one(workspace, project_id, did, provider=provider, model_id=model_id)
                per_doc[did] = {"ok": True}
            except Exception as e:  # noqa: BLE001
                per_doc[did] = {"ok": False, "error": str(e)}

    await asyncio.gather(*(_run_one(d) for d in doc_ids))
    ok = sum(1 for v in per_doc.values() if v["ok"])
    err = sum(1 for v in per_doc.values() if not v["ok"])
    return {"ok_count": ok, "err_count": err, "per_doc": per_doc}
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_extract.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/extract.py backend/tests/unit/test_tool_extract.py
git commit -m "feat(tools): extract_batch with per-doc error capture"
```

---

## Phase 5 — Skill registration & MCP server

### Task 20: emerge-extractor SKILL.md

**Files:**
- Create: `backend/app/skills/__init__.py`
- Create: `backend/app/skills/emerge_extractor.md`

- [ ] **Step 1: Implement skill loader**

```python
# backend/app/skills/__init__.py
from pathlib import Path

_SKILLS_DIR = Path(__file__).parent


def load_skill(name: str) -> str:
    p = _SKILLS_DIR / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"skill not found: {name}")
    return p.read_text(encoding="utf-8")
```

- [ ] **Step 2: Write SKILL.md**

```markdown
<!-- backend/app/skills/emerge_extractor.md -->
# emerge-extractor (default)

You are the emerge agent. You help users build, run, and refine document
extraction APIs. Each project is a folder under `workspace/{project_id}/`.

## Discipline (red lines — never violate)

- The ONLY knowledge channel into the extraction model is each field's
  `description` text and `global_notes.md`. NEVER inject example I/O pairs,
  image few-shot, or hidden heuristics.
- NEVER store, request, or use bbox / coordinate metadata. The only spatial
  data that exists is `_evidence` page integers.
- Output contract for extraction: top-level `array` of `object`,
  snake_case English keys, omit fields when uncertain (no hallucinated
  null/empty placeholders).
- AutoResearch never auto-promotes — that's a separate skill (loaded via
  /improve). You do not optimize schemas yourself.
- `schema.json` is mutated only via the `write_schema` tool.

## Risk gates (ALWAYS confirm with user before invoking)

- Structural schema changes: `write_schema` with `allow_structural=true`
  when adding, removing, renaming, or retyping a field. Pure description-text
  edits do NOT require confirmation.
- `delete_doc`.
- Accepting an autoresearch candidate (overwriting `schema.json`).
- Cancelling a job.

## Free-form intent routing (no slash command)

When the user types free-form text:

1. If no project is selected and the user attaches docs + intent
   ("提取这些发票核心信息"), bootstrap a project end-to-end:
   `create_project` → `upload_doc × N` → `derive_schema(sample=3, intent=...)`
   → `write_schema(allow_structural=true, reason="initial bootstrap")` →
   `extract_batch`. Summarize results in chat.
2. If a project is selected and the user describes a needed schema change
   (e.g. "客户反馈缺 BRN 字段"), propose a diff, present it to the user,
   wait for confirmation before `write_schema(allow_structural=true)`.
3. If the user edits description text only ("把 document_type 描述改为…"),
   apply directly via `write_schema` (no allow_structural needed) — no gate.

## Slash commands handled by this skill

- `/new` — start a new project (will prompt for sample docs / intent).
- `/extract` — run `extract_batch` over all (or specified) docs.
- `/eval` (M2+) — `score`.
- `/review` (M2+) — opens review mode on first un-reviewed doc.
- `/feedback` — case2 entry: take a complaint and propose schema diff.

For `/improve` and `/publish`, you do NOT execute — they load separate
skills with their own discipline.

## When tools fail

A tool returns `{ok: false, error: {error_code, error_message_en}}`.
Surface the error to the user in chat (Chinese OK), suggest a corrective
action, and do not proceed silently.

## When in doubt

Prefer doing the action and showing the user the result. Ask only when
intent is genuinely ambiguous or when a risk gate is triggered.
```

- [ ] **Step 3: Verify skill loads**

Run: `cd backend && uv run python -c "from app.skills import load_skill; print(load_skill('emerge_extractor')[:60])"`
Expected: starts with `<!-- backend/app/skills/emerge_extractor.md -->\n# emerge-extractor`

- [ ] **Step 4: Commit**

```bash
git add backend/app/skills
git commit -m "feat(skills): emerge-extractor SKILL.md (default)"
```

---

### Task 21: MCP tool registration

**Files:**
- Modify: `backend/app/tools/__init__.py` — register all `@tool` functions and build MCP server
- Test: `backend/tests/unit/test_tool_registration.py`

The Anthropic Agent SDK provides a `create_sdk_mcp_server` factory and `@tool` decorator. We expose a `build_emerge_mcp(workspace, provider)` function that returns the SDK MCP server with all tools bound to the right workspace + provider.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_tool_registration.py
from pathlib import Path
from unittest.mock import AsyncMock

from app.tools import build_emerge_mcp


def test_build_emerge_mcp_lists_tools(workspace: Path, stub_provider: AsyncMock) -> None:
    server = build_emerge_mcp(workspace=workspace, provider=stub_provider)
    # Server should have at least these tool names registered
    names = {t.name for t in server.tools}  # type: ignore[attr-defined]
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
    }
    assert expected.issubset(names), names
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`
Expected: ImportError on `build_emerge_mcp`.

- [ ] **Step 3: Implement registration**

```python
# backend/app/tools/__init__.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from app.provider.base import Provider
from app.schemas.schema_field import SchemaField
from app.tools import docs as docs_mod
from app.tools import projects as projects_mod
from app.tools import schema as schema_mod
from app.tools import extract as extract_mod


def build_emerge_mcp(workspace: Path, provider: Provider) -> Any:
    """Construct an in-process MCP server exposing all emerge tools.

    Each tool closes over the workspace path and provider instance so the
    SDK-driven agent doesn't need to know either.
    """

    @tool("create_project", "Create a new extraction project.", {"name": str})
    async def t_create_project(args: dict[str, Any]) -> dict[str, Any]:
        pid = await projects_mod.create_project(workspace, name=args["name"])
        return {"content": [{"type": "text", "text": pid}]}

    @tool("list_projects", "List all projects in the workspace.", {})
    async def t_list_projects(_args: dict[str, Any]) -> dict[str, Any]:
        items = await projects_mod.list_projects(workspace)
        return {"content": [{"type": "text", "text": str(items)}]}

    @tool(
        "upload_doc",
        "Register a previously-uploaded doc by its temp path. Returns doc_id. "
        "(For chat-driven uploads, the user uploads via the upload endpoint and the "
        "doc_ids are passed to this tool only when triggered programmatically.)",
        {"project_id": str, "tmp_path": str, "filename": str},
    )
    async def t_upload_doc(args: dict[str, Any]) -> dict[str, Any]:
        data = Path(args["tmp_path"]).read_bytes()
        did = await docs_mod.upload_doc(workspace, args["project_id"], data, args["filename"])
        return {"content": [{"type": "text", "text": did}]}

    @tool("list_docs", "List documents in a project.", {"project_id": str})
    async def t_list_docs(args: dict[str, Any]) -> dict[str, Any]:
        items = await docs_mod.list_docs(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": str(items)}]}

    @tool(
        "pdf_render_page",
        "Render a PDF page as PNG; returns the path.",
        {"project_id": str, "doc_id": str, "page": int},
    )
    async def t_pdf_render_page(args: dict[str, Any]) -> dict[str, Any]:
        p = await docs_mod.pdf_render_page(workspace, args["project_id"], args["doc_id"], page=args["page"])
        return {"content": [{"type": "text", "text": str(p)}]}

    @tool(
        "derive_schema",
        "Propose a schema from sample documents and a user intent.",
        {"project_id": str, "sample_doc_ids": list, "intent": str},
    )
    async def t_derive_schema(args: dict[str, Any]) -> dict[str, Any]:
        fields = await schema_mod.derive_schema(
            workspace,
            args["project_id"],
            sample_doc_ids=args["sample_doc_ids"],
            intent=args["intent"],
            provider=provider,
        )
        return {"content": [{"type": "text", "text": str([f.model_dump(mode='json') for f in fields])}]}

    @tool("read_schema", "Read the current schema for a project.", {"project_id": str})
    async def t_read_schema(args: dict[str, Any]) -> dict[str, Any]:
        fields = await schema_mod.read_schema(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": str([f.model_dump(mode='json') for f in fields])}]}

    @tool(
        "write_schema",
        "Write a new schema. Set allow_structural=true to add/remove/rename/retype fields.",
        {"project_id": str, "schema": list, "reason": str, "allow_structural": bool},
    )
    async def t_write_schema(args: dict[str, Any]) -> dict[str, Any]:
        fields = [SchemaField(**f) for f in args["schema"]]
        await schema_mod.write_schema(
            workspace,
            args["project_id"],
            fields,
            reason=args["reason"],
            allow_structural=args.get("allow_structural", False),
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "extract_one",
        "Extract from a single document.",
        {"project_id": str, "doc_id": str},
    )
    async def t_extract_one(args: dict[str, Any]) -> dict[str, Any]:
        out = await extract_mod.extract_one(workspace, args["project_id"], args["doc_id"], provider=provider)
        return {"content": [{"type": "text", "text": str(out)}]}

    @tool(
        "extract_batch",
        "Extract over a list of documents (foreground).",
        {"project_id": str, "doc_ids": list},
    )
    async def t_extract_batch(args: dict[str, Any]) -> dict[str, Any]:
        summary = await extract_mod.extract_batch(workspace, args["project_id"], args["doc_ids"], provider=provider)
        return {"content": [{"type": "text", "text": str(summary)}]}

    return create_sdk_mcp_server(
        name="emerge_tools",
        version="0.0.1",
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
        ],
    )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_registration.py -v`
Expected: 1 passed.

(If the SDK's tool list attribute differs from `.tools`, the test asserts an attribute we don't control — adjust the assertion to whichever attribute the SDK exposes, e.g. `server.tool_handlers.keys()`. Re-check via `python -c "import claude_agent_sdk; help(claude_agent_sdk.create_sdk_mcp_server)"` if needed.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/__init__.py backend/tests/unit/test_tool_registration.py
git commit -m "feat(tools): build_emerge_mcp registers all tools as SDK MCP"
```

---

## Phase 6 — Chat service & SSE

### Task 22: Chat log writer

**Files:**
- Create: `backend/app/chat/__init__.py`
- Create: `backend/app/chat/log.py`
- Test: `backend/tests/unit/test_chat_log.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_chat_log.py
import json
from pathlib import Path

from app.chat.log import append_event
from app.tools.projects import create_project


async def test_append_event_writes_one_line(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_test"
    await append_event(workspace, pid, cid, {"type": "user", "text": "hi"})
    log = workspace / pid / "chats" / f"{cid}.jsonl"
    lines = log.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"type": "user", "text": "hi"}


async def test_append_multiple_events(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_test"
    await append_event(workspace, pid, cid, {"type": "user", "text": "hi"})
    await append_event(workspace, pid, cid, {"type": "agent", "text": "hello"})
    lines = (workspace / pid / "chats" / f"{cid}.jsonl").read_text().splitlines()
    assert len(lines) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/unit/test_chat_log.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement chat log**

```python
# backend/app/chat/__init__.py
# (empty)
```

```python
# backend/app/chat/log.py
import asyncio
import json
from pathlib import Path
from typing import Any

from app.workspace.paths import chats_dir


_log_lock = asyncio.Lock()


async def append_event(
    workspace: Path,
    project_id: str,
    chat_id: str,
    event: dict[str, Any],
) -> None:
    cdir = chats_dir(workspace, project_id)
    cdir.mkdir(parents=True, exist_ok=True)
    log_path = cdir / f"{chat_id}.jsonl"
    line = json.dumps(event, ensure_ascii=False) + "\n"
    async with _log_lock:
        # Append-only, JSONL, no atomic rename (a partial trailing line is recoverable).
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_chat_log.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat backend/tests/unit/test_chat_log.py
git commit -m "feat(chat): append-only JSONL chat log"
```

---

### Task 23: SSE event encoder

**Files:**
- Create: `backend/app/chat/stream.py`
- Test: `backend/tests/unit/test_chat_stream.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_chat_stream.py
from app.chat.stream import sse_event


def test_sse_event_basic() -> None:
    out = sse_event("agent_text", {"text": "hello"})
    assert out == 'event: agent_text\ndata: {"text": "hello"}\n\n'


def test_sse_event_multiline_text_safe() -> None:
    out = sse_event("agent_text", {"text": "line1\nline2"})
    # JSON encodes the newline; SSE structure not broken
    assert "\\n" in out
    assert out.endswith("\n\n")


def test_sse_event_unicode() -> None:
    out = sse_event("agent_text", {"text": "你好"})
    assert "你好" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/unit/test_chat_stream.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement stream**

```python
# backend/app/chat/stream.py
import json
from typing import Any


def sse_event(event_type: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_chat_stream.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/stream.py backend/tests/unit/test_chat_stream.py
git commit -m "feat(chat): SSE event encoder"
```

---

### Task 24: ChatService wrapping ClaudeSDKClient

**Files:**
- Create: `backend/app/chat/service.py`
- Test: `backend/tests/integration/test_chat_service.py`

The SDK is exercised in integration tests rather than unit tests; we prove the wiring (skill loaded, MCP attached) compiles and starts. End-to-end LLM behaviour is in the `LLM smoke` test layer, not here.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_chat_service.py
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.chat.service import ChatService


def test_chat_service_constructs(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    assert svc.workspace == workspace
    assert svc.agent_model == "claude-sonnet-4-6"
    # Skill content present in system prompt
    assert "emerge-extractor" in svc.system_prompt
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/integration/test_chat_service.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement ChatService**

```python
# backend/app/chat/service.py
from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from app.chat.log import append_event
from app.chat.stream import sse_event
from app.provider.base import Provider
from app.skills import load_skill
from app.tools import build_emerge_mcp


_DENY_PERMISSIONS = [
    "Read(.env)",
    "Read(.env.*)",
    "Read(/secrets/**)",
    "Read(/*.pem)",
    "Read(/*.key)",
    "Bash(printenv)",
    "Bash(export)",
]


class ChatService:
    def __init__(
        self,
        *,
        workspace: Path,
        provider: Provider,
        agent_model: str = "claude-sonnet-4-6",
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self.agent_model = agent_model
        self.system_prompt = load_skill("emerge_extractor")
        self.mcp_server = build_emerge_mcp(workspace=workspace, provider=provider)

    def _build_options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            system_prompt=self.system_prompt,
            mcp_servers={"emerge_tools": self.mcp_server},
            model=self.agent_model,
            permissions={"deny": _DENY_PERMISSIONS},
            max_turns=20,
        )

    async def chat_turn(
        self,
        *,
        project_id: str,
        chat_id: str,
        user_message: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Yields SSE-encoded strings; caller passes them through to the response."""
        await append_event(self.workspace, project_id, chat_id, {"type": "user", "text": user_message})
        yield sse_event("user_acknowledged", {"text": user_message})

        prompt = user_message
        if attachments:
            paths = ", ".join(a.get("filename", "?") for a in attachments)
            prompt = f"{user_message}\n\n[attachments: {paths}]"

        options = self._build_options()
        try:
            async with ClaudeSDKClient(options=options) as client:
                async for event in client.query(prompt):
                    # The SDK event API surface may evolve; we adapt minimally:
                    etype = getattr(event, "type", "agent_text")
                    payload: dict[str, Any] = {}
                    if hasattr(event, "text"):
                        payload["text"] = event.text
                    elif hasattr(event, "tool_name"):
                        payload["tool_name"] = event.tool_name
                        payload["tool_input"] = getattr(event, "input", None)
                        payload["tool_result"] = getattr(event, "result", None)
                    else:
                        payload["raw"] = repr(event)
                    await append_event(
                        self.workspace, project_id, chat_id, {"type": etype, **payload}
                    )
                    yield sse_event(etype, payload)
        except Exception as e:  # noqa: BLE001
            err = {"error_code": "agent_failure", "error_message_en": str(e)}
            await append_event(self.workspace, project_id, chat_id, {"type": "error", **err})
            yield sse_event("error", err)
        finally:
            yield sse_event("turn_end", {})
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_chat_service.py -v`
Expected: 1 passed.

(The SDK's actual event type names and attributes may differ in your installed version. If the integration smoke later fails, run `uv run python -c "from claude_agent_sdk import ClaudeSDKClient; help(ClaudeSDKClient)"` to inspect; the `etype/payload` mapping in `chat_turn` is the only place to adjust.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/service.py backend/tests/integration/test_chat_service.py
git commit -m "feat(chat): ChatService binds skill + tools and streams SSE events"
```

---

## Phase 7 — API routes

### Task 25: POST /lab/chat (SSE)

**Files:**
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/routes/__init__.py`
- Create: `backend/app/api/routes/chat.py`
- Modify: `backend/app/main.py` — mount router and lifespan
- Test: `backend/tests/integration/test_lab_chat_flow.py`

For the integration test we mock the SDK at module level: SSE flow must not actually call Anthropic. The test asserts the wire format (event names, ordering) given a stub `ChatService`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_lab_chat_flow.py
import json
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client_with_stub_chat(workspace: Path) -> TestClient:
    return TestClient(app)


async def _fake_chat_turn(*args, **kwargs) -> AsyncIterator[str]:
    yield 'event: user_acknowledged\ndata: {"text": "hi"}\n\n'
    yield 'event: agent_text\ndata: {"text": "hello!"}\n\n'
    yield 'event: turn_end\ndata: {}\n\n'


def test_lab_chat_streams_sse(client_with_stub_chat: TestClient) -> None:
    with patch("app.api.routes.chat._get_chat_service") as gcs:
        svc = AsyncMock()
        svc.chat_turn = _fake_chat_turn
        gcs.return_value = svc
        body = {"project_id": "p_x", "chat_id": "c_x", "user_message": "hi"}
        with client_with_stub_chat.stream("POST", "/lab/chat", json=body) as resp:
            assert resp.status_code == 200
            text = b"".join(resp.iter_bytes()).decode()
    assert "event: user_acknowledged" in text
    assert "event: agent_text" in text
    assert "event: turn_end" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/integration/test_lab_chat_flow.py -v`
Expected: 404 — `/lab/chat` not yet mounted.

- [ ] **Step 3: Implement the route**

```python
# backend/app/api/__init__.py
# (empty)
```

```python
# backend/app/api/routes/__init__.py
# (empty)
```

```python
# backend/app/api/routes/chat.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.chat.service import ChatService
from app.config import get_settings
from app.provider.anthropic import AnthropicProvider


router = APIRouter()


class ChatBody(BaseModel):
    project_id: str
    chat_id: str
    user_message: str
    attachments: list[dict[str, Any]] | None = None


def _get_chat_service() -> ChatService:
    settings = get_settings()
    provider = AnthropicProvider(api_key=settings.anthropic_api_key)
    return ChatService(
        workspace=settings.workspace_root,
        provider=provider,
        agent_model=settings.default_agent_model,
    )


@router.post("/lab/chat")
async def lab_chat(body: ChatBody) -> EventSourceResponse:
    svc = _get_chat_service()

    async def gen():
        async for chunk in svc.chat_turn(
            project_id=body.project_id,
            chat_id=body.chat_id,
            user_message=body.user_message,
            attachments=body.attachments,
        ):
            # sse_starlette wants {event, data} dicts; we already encoded them.
            # Strip the "event: x\ndata: y\n\n" wrapper so sse_starlette can re-emit.
            lines = chunk.strip().split("\n")
            event_line = next((ln for ln in lines if ln.startswith("event:")), "event: message")
            data_line = next((ln for ln in lines if ln.startswith("data:")), "data: {}")
            yield {
                "event": event_line.split(":", 1)[1].strip(),
                "data": data_line.split(":", 1)[1].strip(),
            }

    return EventSourceResponse(gen())
```

```python
# backend/app/main.py — replace existing content
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat as chat_route
from app.config import get_settings


settings = get_settings()
app = FastAPI(title="emerge", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_route.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration -v`
Expected: 3 passed (healthz + chat_service + chat_flow).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api backend/app/main.py backend/tests/integration/test_lab_chat_flow.py
git commit -m "feat(api): POST /lab/chat with SSE streaming"
```

---

### Task 26: POST /lab/upload

**Files:**
- Create: `backend/app/api/routes/upload.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_lab_upload.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_lab_upload.py
import io
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project


async def test_upload_pdf(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    files = {"file": ("a.pdf", io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "application/pdf")}
    r = client.post(f"/lab/projects/{pid}/upload", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["doc_id"].startswith("d_")
    assert (workspace / pid / "docs" / f"{body['doc_id']}.pdf").exists()


def test_upload_rejects_unsupported_extension() -> None:
    client = TestClient(app)
    files = {"file": ("a.docx", io.BytesIO(b"x"), "application/vnd.docx")}
    r = client.post("/lab/projects/p_zzz/upload", files=files)
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/integration/test_lab_upload.py -v`
Expected: 404 / NotImplementedError.

- [ ] **Step 3: Implement the route**

```python
# backend/app/api/routes/upload.py
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import get_settings
from app.tools.docs import upload_doc


router = APIRouter()


@router.post("/lab/projects/{project_id}/upload")
async def upload(project_id: str, file: UploadFile = File(...)) -> dict[str, str]:
    settings = get_settings()
    data = await file.read()
    try:
        did = await upload_doc(settings.workspace_root, project_id, data, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"doc_id": did}
```

Modify `backend/app/main.py` — append router include:
```python
from app.api.routes import upload as upload_route
app.include_router(upload_route.router)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_lab_upload.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/upload.py backend/app/main.py backend/tests/integration/test_lab_upload.py
git commit -m "feat(api): POST /lab/projects/{pid}/upload"
```

---

### Task 27: GET /lab/projects + GET /lab/projects/{pid}

**Files:**
- Create: `backend/app/api/routes/projects.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_lab_projects.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_lab_projects.py
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project


async def test_list_projects_returns_created(workspace: Path) -> None:
    pid = await create_project(workspace, name="inv-MY")
    client = TestClient(app)
    r = client.get("/lab/projects")
    assert r.status_code == 200
    items = r.json()
    assert any(it["project_id"] == pid for it in items)


async def test_get_one_project(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}")
    assert r.status_code == 200
    assert r.json()["name"] == "x"


def test_get_unknown_project_404() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_doesnotexist")
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/integration/test_lab_projects.py -v`
Expected: 404 not yet mounted.

- [ ] **Step 3: Implement**

```python
# backend/app/api/routes/projects.py
import json

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.tools.projects import list_projects
from app.workspace.paths import project_json_path


router = APIRouter()


@router.get("/lab/projects")
async def get_projects() -> list[dict]:
    settings = get_settings()
    return await list_projects(settings.workspace_root)


@router.get("/lab/projects/{project_id}")
async def get_project(project_id: str) -> dict:
    settings = get_settings()
    pj = project_json_path(settings.workspace_root, project_id)
    if not pj.exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    blob = json.loads(pj.read_text())
    return {"project_id": project_id, **blob}
```

Modify `backend/app/main.py`:
```python
from app.api.routes import projects as projects_route
app.include_router(projects_route.router)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_lab_projects.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/projects.py backend/app/main.py backend/tests/integration/test_lab_projects.py
git commit -m "feat(api): GET /lab/projects (list + detail)"
```

---

### Task 28: GET PDF page render route

**Files:**
- Create: `backend/app/api/routes/docs.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_lab_docs_pages.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_lab_docs_pages.py
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.docs import upload_doc
from app.tools.projects import create_project


_FIXTURE = Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf"


async def test_get_page_returns_png(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf")
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/docs/{did}/pages/1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_get_page_404_for_missing(workspace: Path) -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_x/docs/d_y/pages/1")
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/integration/test_lab_docs_pages.py -v`
Expected: 404 not mounted.

- [ ] **Step 3: Implement**

```python
# backend/app/api/routes/docs.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings
from app.tools.docs import pdf_render_page


router = APIRouter()


@router.get("/lab/projects/{project_id}/docs/{doc_id}/pages/{page}")
async def get_page(project_id: str, doc_id: str, page: int) -> FileResponse:
    settings = get_settings()
    try:
        path = await pdf_render_page(settings.workspace_root, project_id, doc_id, page=page)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(path, media_type="image/png")
```

Modify `backend/app/main.py`:
```python
from app.api.routes import docs as docs_route
app.include_router(docs_route.router)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_lab_docs_pages.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run all backend tests**

Run: `cd backend && uv run pytest -v`
Expected: all green; ~50+ tests passing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/docs.py backend/app/main.py backend/tests/integration/test_lab_docs_pages.py
git commit -m "feat(api): GET /lab/projects/{pid}/docs/{did}/pages/{p}"
```

---

## Phase 8 — Frontend foundation

### Task 29: Frontend project scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/index.css`

- [ ] **Step 1: package.json**

```json
{
  "name": "emerge-frontend",
  "private": true,
  "type": "module",
  "version": "0.0.1",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "e2e": "playwright test"
  },
  "dependencies": {
    "@radix-ui/react-dialog": "^1.1.2",
    "@radix-ui/react-dropdown-menu": "^2.1.2",
    "@radix-ui/react-tooltip": "^1.1.4",
    "lucide-react": "^0.456.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^6.27.0",
    "zustand": "^5.0.1"
  },
  "devDependencies": {
    "@playwright/test": "^1.48.2",
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/node": "^22.9.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.3",
    "autoprefixer": "^10.4.20",
    "jsdom": "^25.0.1",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.14",
    "typescript": "^5.6.3",
    "vite": "^5.4.10",
    "vitest": "^2.1.4"
  }
}
```

- [ ] **Step 2: vite.config.ts**

```ts
// frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/lab': 'http://localhost:8000',
      '/v1': 'http://localhost:8000',
      '/healthz': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    globals: true,
  },
})
```

- [ ] **Step 3: tsconfig files**

```json
// frontend/tsconfig.json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.node.json" },
    { "path": "./tsconfig.app.json" }
  ]
}
```

```json
// frontend/tsconfig.node.json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

```json
// frontend/tsconfig.app.json
{
  "compilerOptions": {
    "composite": true,
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "skipLibCheck": true,
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "tests"]
}
```

- [ ] **Step 4: tailwind + postcss + index.html + entry**

```js
// frontend/tailwind.config.js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--bg-canvas)',
        surface: 'var(--bg-surface)',
        subtle: 'var(--bg-subtle)',
        'fg-primary': 'var(--fg-primary)',
        'fg-secondary': 'var(--fg-secondary)',
        'fg-muted': 'var(--fg-muted)',
        'accent-primary': 'var(--accent-primary)',
        'accent-info': 'var(--accent-info)',
        'accent-success': 'var(--accent-success)',
        'accent-danger': 'var(--accent-danger)',
      },
      fontFamily: {
        heading: ['Poppins', 'Arial', 'sans-serif'],
        body: ['Lora', 'Georgia', 'serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
```

```js
// frontend/postcss.config.js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
}
```

```html
<!-- frontend/index.html -->
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>emerge</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

```tsx
// frontend/src/main.tsx
import React from 'react'
import ReactDOM from 'react-dom/client'

import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

```css
/* frontend/src/index.css */
@import './theme/tokens.css';

@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root {
  height: 100%;
  background: var(--bg-canvas);
  color: var(--fg-primary);
  font-family: var(--font-body, Lora, Georgia, serif);
}
```

- [ ] **Step 5: Install and verify scaffold**

Run:
```bash
cd frontend && npm install && npm run build 2>&1 | head -20
```
Expected: build attempt — may fail on missing `App.tsx` or `theme/tokens.css`; that's OK, we add them next.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts \
  frontend/tsconfig.json frontend/tsconfig.app.json frontend/tsconfig.node.json \
  frontend/tailwind.config.js frontend/postcss.config.js \
  frontend/index.html frontend/src/main.tsx frontend/src/index.css
git commit -m "chore(frontend): vite + react 19 + ts + tailwind scaffold"
```

---

### Task 30: Theme tokens

**Files:**
- Create: `frontend/src/theme/tokens.css`

- [ ] **Step 1: Implement tokens**

```css
/* frontend/src/theme/tokens.css */
:root {
  --bg-canvas: #faf9f5;
  --bg-surface: #ffffff;
  --bg-subtle: #e8e6dc;
  --fg-primary: #141413;
  --fg-secondary: #6b6a64;
  --fg-muted: #b0aea5;
  --accent-primary: #d97757;
  --accent-info: #6a9bcc;
  --accent-success: #788c5d;
  --accent-danger: #b53a2b;
  --font-heading: 'Poppins', Arial, sans-serif;
  --font-body: 'Lora', Georgia, serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg-canvas: #141413;
    --bg-surface: #1f1e1c;
    --bg-subtle: #2a2926;
    --fg-primary: #faf9f5;
    --fg-secondary: #d4d2c9;
    --fg-muted: #b0aea5;
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/theme/tokens.css
git commit -m "feat(frontend): Anthropic palette CSS-var tokens"
```

---

### Task 31: App shell — three-pane layout

**Files:**
- Create: `frontend/src/App.tsx`

- [ ] **Step 1: Write App with placeholder panes**

```tsx
// frontend/src/App.tsx
import ProjectList from './components/ProjectList/ProjectList'
import ChatPanel from './components/Chat/ChatPanel'
import DocPreview from './components/DocPreview/DocPreview'

export default function App() {
  return (
    <div className="grid grid-cols-[260px_1fr_360px] h-full bg-canvas text-fg-primary">
      <aside className="border-r border-subtle">
        <ProjectList />
      </aside>
      <main className="flex flex-col">
        <ChatPanel />
      </main>
      <aside className="border-l border-subtle">
        <DocPreview />
      </aside>
    </div>
  )
}
```

- [ ] **Step 2: Commit (component files come next; App now references them)**

```bash
git add frontend/src/App.tsx
git commit -m "feat(frontend): three-pane App shell"
```

---

### Task 32: Frontend tests setup + base API client

**Files:**
- Create: `frontend/tests/setup.ts`
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/sse.ts`
- Create: `frontend/src/lib/ids.ts`
- Create: `frontend/src/types/chat.ts`
- Create: `frontend/src/types/project.ts`

- [ ] **Step 1: Test setup**

```ts
// frontend/tests/setup.ts
import '@testing-library/jest-dom/vitest'
```

- [ ] **Step 2: API client**

```ts
// frontend/src/lib/api.ts
export interface Project {
  project_id: string
  name: string
  project_type: string
  active_version_id: string | null
}

const API = '' // same origin via vite proxy

export async function listProjects(): Promise<Project[]> {
  const r = await fetch(`${API}/lab/projects`)
  if (!r.ok) throw new Error(`listProjects ${r.status}`)
  return r.json()
}

export async function uploadDoc(projectId: string, file: File): Promise<{ doc_id: string }> {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${API}/lab/projects/${projectId}/upload`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error(`upload ${r.status}`)
  return r.json()
}
```

- [ ] **Step 3: SSE client**

```ts
// frontend/src/lib/sse.ts
export interface SSEEvent {
  event: string
  data: unknown
}

export async function* streamSSE(url: string, init: RequestInit): AsyncGenerator<SSEEvent> {
  const resp = await fetch(url, init)
  if (!resp.ok || !resp.body) throw new Error(`SSE ${resp.status}`)
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const lines = block.split('\n')
      let event = 'message'
      let dataStr = ''
      for (const ln of lines) {
        if (ln.startsWith('event:')) event = ln.slice(6).trim()
        else if (ln.startsWith('data:')) dataStr = ln.slice(5).trim()
      }
      let data: unknown = dataStr
      try { data = JSON.parse(dataStr) } catch { /* keep string */ }
      yield { event, data }
    }
  }
}
```

- [ ] **Step 4: ID + types**

```ts
// frontend/src/lib/ids.ts
export function newChatId(): string {
  return 'c_' + crypto.randomUUID().replace(/-/g, '').slice(0, 12)
}
```

```ts
// frontend/src/types/chat.ts
export type ChatEvent =
  | { type: 'user'; text: string }
  | { type: 'agent_text'; text: string }
  | { type: 'tool_call'; tool_name: string; tool_input: unknown; tool_result: unknown; ok: boolean }
  | { type: 'error'; error_code: string; error_message_en: string }
  | { type: 'turn_end' }
```

```ts
// frontend/src/types/project.ts
export type { Project } from '../lib/api'
```

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/setup.ts frontend/src/lib frontend/src/types
git commit -m "feat(frontend): API client + SSE reader + chat/project types"
```

---

## Phase 9 — Frontend components

### Task 33: ProjectList + ProjectItem

**Files:**
- Create: `frontend/src/stores/projects.ts`
- Create: `frontend/src/components/ProjectList/ProjectList.tsx`
- Create: `frontend/src/components/ProjectList/ProjectItem.tsx`

- [ ] **Step 1: Store**

```ts
// frontend/src/stores/projects.ts
import { create } from 'zustand'

import { listProjects, type Project } from '../lib/api'

interface State {
  projects: Project[]
  selectedId: string | null
  loading: boolean
  refresh: () => Promise<void>
  select: (id: string | null) => void
}

export const useProjects = create<State>((set) => ({
  projects: [],
  selectedId: null,
  loading: false,
  refresh: async () => {
    set({ loading: true })
    try {
      const ps = await listProjects()
      set({ projects: ps, loading: false })
    } catch {
      set({ loading: false })
    }
  },
  select: (id) => set({ selectedId: id }),
}))
```

- [ ] **Step 2: Components**

```tsx
// frontend/src/components/ProjectList/ProjectList.tsx
import { useEffect } from 'react'
import { Plus } from 'lucide-react'

import { useProjects } from '../../stores/projects'
import ProjectItem from './ProjectItem'

export default function ProjectList() {
  const { projects, refresh, select, selectedId } = useProjects()
  useEffect(() => { void refresh() }, [refresh])

  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 font-heading text-sm uppercase tracking-wide text-fg-muted">
        Projects
      </header>
      <ul className="flex-1 overflow-auto">
        {projects.map(p => (
          <li key={p.project_id}>
            <ProjectItem
              project={p}
              selected={p.project_id === selectedId}
              onSelect={() => select(p.project_id)}
            />
          </li>
        ))}
      </ul>
      <button
        onClick={() => select(null)}
        className="m-3 inline-flex items-center gap-2 text-sm text-fg-secondary hover:text-fg-primary"
      >
        <Plus size={14} /> new
      </button>
    </div>
  )
}
```

```tsx
// frontend/src/components/ProjectList/ProjectItem.tsx
import type { Project } from '../../types/project'

interface Props {
  project: Project
  selected: boolean
  onSelect: () => void
}

export default function ProjectItem({ project, selected, onSelect }: Props) {
  return (
    <button
      onClick={onSelect}
      className={
        'w-full text-left px-4 py-2 transition-colors ' +
        (selected ? 'bg-subtle text-fg-primary' : 'text-fg-secondary hover:bg-subtle')
      }
    >
      <span className="font-mono text-sm">{project.name}</span>
      {project.active_version_id && (
        <span className="ml-2 text-xs text-accent-primary">▲{project.active_version_id}</span>
      )}
    </button>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/projects.ts frontend/src/components/ProjectList
git commit -m "feat(frontend): ProjectList + ProjectItem with Zustand store"
```

---

### Task 34: Chat store + ChatPanel + MessageList

**Files:**
- Create: `frontend/src/stores/chat.ts`
- Create: `frontend/src/components/Chat/ChatPanel.tsx`
- Create: `frontend/src/components/Chat/MessageList.tsx`

- [ ] **Step 1: Store**

```ts
// frontend/src/stores/chat.ts
import { create } from 'zustand'

import { newChatId } from '../lib/ids'
import { streamSSE } from '../lib/sse'
import type { ChatEvent } from '../types/chat'

interface State {
  chatId: string
  events: ChatEvent[]
  busy: boolean
  send: (projectId: string, message: string, attachments?: { filename: string }[]) => Promise<void>
  reset: () => void
}

export const useChat = create<State>((set, get) => ({
  chatId: newChatId(),
  events: [],
  busy: false,
  reset: () => set({ chatId: newChatId(), events: [] }),
  send: async (projectId, message, attachments) => {
    set(s => ({ events: [...s.events, { type: 'user', text: message }], busy: true }))
    try {
      for await (const ev of streamSSE('/lab/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          chat_id: get().chatId,
          user_message: message,
          attachments,
        }),
      })) {
        const e: ChatEvent = mapSse(ev.event, ev.data)
        if (e.type === 'turn_end') break
        set(s => ({ events: [...s.events, e] }))
      }
    } finally {
      set({ busy: false })
    }
  },
}))

function mapSse(event: string, data: unknown): ChatEvent {
  if (event === 'agent_text') return { type: 'agent_text', text: (data as { text: string }).text }
  if (event === 'tool_call') {
    const d = data as { tool_name: string; tool_input: unknown; tool_result: unknown; ok?: boolean }
    return {
      type: 'tool_call',
      tool_name: d.tool_name,
      tool_input: d.tool_input,
      tool_result: d.tool_result,
      ok: d.ok ?? true,
    }
  }
  if (event === 'error') {
    const d = data as { error_code: string; error_message_en: string }
    return { type: 'error', error_code: d.error_code, error_message_en: d.error_message_en }
  }
  if (event === 'turn_end') return { type: 'turn_end' }
  // Unknown event types fall through as agent_text with raw stringification.
  return { type: 'agent_text', text: typeof data === 'string' ? data : JSON.stringify(data) }
}
```

- [ ] **Step 2: ChatPanel + MessageList**

```tsx
// frontend/src/components/Chat/ChatPanel.tsx
import { useState } from 'react'

import { useProjects } from '../../stores/projects'
import { useChat } from '../../stores/chat'

import Composer from './Composer'
import MessageList from './MessageList'

export default function ChatPanel() {
  const { selectedId } = useProjects()
  const { events, send, busy } = useChat()
  const [pending, setPending] = useState<{ filename: string }[]>([])

  return (
    <div className="flex flex-col h-full">
      <header className="border-b border-subtle px-4 py-3 font-heading text-sm uppercase tracking-wide text-fg-muted">
        Chat
      </header>
      <div className="flex-1 overflow-auto">
        <MessageList events={events} />
      </div>
      <Composer
        disabled={busy}
        pending={pending}
        onAttach={(files) => setPending(p => [...p, ...files])}
        onSubmit={async (text) => {
          await send(selectedId ?? 'p_unset', text, pending)
          setPending([])
        }}
      />
    </div>
  )
}
```

```tsx
// frontend/src/components/Chat/MessageList.tsx
import type { ChatEvent } from '../../types/chat'

import ToolCallCard from './ToolCallCard'

interface Props { events: ChatEvent[] }

export default function MessageList({ events }: Props) {
  return (
    <div className="px-4 py-3 space-y-3 font-body">
      {events.map((e, i) => {
        if (e.type === 'user') {
          return <div key={i} className="text-fg-primary"><b>you:</b> {e.text}</div>
        }
        if (e.type === 'agent_text') {
          return <div key={i} className="text-fg-secondary"><b>agent:</b> {e.text}</div>
        }
        if (e.type === 'tool_call') {
          return <ToolCallCard key={i} event={e} />
        }
        if (e.type === 'error') {
          return (
            <div key={i} className="border-l-2 border-accent-danger px-3 py-2 bg-subtle text-sm">
              <span className="font-mono text-accent-danger">{e.error_code}</span>: {e.error_message_en}
            </div>
          )
        }
        return null
      })}
    </div>
  )
}
```

- [ ] **Step 3: Commit (Composer + ToolCallCard come next)**

```bash
git add frontend/src/stores/chat.ts frontend/src/components/Chat/ChatPanel.tsx frontend/src/components/Chat/MessageList.tsx
git commit -m "feat(frontend): chat store + ChatPanel + MessageList"
```

---

### Task 35: ToolCallCard with collapsible state

**Files:**
- Create: `frontend/src/components/Chat/ToolCallCard.tsx`
- Create: `frontend/tests/unit/ToolCallCard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/tests/unit/ToolCallCard.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ToolCallCard from '../../src/components/Chat/ToolCallCard'

describe('ToolCallCard', () => {
  it('shows tool name folded by default', () => {
    render(
      <ToolCallCard event={{ type: 'tool_call', tool_name: 'derive_schema', tool_input: { x: 1 }, tool_result: { y: 2 }, ok: true }} />
    )
    expect(screen.getByText('derive_schema')).toBeInTheDocument()
    expect(screen.queryByText(/"x"/)).not.toBeInTheDocument()
  })

  it('expands on click and reveals input/result', async () => {
    render(
      <ToolCallCard event={{ type: 'tool_call', tool_name: 'extract_one', tool_input: { x: 1 }, tool_result: { y: 2 }, ok: true }} />
    )
    await userEvent.click(screen.getByRole('button'))
    expect(screen.getByText(/"x": 1/)).toBeInTheDocument()
    expect(screen.getByText(/"y": 2/)).toBeInTheDocument()
  })

  it('renders red border when ok is false', () => {
    const { container } = render(
      <ToolCallCard event={{ type: 'tool_call', tool_name: 'extract_one', tool_input: {}, tool_result: { error_code: 'x' }, ok: false }} />
    )
    expect(container.querySelector('[data-ok="false"]')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test 2>&1 | tail -20`
Expected: 3 failing (component does not exist).

- [ ] **Step 3: Implement ToolCallCard**

```tsx
// frontend/src/components/Chat/ToolCallCard.tsx
import { useState } from 'react'
import { Check, X, ChevronDown, ChevronRight } from 'lucide-react'

import type { ChatEvent } from '../../types/chat'

interface Props { event: Extract<ChatEvent, { type: 'tool_call' }> }

export default function ToolCallCard({ event }: Props) {
  const [open, setOpen] = useState(false)
  const Icon = event.ok ? Check : X
  return (
    <button
      onClick={() => setOpen(o => !o)}
      data-ok={event.ok}
      className={
        'block w-full text-left border-l-2 px-3 py-2 bg-surface text-sm font-mono transition-colors ' +
        (event.ok ? 'border-accent-info' : 'border-accent-danger')
      }
    >
      <div className="flex items-center gap-2">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Icon size={14} className={event.ok ? 'text-accent-success' : 'text-accent-danger'} />
        <span>{event.tool_name}</span>
      </div>
      {open && (
        <pre className="mt-2 text-xs whitespace-pre-wrap text-fg-secondary">
{`input:
${JSON.stringify(event.tool_input, null, 2)}

result:
${JSON.stringify(event.tool_result, null, 2)}`}
        </pre>
      )}
    </button>
  )
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm run test`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/ToolCallCard.tsx frontend/tests/unit/ToolCallCard.test.tsx
git commit -m "feat(frontend): ToolCallCard collapsible folded/expanded states"
```

---

### Task 36: SlashMenu

**Files:**
- Create: `frontend/src/components/Chat/SlashMenu.tsx`

- [ ] **Step 1: Implement (no test — purely presentational; verified in e2e)**

```tsx
// frontend/src/components/Chat/SlashMenu.tsx
interface Item { command: string; hint: string }

const ITEMS: Item[] = [
  { command: '/new', hint: 'create a new project' },
  { command: '/extract', hint: 'run extraction over project docs' },
  { command: '/eval', hint: '(M2) score against reviewed examples' },
  { command: '/review', hint: '(M2) review predictions' },
  { command: '/improve', hint: '(M2) autoresearch loop' },
  { command: '/publish', hint: '(M3) freeze version + API key' },
  { command: '/feedback', hint: 'address client feedback' },
]

interface Props { query: string; onPick: (cmd: string) => void }

export default function SlashMenu({ query, onPick }: Props) {
  const filtered = ITEMS.filter(i => i.command.startsWith(query))
  if (filtered.length === 0) return null
  return (
    <ul className="absolute bottom-full mb-2 left-0 right-0 max-h-60 overflow-auto bg-surface border border-subtle rounded shadow font-mono text-sm">
      {filtered.map(i => (
        <li key={i.command}>
          <button
            type="button"
            onClick={() => onPick(i.command)}
            className="w-full text-left px-3 py-2 hover:bg-subtle"
          >
            <span className="text-accent-primary">{i.command}</span>{' '}
            <span className="text-fg-muted">{i.hint}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Chat/SlashMenu.tsx
git commit -m "feat(frontend): SlashMenu component"
```

---

### Task 37: Composer (input + drag-drop)

**Files:**
- Create: `frontend/src/components/Chat/Composer.tsx`
- Create: `frontend/tests/unit/Composer.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/tests/unit/Composer.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import Composer from '../../src/components/Chat/Composer'

describe('Composer', () => {
  it('calls onSubmit on Enter', async () => {
    const onSubmit = vi.fn()
    render(<Composer disabled={false} pending={[]} onAttach={() => {}} onSubmit={onSubmit} />)
    const input = screen.getByRole('textbox')
    await userEvent.type(input, 'hello')
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('hello')
  })

  it('shows slash menu when text starts with /', async () => {
    render(<Composer disabled={false} pending={[]} onAttach={() => {}} onSubmit={() => {}} />)
    const input = screen.getByRole('textbox')
    await userEvent.type(input, '/ext')
    expect(screen.getByText('/extract')).toBeInTheDocument()
  })

  it('shows pending attachment chips', () => {
    render(<Composer disabled={false} pending={[{ filename: 'a.pdf' }]} onAttach={() => {}} onSubmit={() => {}} />)
    expect(screen.getByText('a.pdf')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test 2>&1 | tail -20`
Expected: 3 failing.

- [ ] **Step 3: Implement Composer**

```tsx
// frontend/src/components/Chat/Composer.tsx
import { useState, type DragEvent, type KeyboardEvent } from 'react'

import SlashMenu from './SlashMenu'

interface Props {
  disabled: boolean
  pending: { filename: string }[]
  onAttach: (files: { filename: string }[]) => void
  onSubmit: (text: string) => void
}

export default function Composer({ disabled, pending, onAttach, onSubmit }: Props) {
  const [text, setText] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const showSlash = text.startsWith('/')

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (text.trim().length === 0) return
      onSubmit(text.trim())
      setText('')
    }
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    const files = Array.from(e.dataTransfer.files).map(f => ({ filename: f.name }))
    onAttach(files)
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={
        'relative border-t border-subtle p-3 ' +
        (dragOver ? 'bg-subtle' : 'bg-canvas')
      }
    >
      {showSlash && (
        <SlashMenu query={text} onPick={(c) => { setText(c + ' '); }} />
      )}
      {pending.length > 0 && (
        <ul className="flex flex-wrap gap-1 mb-2">
          {pending.map((a, i) => (
            <li key={i} className="text-xs px-2 py-1 bg-surface border border-subtle rounded">
              {a.filename}
            </li>
          ))}
        </ul>
      )}
      <textarea
        rows={2}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKey}
        placeholder="Drop docs here, or / for commands"
        className="w-full bg-surface text-fg-primary p-2 font-body resize-none focus:outline-none focus:ring-1 focus:ring-accent-primary"
      />
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm run test`
Expected: all (Composer + ToolCallCard) passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/Composer.tsx frontend/tests/unit/Composer.test.tsx
git commit -m "feat(frontend): Composer with slash menu + drag-drop chips"
```

---

### Task 38: SSE upload wiring (Composer drop → uploadDoc → attach to next chat send)

The Composer currently passes `{ filename }` chips to `pending`. We need to actually upload files when dropped, so the chat send carries server-side `doc_id`s.

**Files:**
- Modify: `frontend/src/components/Chat/ChatPanel.tsx`
- Modify: `frontend/src/lib/api.ts` — add `createProject`

- [ ] **Step 1: Add createProject helper**

Append to `frontend/src/lib/api.ts`:

```ts
export async function createProject(name: string): Promise<{ project_id: string }> {
  const r = await fetch(`/lab/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_id: 'p_unset',
      chat_id: 'c_bootstrap',
      user_message: `/new ${name}`,
    }),
  })
  if (!r.ok) throw new Error(`createProject ${r.status}`)
  // returns SSE; for M1 caller uses /lab/projects to refresh after the chat completes.
  return { project_id: 'pending' }
}
```

(Note: in M1 we let the agent do the actual project creation through the chat path. The frontend never POSTs `/lab/projects` directly to create — that's an agent decision.)

- [ ] **Step 2: Wire Composer drop → upload → push real chip data**

Replace `frontend/src/components/Chat/ChatPanel.tsx`:

```tsx
import { useState } from 'react'

import { uploadDoc } from '../../lib/api'
import { useProjects } from '../../stores/projects'
import { useChat } from '../../stores/chat'

import Composer from './Composer'
import MessageList from './MessageList'

interface AttachInfo { filename: string; doc_id?: string; pending?: boolean }

export default function ChatPanel() {
  const { selectedId, refresh: refreshProjects } = useProjects()
  const { events, send, busy } = useChat()
  const [pending, setPending] = useState<AttachInfo[]>([])

  async function attach(files: File[]) {
    if (!selectedId) {
      // Project not yet created: keep filenames pending; agent will create project then we upload.
      setPending(p => [...p, ...files.map(f => ({ filename: f.name, pending: true }))])
      return
    }
    setPending(p => [...p, ...files.map(f => ({ filename: f.name, pending: true }))])
    for (const f of files) {
      try {
        const { doc_id } = await uploadDoc(selectedId, f)
        setPending(p => p.map(x => x.filename === f.name ? { filename: f.name, doc_id, pending: false } : x))
      } catch {
        setPending(p => p.filter(x => x.filename !== f.name))
      }
    }
  }

  return (
    <div className="flex flex-col h-full">
      <header className="border-b border-subtle px-4 py-3 font-heading text-sm uppercase tracking-wide text-fg-muted">
        Chat
      </header>
      <div className="flex-1 overflow-auto">
        <MessageList events={events} />
      </div>
      <Composer
        disabled={busy}
        pending={pending.map(p => ({ filename: p.filename }))}
        onAttach={(files) => {
          // The Composer handler hands us filenames only; we need the actual File objects.
          // Re-hook Composer in a follow-up task to forward File[]. For now:
          void attach(files as unknown as File[])
        }}
        onSubmit={async (text) => {
          await send(selectedId ?? 'p_unset', text, pending.map(p => ({ filename: p.filename, doc_id: p.doc_id })))
          setPending([])
          await refreshProjects()
        }}
      />
    </div>
  )
}
```

- [ ] **Step 3: Update Composer to forward File[]**

Modify `frontend/src/components/Chat/Composer.tsx` — change `onAttach` signature to `(files: File[])` and pass `e.dataTransfer.files` directly:

Replace the relevant portion:
```tsx
interface Props {
  disabled: boolean
  pending: { filename: string }[]
  onAttach: (files: File[]) => void
  onSubmit: (text: string) => void
}
```
And in `handleDrop`:
```tsx
function handleDrop(e: DragEvent<HTMLDivElement>) {
  e.preventDefault()
  setDragOver(false)
  onAttach(Array.from(e.dataTransfer.files))
}
```

Update `Composer.test.tsx` accordingly:
```tsx
it('shows slash menu when text starts with /', async () => {
  render(<Composer disabled={false} pending={[]} onAttach={(_files) => {}} onSubmit={() => {}} />)
  const input = screen.getByRole('textbox')
  await userEvent.type(input, '/ext')
  expect(screen.getByText('/extract')).toBeInTheDocument()
})
```
(Other tests: replace `onAttach={() => {}}` with `onAttach={(_files: File[]) => {}}` to keep types consistent.)

Update `ChatPanel.tsx`'s `onAttach` to:
```tsx
onAttach={(files: File[]) => { void attach(files) }}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm run test`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/ChatPanel.tsx frontend/src/components/Chat/Composer.tsx frontend/src/lib/api.ts frontend/tests/unit/Composer.test.tsx
git commit -m "feat(frontend): drop file → upload → attach doc_id to chat send"
```

---

### Task 39: DocPreview placeholder

**Files:**
- Create: `frontend/src/components/DocPreview/DocPreview.tsx`

- [ ] **Step 1: Implement minimal placeholder**

```tsx
// frontend/src/components/DocPreview/DocPreview.tsx
export default function DocPreview() {
  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 font-heading text-sm uppercase tracking-wide text-fg-muted">
        Preview
      </header>
      <div className="flex-1 grid place-items-center text-fg-muted text-sm font-body">
        select a doc from chat to preview here
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Run dev server smoke**

Run:
```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000 &
cd frontend && npm run dev
```
Open http://localhost:5173/ in a browser. Expected: three-pane layout renders, projects list empty, chat composer visible. Type `/ext` — slash menu shows.

(Stop both servers with Ctrl-C / `kill %1`.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/DocPreview/DocPreview.tsx
git commit -m "feat(frontend): DocPreview placeholder"
```

---

## Phase 10 — End-to-end smoke

### Task 40: Playwright e2e — drag → first extract

This is a **stubbed** e2e test that asserts the wire flow: a dropped file triggers `/lab/projects/{pid}/upload`, the Composer Enter triggers `/lab/chat` with attachments, and the SSE stream renders user / agent / tool_call events. The Anthropic provider is not exercised — the backend route is stubbed in test mode.

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/tests/e2e/walking-skeleton.spec.ts`
- Create: `backend/app/api/routes/_test_stubs.py` — mounted only when `EMERGE_TEST_MODE=1`
- Modify: `backend/app/main.py` — conditional include

- [ ] **Step 1: Backend test stub**

```python
# backend/app/api/routes/_test_stubs.py
"""Test-only routes used by the Playwright e2e to avoid hitting Anthropic."""
import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse


router = APIRouter()


class StubBody(BaseModel):
    project_id: str
    chat_id: str
    user_message: str
    attachments: list[dict[str, Any]] | None = None


@router.post("/lab/chat")
async def stub_chat(body: StubBody) -> EventSourceResponse:
    async def gen():
        yield {"event": "user_acknowledged", "data": json.dumps({"text": body.user_message})}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_name": "create_project",
            "tool_input": {"name": "stubbed"},
            "tool_result": {"project_id": "p_stub"},
            "ok": True,
        })}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_name": "extract_batch",
            "tool_input": {"project_id": "p_stub", "doc_ids": []},
            "tool_result": {"ok_count": 0, "err_count": 0, "per_doc": {}},
            "ok": True,
        })}
        yield {"event": "agent_text", "data": json.dumps({
            "text": "Stub run complete. (M1 e2e — no real LLM call.)"
        })}
        yield {"event": "turn_end", "data": json.dumps({})}
    return EventSourceResponse(gen())
```

- [ ] **Step 2: Modify main.py to conditionally include the stub**

Modify `backend/app/main.py` — final form:

```python
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import docs as docs_route
from app.api.routes import projects as projects_route
from app.api.routes import upload as upload_route
from app.config import get_settings


settings = get_settings()
app = FastAPI(title="emerge", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.getenv("EMERGE_TEST_MODE") == "1":
    from app.api.routes import _test_stubs
    app.include_router(_test_stubs.router)
else:
    from app.api.routes import chat as chat_route
    app.include_router(chat_route.router)

app.include_router(upload_route.router)
app.include_router(projects_route.router)
app.include_router(docs_route.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 3: Playwright config**

```ts
// frontend/playwright.config.ts
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  use: { baseURL: 'http://localhost:5173' },
  webServer: [
    {
      command: 'EMERGE_TEST_MODE=1 EMERGE_WORKSPACE_ROOT=./.tmp_workspace uv --directory ../backend run uvicorn app.main:app --port 8000',
      url: 'http://localhost:8000/healthz',
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
})
```

- [ ] **Step 4: e2e spec**

```ts
// frontend/tests/e2e/walking-skeleton.spec.ts
import { test, expect } from '@playwright/test'

test('drag a PDF and submit chat — stubbed flow', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Projects')).toBeVisible()

  // type a chat message and hit Enter
  const textarea = page.getByRole('textbox')
  await textarea.fill('extract core invoice info')
  await textarea.press('Enter')

  // expect the stub agent_text to appear
  await expect(page.getByText('Stub run complete')).toBeVisible({ timeout: 10_000 })

  // expect tool-call cards
  await expect(page.getByText('create_project')).toBeVisible()
  await expect(page.getByText('extract_batch')).toBeVisible()
})
```

- [ ] **Step 5: Install Playwright browser and run**

Run:
```bash
cd frontend && npx playwright install chromium
npm run e2e
```
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/_test_stubs.py backend/app/main.py \
  frontend/playwright.config.ts frontend/tests/e2e/walking-skeleton.spec.ts
git commit -m "test(e2e): walking skeleton with stubbed chat route"
```

---

## Acceptance check

Run all backend + frontend tests one last time:

```bash
cd backend && uv run pytest -v
cd frontend && npm run test && npm run e2e
```

Expected: every test green. Manual smoke (with a real `EMERGE_ANTHROPIC_API_KEY`):

```bash
unset EMERGE_TEST_MODE
cd backend && uv run uvicorn app.main:app --reload --port 8000 &
cd frontend && npm run dev
```
Open http://localhost:5173/, drag 3–5 small PDFs into the chat composer, type "提取该发票核心信息" + Enter. Within ~10 s expect: tool_call cards for `create_project` → `upload_doc × N` → `derive_schema` → `write_schema` → `extract_batch`, plus an agent summary message. Project list refreshes. Workspace folder under `backend/workspace/p_xxxxxxxxx/` exists with `schema.json`, `docs/`, and `predictions/_draft/`.

---

## Spec coverage check

| Spec section | Covered by |
|---|---|
| §1.1 user mental model | demonstrated in M1 acceptance flow |
| §1.3 three-layer LLM separation | Tasks 12 (provider), 24 (chat service uses SDK separately) |
| §3.1–§3.2 filesystem layout | Tasks 2, 13, 14, 18, 19 (paths, project, docs, predictions/_draft) |
| §3.3 invariants (atomic write, flock) | Tasks 3, 4, 13, 16 |
| §4.1 `emerge-extractor` discipline | Task 20 SKILL.md |
| §5 tools (M1 subset) | Tasks 13–19, 21 |
| §6.3 risk gates (`write_schema` structural) | Task 16 |
| §8.1 default three-pane | Task 31 |
| §8.5 tool-call rendering | Task 35 |
| §8.6 visual identity | Task 30 |
| §9 error envelope | Tasks 8, 24 (error event), 35 (red border) |
| §10 testing layers | Tool unit (~10 tasks); provider contract (Task 12); skill replay deferred to M2 once we have meaningful chat flows; LLM smoke in acceptance check; frontend (Tasks 35, 37) |

M2/M3/M4 features (review mode, eval, improve, publish, OpenAI provider, dark mode polish) are deferred to their own plans by design.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-08-m1-walking-skeleton.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
