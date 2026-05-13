# M2C — AutoResearch + /improve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `/improve` workflow — when the user types `/improve`, the agent loads the `emerge-autoresearch` skill, kicks off a background job that loops up to `max_turn` times proposing schema description tweaks, scoring against reviewed examples, and saving the best per-turn candidate under `versions/_candidate/{job_id}/turn_{k}.json`. The user explicitly accepts a candidate to overwrite `schema.json`. Frontend renders streaming progress (per-turn macro_f1) with pause / cancel / accept controls. Also fold in spec-deferred review-mode items: type-derived FieldEditor controls, `_evidence` round-trip on review save, and inline `_notes` UI.

**Architecture:** A new `JobRunner` singleton (asyncio task tracker, per-job pause/resume/cancel events) lives in `app/jobs/runner.py`. The autoresearch loop in `app/jobs/autoresearch.py` is a pure async function that, per turn, (1) re-extracts reviewed docs with the current schema, (2) scores the result, (3) if better than the previous best, persists a candidate under `versions/_candidate/{job_id}/turn_{k}.json`, (4) calls the proposer LLM (via the existing `Provider.extract` adapter, NOT the SDK) to propose a revised schema where only `description` text changes are allowed. Stop on `max_turn` or `early_stop_no_improvement` consecutive non-improving turns. Per-job events stream as JSONL to `jobs/{job_id}.jsonl` and over a new SSE route the frontend subscribes to. Reviewed `_notes` feed the proposer as user-priority hints. Counterexample triplets do NOT exist yet (M3 /feedback territory) — score against the full reviewed set IS the regression test. Acceptance is a separate `POST /lab/projects/{pid}/schema/accept-candidate` route, never auto-applied.

**Tech Stack:** Backend uses `asyncio.Event` for pause/cancel signaling, existing `provider.extract` adapter for the proposer call, existing `score()` for grading, existing `atomic_write_json` + `project_lock` for filesystem invariants. Frontend adds a `useJob` Zustand store that subscribes to the SSE route, a `JobProgressCard` chat-message component, and extends `Reviewed`/review-mode for `_evidence` + `_notes` round-trip.

---

## Hard rules (red lines re-stated, never violate)

1. **AutoResearch never auto-promotes.** `schema.json` is mutated only by the explicit `accept-candidate` route. The loop only writes under `versions/_candidate/{job_id}/`.
2. **Proposer LLM goes through `Provider.extract` adapter — never via `ClaudeSDKClient`.** No SDK recursion from inside a tool / job. (Insight reinforces: the agent and extract are separate code paths.)
3. **No image few-shot, no example I/O pairs.** The proposer is allowed to rewrite `description` text only. Field add/remove/rename/retype is forbidden in the proposer's response_schema.
4. **Counterexamples never enter any prompt.** M2C does not introduce counterexample storage; the regression set IS the reviewed set (we score on it every turn).
5. **No token / $ budget.** Only `max_turn` (default 30) and `early_stop_no_improvement` (default 5) bound the loop.
6. **Reviewed `_notes` are user-priority hints into the proposer** — they are NOT counterexamples; they are inline annotations from the review UI.

---

## Scope cuts (deferred to M3 / M4)

- **Per-field convergence stopping criterion** — only global macro_f1 stagnation triggers early stop in v1. Per-field stop is M4 polish.
- **Crash recovery for in-flight jobs.** If the backend restarts mid-loop, the job is forgotten. Spec §9.2 mentions a `_job_locks/` startup scan; defer to M3.
- **Counterexample triplet storage and `/feedback` flow** — M3 case2.
- **Autoresearch UI surfacing schema diff against the active candidate** — for v1, the JobProgressCard shows the per-turn macro_f1 line and a "best turn so far" pointer; the diff is rendered in a simple modal on click-to-accept (raw JSON side-by-side).
- **`_source_page` click-to-page on JSON values in review mode** — needs `_evidence` round-trip (Task 19) but the click-to-jump UX is M4. Task 19 only persists `_evidence`; the viewer keeps the existing manual page navigation.
- **Per-job proposer model override / temperature override** — proposer uses the project's `extract_model` for v1.

---

## File structure

### Backend

```
backend/app/
├── jobs/
│   ├── __init__.py            # NEW — re-export JobRunner, get_runner()
│   ├── runner.py              # NEW — JobRunner singleton, _JobHandle, state machine
│   ├── events.py              # NEW — append_event_jsonl helpers, read_events
│   └── autoresearch.py        # NEW — propose_schema, score_with_schema, run_loop
├── schemas/
│   └── job.py                 # NEW — JobStatus, JobInfo, JobEvent pydantic models
├── tools/
│   ├── jobs.py                # NEW — start_job/get_job/pause_job/resume_job/cancel_job
│   └── __init__.py            # MODIFIED — register job tools, accept JobRunner arg
├── workspace/
│   └── paths.py               # MODIFIED — jobs_dir, job_log_path, candidate_dir, candidate_turn_path
├── api/routes/
│   ├── jobs.py                # NEW — GET /lab/jobs/{job_id}, GET .../events (SSE)
│   └── schema.py              # NEW — GET /lab/projects/{pid}/schema (already used by ReviewMode), POST /lab/projects/{pid}/schema/accept-candidate
├── skills/
│   ├── emerge_autoresearch.md # NEW
│   ├── emerge_extractor.md    # MODIFIED — drop (M2) annotations, link /improve handoff
│   └── __init__.py            # MODIFIED — load_skills(names) helper
├── chat/
│   └── service.py             # MODIFIED — load autoresearch skill on /improve, emit tool_result event with tool_use_id
├── schemas/
│   └── reviewed.py            # MODIFIED — accept Optional `evidence` field aliased to `_evidence`
└── main.py                    # MODIFIED — mount jobs + schema routers; init JobRunner on startup

backend/tests/unit/
├── test_paths.py              # add jobs_dir / candidate_dir tests (MODIFIED)
├── test_job_schemas.py        # NEW
├── test_job_events.py         # NEW
├── test_autoresearch_propose.py # NEW
├── test_autoresearch_score.py # NEW
├── test_autoresearch_loop.py  # NEW
├── test_job_runner.py         # NEW
├── test_tool_jobs.py          # NEW
├── test_tool_registration.py  # extend (MODIFIED)
├── test_skills_loader.py      # NEW
├── test_chat_tool_result.py   # NEW
└── test_reviewed_schema.py    # extend for `_evidence` round-trip (MODIFIED)
backend/tests/integration/
├── test_lab_jobs.py           # NEW — start, status, events SSE, cancel
├── test_lab_accept_candidate.py  # NEW
└── test_lab_reviewed_evidence.py # NEW
```

### Frontend

```
frontend/src/
├── types/
│   └── job.ts                 # NEW
├── stores/
│   └── jobs.ts                # NEW — useJob(jobId)
│   └── review.ts              # MODIFIED — round-trip evidence + notes
├── lib/
│   └── api.ts                 # MODIFIED — startJob/getJob/cancelJob/acceptCandidate URLs
├── components/
│   ├── Chat/
│   │   ├── JobProgressCard.tsx # NEW
│   │   ├── MessageList.tsx     # MODIFIED — render JobProgressCard for start_job tool result
│   │   └── SlashMenu.tsx       # MODIFIED — drop (M2) on /improve
│   ├── ReviewMode/
│   │   ├── FieldEditor.tsx     # MODIFIED — type-derived enum/number/boolean controls
│   │   └── NotesPopover.tsx    # NEW — right-click inline _notes editor
└── stores/
    └── chat.ts                 # MODIFIED — accept tool_result event, attach to existing tool_call by tool_use_id

frontend/tests/unit/
├── FieldEditor.test.tsx       # extend (MODIFIED)
├── JobProgressCard.test.tsx   # NEW
└── NotesPopover.test.tsx      # NEW
```

---

## Conventions

- **TDD throughout.** Each backend task lands a failing test first; frontend tasks land a vitest test first when feasible.
- **Backend run:** `cd backend && uv run pytest -v`. Baseline is **142 passed** (verified at plan write time).
- **Frontend run:** `cd frontend && npm run test` (vitest, baseline 13 passed) and `cd frontend && npm run e2e` (Playwright, baseline 2 passed).
- **All HTTP routes go through `safe_project_id`.** New `safe_job_id` helper added in T8 with regex `^j_[a-z0-9]{12}$`.
- **Atomic write via `atomic_write_json`** for any file persisted under a project.
- **`_evidence` and `_notes` are aliases**, mirroring the existing `Reviewed.notes` pattern (`Field(default=None, alias="_evidence")`).
- **JSONL event log is append-only**. Use the existing append pattern from `chat/log.py` (no atomic rename — partial trailing line is recoverable).

---

## Task index

Phase 1 — Foundations (1–3) — ~30 min
Phase 2 — Autoresearch loop (4–7) — ~120 min
Phase 3 — JobRunner (8–9) — ~80 min
Phase 4 — Chat SSE pairing (10) — ~25 min
Phase 5 — Tools + skill + chat (11–13) — ~60 min
Phase 6 — HTTP routes (14–15) — ~50 min
Phase 7 — Frontend (16–18) — ~80 min
Phase 8 — Spec deferred items (19–20) — ~70 min
Phase 9 — Smoke (21) — ~20 min

---

## Phase 1 — Foundations

### Task 1: paths helpers — `jobs_dir`, `job_log_path`, `candidate_dir`, `candidate_turn_path`

**Files:**
- Modify: `backend/app/workspace/paths.py`
- Modify: `backend/tests/unit/test_paths.py`

Per spec §3.2 each project has `jobs/{job_id}.jsonl` and `versions/_candidate/{job_id}/turn_{k}.json`. Mirror the M2B `metrics_dir`/`metrics_path` pattern.

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/unit/test_paths.py`:

```python
def test_jobs_dir(workspace: Path) -> None:
    from app.workspace.paths import jobs_dir
    assert jobs_dir(workspace, "p_abc") == workspace / "p_abc" / "jobs"


def test_job_log_path(workspace: Path) -> None:
    from app.workspace.paths import job_log_path
    assert (
        job_log_path(workspace, "p_abc", "j_xyz")
        == workspace / "p_abc" / "jobs" / "j_xyz.jsonl"
    )


def test_candidate_dir(workspace: Path) -> None:
    from app.workspace.paths import candidate_dir
    assert (
        candidate_dir(workspace, "p_abc", "j_xyz")
        == workspace / "p_abc" / "versions" / "_candidate" / "j_xyz"
    )


def test_candidate_turn_path(workspace: Path) -> None:
    from app.workspace.paths import candidate_turn_path
    assert (
        candidate_turn_path(workspace, "p_abc", "j_xyz", 3)
        == workspace / "p_abc" / "versions" / "_candidate" / "j_xyz" / "turn_3.json"
    )
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_paths.py -v`
Expected: ImportError on the new helpers.

- [ ] **Step 3: Append helpers**

Append to `backend/app/workspace/paths.py`:

```python
def jobs_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "jobs"


def job_log_path(workspace: Path, project_id: str, job_id: str) -> Path:
    return jobs_dir(workspace, project_id) / f"{job_id}.jsonl"


def candidate_dir(workspace: Path, project_id: str, job_id: str) -> Path:
    return versions_dir(workspace, project_id) / "_candidate" / job_id


def candidate_turn_path(workspace: Path, project_id: str, job_id: str, turn: int) -> Path:
    return candidate_dir(workspace, project_id, job_id) / f"turn_{turn}.json"
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/unit/test_paths.py -v`
Expected: 4 new tests pass.

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: 146 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace/paths.py backend/tests/unit/test_paths.py
git commit -m "feat(workspace): jobs_dir / candidate_dir helpers for M2C"
```

---

### Task 2: Pydantic models — `JobStatus`, `JobInfo`, `JobEvent`

**Files:**
- Create: `backend/app/schemas/job.py`
- Create: `backend/tests/unit/test_job_schemas.py`

Models for the in-memory job state and the on-disk JSONL event lines.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_job_schemas.py
import pytest
from pydantic import ValidationError

from app.schemas.job import JobEvent, JobInfo, JobStatus


def test_job_status_values() -> None:
    assert {s.value for s in JobStatus} == {
        "pending", "running", "paused", "done", "cancelled", "error",
    }


def test_job_info_minimal() -> None:
    info = JobInfo(
        job_id="j_abc123def456",
        project_id="p_abc123def456",
        skill="autoresearch",
        status=JobStatus.RUNNING,
        params={"max_turn": 30},
        created_at="2026-05-09T00-00-00Z",
    )
    assert info.skill == "autoresearch"
    assert info.status == JobStatus.RUNNING
    assert info.best_turn is None
    assert info.best_macro_f1 is None
    assert info.latest_turn == 0


def test_job_info_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        JobInfo(
            job_id="j_x", project_id="p_x", skill="autoresearch",
            status=JobStatus.RUNNING, params={}, created_at="x", unknown=1,
        )


def test_job_event_round_trip() -> None:
    ev = JobEvent(type="turn", turn=3, macro_f1=0.78, ts="2026-05-09T00-00-00Z")
    blob = ev.model_dump(mode="json")
    assert blob["type"] == "turn"
    assert blob["turn"] == 3
    assert blob["macro_f1"] == 0.78


def test_job_event_extra_allowed() -> None:
    """JobEvent allows arbitrary keys per event type — schema is loose by design.
    Strict typing happens at consumer parse time."""
    ev = JobEvent(type="started", ts="x", arbitrary_key="value")
    assert ev.model_dump(mode="json").get("arbitrary_key") == "value"
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_job_schemas.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/schemas/job.py
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    CANCELLED = "cancelled"
    ERROR = "error"


class JobInfo(BaseModel):
    """In-memory and serialized status for a single job."""
    model_config = ConfigDict(extra="forbid")

    job_id: str
    project_id: str
    skill: str               # "autoresearch" for v1
    status: JobStatus
    params: dict[str, Any]
    created_at: str
    latest_turn: int = 0
    best_turn: int | None = None
    best_macro_f1: float | None = None
    error_code: str | None = None
    error_message_en: str | None = None


class JobEvent(BaseModel):
    """One JSONL line in jobs/{job_id}.jsonl. Loose-typed: each `type` carries
    its own payload keys. Consumers parse with type-specific logic."""
    model_config = ConfigDict(extra="allow")

    type: str
    ts: str
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_job_schemas.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/job.py backend/tests/unit/test_job_schemas.py
git commit -m "feat(schemas): JobStatus / JobInfo / JobEvent models for M2C jobs"
```

---

### Task 3: JSONL event helpers (`append_event_jsonl`, `read_events`)

**Files:**
- Create: `backend/app/jobs/__init__.py` (empty)
- Create: `backend/app/jobs/events.py`
- Create: `backend/tests/unit/test_job_events.py`

Append-only JSONL writer guarded by an asyncio lock. Reader recovers from a partial trailing line.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_job_events.py
from datetime import datetime, timezone
from pathlib import Path

from app.jobs.events import append_event_jsonl, now_iso_filename_safe, read_events
from app.schemas.job import JobEvent


async def test_append_then_read(workspace: Path) -> None:
    p = workspace / "p_abc" / "jobs" / "j_xyz.jsonl"
    await append_event_jsonl(p, JobEvent(type="started", ts="t0"))
    await append_event_jsonl(p, JobEvent(type="turn", ts="t1", turn=1, macro_f1=0.5))
    events = await read_events(p)
    assert [e.type for e in events] == ["started", "turn"]
    assert events[1].model_dump(mode="json")["macro_f1"] == 0.5


async def test_read_partial_trailing_line(workspace: Path) -> None:
    p = workspace / "p_abc" / "jobs" / "j_xyz.jsonl"
    await append_event_jsonl(p, JobEvent(type="started", ts="t0"))
    # Simulate crash mid-write
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write('{"type": "turn", "ts":')   # truncated, no newline
    events = await read_events(p)
    assert len(events) == 1
    assert events[0].type == "started"


async def test_read_missing_file_returns_empty(workspace: Path) -> None:
    p = workspace / "p_abc" / "jobs" / "missing.jsonl"
    events = await read_events(p)
    assert events == []


def test_now_iso_filename_safe_format() -> None:
    s = now_iso_filename_safe()
    # 2026-05-09T01-23-45Z — no colons (filename-safe)
    assert "Z" in s and ":" not in s
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_job_events.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/jobs/__init__.py
# (empty — namespace placeholder)
```

```python
# backend/app/jobs/events.py
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.job import JobEvent


_log_lock = asyncio.Lock()


def now_iso_filename_safe() -> str:
    """ISO-8601 UTC with `:` replaced by `-` so it's safe as a filename component."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


async def append_event_jsonl(path: Path, event: JobEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n"
    async with _log_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


async def read_events(path: Path) -> list[JobEvent]:
    """Read all complete JSONL lines. Discards a final partial line silently."""
    if not path.exists():
        return []
    out: list[JobEvent] = []
    text = path.read_text(encoding="utf-8")
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        try:
            out.append(JobEvent(**json.loads(s)))
        except (json.JSONDecodeError, ValueError):
            # Partial trailing line on crash recovery — skip silently.
            continue
    return out
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_job_events.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/__init__.py backend/app/jobs/events.py backend/tests/unit/test_job_events.py
git commit -m "feat(jobs): append_event_jsonl + read_events helpers"
```

---

## Phase 2 — AutoResearch loop

### Task 4: Proposer prompt + response_schema constants

**Files:**
- Create: `backend/app/jobs/autoresearch.py`
- Create: `backend/tests/unit/test_autoresearch_propose.py`

The proposer is fed: current schema, paired (reviewed, prediction, score) summary, and `_notes` hints. It returns a revised schema where ONLY `description` text changes are allowed. We enforce this server-side after the call (T5).

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_autoresearch_propose.py
from app.jobs.autoresearch import (
    PROPOSER_RESPONSE_SCHEMA,
    PROPOSER_SYSTEM_PROMPT,
    build_proposer_user_text,
)
from app.schemas.schema_field import FieldType, SchemaField


def _f(name: str, desc: str) -> SchemaField:
    return SchemaField(name=name, type=FieldType.STRING, description=desc)


def test_proposer_response_schema_shape() -> None:
    s = PROPOSER_RESPONSE_SCHEMA
    assert s["type"] == "object"
    assert "fields" in s["properties"]
    assert "rationale" in s["properties"]
    assert "fields" in s["required"]


def test_proposer_system_prompt_forbids_structural_changes() -> None:
    # The prompt must explicitly tell the model NOT to add/remove/rename/retype.
    prompt = PROPOSER_SYSTEM_PROMPT
    assert "description" in prompt.lower()
    forbidden = ["add", "remove", "rename", "retype"]
    for kw in forbidden:
        assert kw in prompt.lower(), f"prompt missing guard against {kw!r}"


def test_proposer_user_text_includes_schema_and_scores() -> None:
    schema = [_f("invoice_no", "the number of the invoice")]
    reviewed = {"d_a": [{"invoice_no": "INV-1"}]}
    predictions = {"d_a": [{"invoice_no": "WRONG"}]}
    notes = {"d_a": {"invoice_no": "official is INV-1, not WRONG"}}
    per_field_summary = [{"field": "invoice_no", "f1": 0.0, "tp": 0, "fp": 1, "fn": 1}]

    text = build_proposer_user_text(
        schema=schema,
        reviewed=reviewed,
        predictions=predictions,
        per_field=per_field_summary,
        notes=notes,
    )
    assert "invoice_no" in text
    assert "WRONG" in text
    assert "INV-1" in text
    assert "official is INV-1" in text
    # f1 number visible
    assert "0.0" in text or "0.00" in text


def test_proposer_user_text_includes_no_notes_section_when_empty() -> None:
    schema = [_f("x", "a field")]
    text = build_proposer_user_text(
        schema=schema, reviewed={}, predictions={}, per_field=[], notes={}
    )
    assert "user notes" not in text.lower() or "(none)" in text.lower()
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_autoresearch_propose.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/jobs/autoresearch.py
from __future__ import annotations

from typing import Any

from app.schemas.schema_field import SchemaField


PROPOSER_SYSTEM_PROMPT = """You are improving a JSON extraction schema for a document-extraction API.

Given the current schema, ground-truth reviewed examples, the latest model
predictions, the per-field score, and user inline notes, propose a revised
schema. The ONLY change you may make is rewording each field's `description`
(adding rules, sharpening format guidance, encoding edge cases the user
flagged in notes).

Hard constraints:
- DO NOT add fields.
- DO NOT remove fields.
- DO NOT rename fields.
- DO NOT retype fields.
- Keep the field order identical.
- For each field, return `name`, `type`, and `description` (and the original
  `required`/`enum`/`examples`/`children` if present), but only `description`
  may differ from the input.

Treat the user's inline `_notes` as high-priority hints — they are direct
human feedback on what's wrong. Sample errors show concrete reviewed-vs-
prediction disagreements per doc.

Output via the propose_schema tool. Include a short `rationale` explaining
which descriptions you changed and why."""


PROPOSER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["fields", "rationale"],
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "description"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["string", "number", "boolean", "date", "array<object>"],
                    },
                    "description": {"type": "string"},
                    "required": {"type": "boolean"},
                    "examples": {"type": "array", "items": {"type": "string"}},
                    "enum": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "rationale": {"type": "string"},
    },
}


def build_proposer_user_text(
    *,
    schema: list[SchemaField],
    reviewed: dict[str, list[dict[str, Any]]],
    predictions: dict[str, list[dict[str, Any]]],
    per_field: list[dict[str, Any]],
    notes: dict[str, dict[str, str]],
) -> str:
    lines: list[str] = []

    lines.append("=== current schema ===")
    for f in schema:
        lines.append(f"- {f.name} ({f.type.value}): {f.description}")

    lines.append("")
    lines.append("=== per-field score ===")
    if not per_field:
        lines.append("(no graded fields)")
    else:
        for fs in per_field:
            lines.append(
                f"- {fs['field']}: f1={fs['f1']:.2f} tp={fs['tp']} fp={fs['fp']} fn={fs['fn']}"
            )

    lines.append("")
    lines.append("=== sample errors (reviewed vs prediction) ===")
    any_err = False
    for doc_id, rev_entities in reviewed.items():
        rev = rev_entities[0] if rev_entities else {}
        pred_entities = predictions.get(doc_id, [])
        pred = pred_entities[0] if pred_entities else {}
        for f in schema:
            r = rev.get(f.name)
            p = pred.get(f.name)
            if r is not None and r != p:
                any_err = True
                lines.append(f"- {doc_id}.{f.name}: reviewed={r!r} predicted={p!r}")
    if not any_err:
        lines.append("(no field-level errors)")

    lines.append("")
    lines.append("=== user notes (high-priority hints) ===")
    flat: list[str] = []
    for doc_id, per_field_notes in notes.items():
        for fname, note in per_field_notes.items():
            flat.append(f"- {doc_id}.{fname}: {note}")
    if not flat:
        lines.append("(none)")
    else:
        lines.extend(flat)

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_autoresearch_propose.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/autoresearch.py backend/tests/unit/test_autoresearch_propose.py
git commit -m "feat(autoresearch): proposer prompt + response_schema + user-text builder"
```

---

### Task 5: `propose_schema()` — single proposer LLM call with structural-change guard

**Files:**
- Modify: `backend/app/jobs/autoresearch.py` (append `propose_schema`)
- Modify: `backend/tests/unit/test_autoresearch_propose.py` (append integration tests)

Calls `provider.extract` with the proposer system prompt + assembled user text. Validates that returned schema has the same field names AND same types as the input — raises `ProposerStructuralChangeError` otherwise. Returns the parsed `SchemaField[]` (with new descriptions only) plus the rationale string.

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/unit/test_autoresearch_propose.py`:

```python
from unittest.mock import AsyncMock

import pytest

from app.jobs.autoresearch import ProposerStructuralChangeError, propose_schema
from app.provider.base import ProviderResult


async def test_propose_schema_returns_revised_descriptions() -> None:
    schema = [_f("invoice_no", "old desc")]
    new_blob = {
        "fields": [{"name": "invoice_no", "type": "string", "description": "new sharper desc"}],
        "rationale": "tightened format guidance",
    }
    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(raw_json=new_blob, model_id="stub")

    proposed, rationale = await propose_schema(
        provider=provider, model_id="stub", schema=schema,
        reviewed={}, predictions={}, per_field=[], notes={},
    )
    assert len(proposed) == 1
    assert proposed[0].name == "invoice_no"
    assert proposed[0].description == "new sharper desc"
    assert rationale == "tightened format guidance"


async def test_propose_schema_rejects_added_field() -> None:
    schema = [_f("invoice_no", "old desc")]
    bad_blob = {
        "fields": [
            {"name": "invoice_no", "type": "string", "description": "new"},
            {"name": "snuck_in", "type": "string", "description": "extra"},
        ],
        "rationale": "tried to add field",
    }
    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(raw_json=bad_blob, model_id="stub")
    with pytest.raises(ProposerStructuralChangeError):
        await propose_schema(
            provider=provider, model_id="stub", schema=schema,
            reviewed={}, predictions={}, per_field=[], notes={},
        )


async def test_propose_schema_rejects_renamed_field() -> None:
    schema = [_f("invoice_no", "x")]
    bad_blob = {
        "fields": [{"name": "invoice_number", "type": "string", "description": "y"}],
        "rationale": "renamed",
    }
    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(raw_json=bad_blob, model_id="stub")
    with pytest.raises(ProposerStructuralChangeError):
        await propose_schema(
            provider=provider, model_id="stub", schema=schema,
            reviewed={}, predictions={}, per_field=[], notes={},
        )


async def test_propose_schema_rejects_retyped_field() -> None:
    schema = [_f("invoice_no", "x")]
    bad_blob = {
        "fields": [{"name": "invoice_no", "type": "number", "description": "y"}],
        "rationale": "retyped",
    }
    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(raw_json=bad_blob, model_id="stub")
    with pytest.raises(ProposerStructuralChangeError):
        await propose_schema(
            provider=provider, model_id="stub", schema=schema,
            reviewed={}, predictions={}, per_field=[], notes={},
        )
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_autoresearch_propose.py -v`
Expected: ImportError on `propose_schema` / `ProposerStructuralChangeError`.

- [ ] **Step 3: Append `propose_schema` to `app/jobs/autoresearch.py`**

```python
from app.provider.base import Provider, TextBlock


class ProposerStructuralChangeError(Exception):
    """Raised when the proposer LLM tried to add/remove/rename/retype a field.
    The autoresearch loop treats this as a non-improving turn and continues."""


async def propose_schema(
    *,
    provider: Provider,
    model_id: str,
    schema: list[SchemaField],
    reviewed: dict[str, list[dict[str, Any]]],
    predictions: dict[str, list[dict[str, Any]]],
    per_field: list[dict[str, Any]],
    notes: dict[str, dict[str, str]],
) -> tuple[list[SchemaField], str]:
    """One proposer LLM call. Returns (revised schema, rationale).

    Raises ProposerStructuralChangeError if the proposer attempts to add /
    remove / rename / retype any field — only `description` text may change.
    """
    user_text = build_proposer_user_text(
        schema=schema, reviewed=reviewed, predictions=predictions,
        per_field=per_field, notes=notes,
    )
    result = await provider.extract(
        model_id=model_id,
        system_prompt=PROPOSER_SYSTEM_PROMPT,
        user_content=[TextBlock(text=user_text)],
        response_schema=PROPOSER_RESPONSE_SCHEMA,
        params={"temperature": 0.2},
    )
    blob = result.raw_json
    rationale = str(blob.get("rationale", ""))
    raw_fields: list[dict[str, Any]] = list(blob.get("fields") or [])

    if len(raw_fields) != len(schema):
        raise ProposerStructuralChangeError(
            f"proposer returned {len(raw_fields)} fields; expected {len(schema)}"
        )
    proposed: list[SchemaField] = []
    for old, new in zip(schema, raw_fields):
        if new.get("name") != old.name:
            raise ProposerStructuralChangeError(
                f"proposer changed field name {old.name!r} → {new.get('name')!r}"
            )
        if new.get("type") != old.type.value:
            raise ProposerStructuralChangeError(
                f"proposer changed type for {old.name!r} "
                f"{old.type.value!r} → {new.get('type')!r}"
            )
        # Carry forward old metadata that the proposer doesn't touch.
        merged = old.model_dump(mode="json")
        merged["description"] = str(new.get("description", old.description))
        proposed.append(SchemaField(**merged))

    return proposed, rationale
```

(Add the import at the top of the file: `from app.provider.base import Provider, TextBlock`.)

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_autoresearch_propose.py -v`
Expected: 8 passed (4 prior + 4 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/autoresearch.py backend/tests/unit/test_autoresearch_propose.py
git commit -m "feat(autoresearch): propose_schema() with structural-change guard"
```

---

### Task 6: `score_with_schema()` — extract over reviewed + score helper

**Files:**
- Modify: `backend/app/jobs/autoresearch.py` (append)
- Create: `backend/tests/unit/test_autoresearch_score.py`

Helper that, given a candidate schema, runs `extract_one` over the reviewed-doc set (with that schema in memory — does NOT touch `schema.json`), assembles a predictions dict, and calls `score()`. Used by the loop to grade each turn.

The existing `extract_one` reads the schema from `schema.json`. We need a variant that takes the schema as a parameter to avoid filesystem mutation. Add `extract_one_with_schema` to `app/tools/extract.py` (small helper).

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_autoresearch_score.py
from pathlib import Path
from unittest.mock import AsyncMock

from app.jobs.autoresearch import score_with_schema
from app.provider.base import ProviderResult
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed


async def test_score_with_schema_runs_extract_then_score(workspace: Path) -> None:
    pid = await create_project(workspace, name="t")
    pdf = b"%PDF-1.4\n%%EOF\n"
    did = await upload_doc(workspace, pid, pdf, "a.pdf")
    await save_reviewed(
        workspace, pid, did,
        entities=[{"invoice_no": "INV-1"}],
        source=ReviewedSource.MANUAL,
    )
    schema = [SchemaField(name="invoice_no", type=FieldType.STRING, description="d")]

    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"invoice_no": "INV-1"}]},
        model_id="stub",
    )

    score_result, predictions = await score_with_schema(
        workspace=workspace, project_id=pid, schema=schema,
        provider=provider, model_id="stub",
    )
    assert score_result.macro_f1 == 1.0
    assert predictions == {did: [{"invoice_no": "INV-1"}]}


async def test_score_with_schema_returns_zero_when_reviewed_empty(workspace: Path) -> None:
    pid = await create_project(workspace, name="t")
    schema = [SchemaField(name="invoice_no", type=FieldType.STRING, description="d")]
    provider = AsyncMock()
    score_result, predictions = await score_with_schema(
        workspace=workspace, project_id=pid, schema=schema,
        provider=provider, model_id="stub",
    )
    assert score_result.n_reviewed == 0
    assert predictions == {}
    provider.extract.assert_not_called()
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_autoresearch_score.py -v`
Expected: ImportError on `score_with_schema`.

- [ ] **Step 3: Add `extract_one_with_schema` helper**

In `backend/app/tools/extract.py`, near the existing `extract_one` function add:

```python
async def extract_one_with_schema(
    workspace: Path,
    project_id: str,
    doc_id: str,
    *,
    schema: list[SchemaField],
    provider: Provider,
    model_id: str,
) -> dict[str, Any]:
    """Like extract_one but uses an in-memory schema (does NOT read schema.json
    or write predictions/_draft/). Used by the autoresearch loop to grade
    candidate schemas without mutating disk state."""
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
        params={"temperature": 0.0},
    )
    parsed = ExtractionOutput(**result.raw_json)
    return parsed.model_dump(by_alias=True, exclude_none=True, mode="json")
```

- [ ] **Step 4: Append `score_with_schema` to `app/jobs/autoresearch.py`**

```python
from pathlib import Path
import json

from app.schemas.score import ScoreResult
from app.tools.extract import extract_one_with_schema
from app.tools.score import score
from app.workspace.paths import reviewed_dir


async def score_with_schema(
    *,
    workspace: Path,
    project_id: str,
    schema: list[SchemaField],
    provider: Provider,
    model_id: str,
) -> tuple[ScoreResult, dict[str, list[dict[str, Any]]]]:
    """Run extract over each reviewed doc with `schema`, then score predictions
    vs reviewed. Returns (ScoreResult, predictions_dict)."""
    rdir = reviewed_dir(workspace, project_id)
    reviewed: dict[str, list[dict[str, Any]]] = {}
    if rdir.exists():
        for p in sorted(rdir.glob("*.json")):
            blob = json.loads(p.read_text())
            reviewed[p.stem] = blob.get("entities", [])

    predictions: dict[str, list[dict[str, Any]]] = {}
    for doc_id in reviewed:
        out = await extract_one_with_schema(
            workspace, project_id, doc_id,
            schema=schema, provider=provider, model_id=model_id,
        )
        predictions[doc_id] = out.get("entities", [])

    result = score(schema, predictions, reviewed)
    return result, predictions
```

(Imports added at top of `autoresearch.py`.)

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_autoresearch_score.py tests/unit/test_tool_extract.py -v`
Expected: 2 new passes; existing extract tests still pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/jobs/autoresearch.py backend/app/tools/extract.py backend/tests/unit/test_autoresearch_score.py
git commit -m "feat(autoresearch): score_with_schema + extract_one_with_schema helpers"
```

---

### Task 7: `run_autoresearch_loop()` orchestrator

**Files:**
- Modify: `backend/app/jobs/autoresearch.py` (append)
- Create: `backend/tests/unit/test_autoresearch_loop.py`

The loop. Pseudocode:

```
emit started event
baseline = score_with_schema(initial_schema)
emit turn 0 event (baseline)
save_candidate_turn(0, schema, baseline, predictions)
best = baseline
no_improvement = 0
current = initial_schema

for k in 1..max_turn:
    if cancelled: emit cancelled, break
    if paused: await resume
    proposed = propose_schema(current, ...)         # may raise ProposerStructuralChangeError
    scored, predictions = score_with_schema(proposed)
    emit turn k event
    if scored.macro_f1 > best.macro_f1:
        save_candidate_turn(k, proposed, scored, predictions)
        best = (k, scored, proposed)
        no_improvement = 0
    else:
        no_improvement += 1
    current = proposed     # always advance, even if no improvement
    if no_improvement >= early_stop_no_improvement:
        emit ended(reason=early_stop), break
emit ended(reason=max_turn)
```

`save_candidate_turn(k, schema, scored, predictions)` writes `versions/_candidate/{job_id}/turn_{k}.json` atomically with `{schema, rationale, macro_f1, per_field, predictions, turn, parent_turn}`.

The orchestrator accepts an optional `cancel_event` and `pause_event` from the caller (T8 wires them in). For testability the orchestrator uses module-level injection points (`propose_schema`, `score_with_schema`) — tests monkeypatch them.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_autoresearch_loop.py
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.jobs import autoresearch as ar
from app.jobs.autoresearch import (
    ProposerStructuralChangeError,
    AutoresearchParams,
    run_autoresearch_loop,
)
from app.schemas.job import JobEvent
from app.schemas.schema_field import FieldType, SchemaField
from app.schemas.score import FieldScore, ScoreResult


def _f(name: str = "invoice_no") -> SchemaField:
    return SchemaField(name=name, type=FieldType.STRING, description="d")


def _fake_score(macro_f1: float) -> ScoreResult:
    return ScoreResult(
        n_docs=1, n_reviewed=1, macro_f1=macro_f1,
        per_field=[FieldScore(field="invoice_no", tp=1, fp=0, fn=0, support=1,
                              precision=1.0, recall=1.0, f1=macro_f1)],
        errors=[], ts="t", schema_field_count=1,
    )


@dataclass
class _Plan:
    score_seq: list[float]               # score returned per turn (turn 0..N)
    propose_seq: list[list[SchemaField]] # schema returned per propose call (turn 1..N)


def _patched_score_and_propose(monkeypatch: pytest.MonkeyPatch, plan: _Plan) -> dict[str, int]:
    counters = {"score": 0, "propose": 0}

    async def _fake_score_with_schema(**kwargs) -> tuple[ScoreResult, dict]:
        i = counters["score"]
        counters["score"] += 1
        return _fake_score(plan.score_seq[i]), {}

    async def _fake_propose_schema(**kwargs) -> tuple[list[SchemaField], str]:
        i = counters["propose"]
        counters["propose"] += 1
        return plan.propose_seq[i], "rat"

    monkeypatch.setattr(ar, "score_with_schema", _fake_score_with_schema)
    monkeypatch.setattr(ar, "propose_schema", _fake_propose_schema)
    return counters


async def test_loop_improves_then_max_turn(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = [_f()]
    plan = _Plan(
        score_seq=[0.5, 0.7, 0.9],   # baseline + 2 propose turns
        propose_seq=[[_f()], [_f()]],
    )
    _patched_score_and_propose(monkeypatch, plan)

    events: list[JobEvent] = []
    async def emit(e: JobEvent) -> None:
        events.append(e)

    info = await run_autoresearch_loop(
        workspace=workspace, project_id="p_aaaaaaaaaaaa",
        job_id="j_xxxxxxxxxxxx", initial_schema=schema,
        provider=AsyncMock(), model_id="stub",
        params=AutoresearchParams(max_turn=2, early_stop_no_improvement=99),
        emit=emit, cancel_event=asyncio.Event(), pause_event=asyncio.Event(),
    )
    assert info.best_macro_f1 == 0.9
    assert info.best_turn == 2
    types = [e.type for e in events]
    assert types[0] == "started"
    assert types.count("turn") == 3   # turns 0, 1, 2
    assert types[-1] == "ended"
    # Candidate files persisted for improving turns
    cand_dir = workspace / "p_aaaaaaaaaaaa" / "versions" / "_candidate" / "j_xxxxxxxxxxxx"
    assert (cand_dir / "turn_0.json").exists()
    assert (cand_dir / "turn_1.json").exists()
    assert (cand_dir / "turn_2.json").exists()


async def test_loop_no_improvement_does_not_save(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = [_f()]
    plan = _Plan(
        score_seq=[0.8, 0.5, 0.7],   # baseline=0.8, both proposals worse
        propose_seq=[[_f()], [_f()]],
    )
    _patched_score_and_propose(monkeypatch, plan)
    events: list[JobEvent] = []
    async def emit(e: JobEvent) -> None: events.append(e)

    info = await run_autoresearch_loop(
        workspace=workspace, project_id="p_aaaaaaaaaaaa",
        job_id="j_xxxxxxxxxxxx", initial_schema=schema,
        provider=AsyncMock(), model_id="stub",
        params=AutoresearchParams(max_turn=2, early_stop_no_improvement=99),
        emit=emit, cancel_event=asyncio.Event(), pause_event=asyncio.Event(),
    )
    assert info.best_macro_f1 == 0.8
    assert info.best_turn == 0
    cand_dir = workspace / "p_aaaaaaaaaaaa" / "versions" / "_candidate" / "j_xxxxxxxxxxxx"
    assert (cand_dir / "turn_0.json").exists()
    assert not (cand_dir / "turn_1.json").exists()
    assert not (cand_dir / "turn_2.json").exists()


async def test_loop_early_stop(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = [_f()]
    # baseline 0.5, then 5 turns of no improvement → early stop at turn 5
    plan = _Plan(
        score_seq=[0.5, 0.4, 0.3, 0.4, 0.4, 0.3, 0.4, 0.4],
        propose_seq=[[_f()]] * 7,
    )
    _patched_score_and_propose(monkeypatch, plan)
    events: list[JobEvent] = []
    async def emit(e: JobEvent) -> None: events.append(e)

    info = await run_autoresearch_loop(
        workspace=workspace, project_id="p_aaaaaaaaaaaa",
        job_id="j_xxxxxxxxxxxx", initial_schema=schema,
        provider=AsyncMock(), model_id="stub",
        params=AutoresearchParams(max_turn=20, early_stop_no_improvement=5),
        emit=emit, cancel_event=asyncio.Event(), pause_event=asyncio.Event(),
    )
    end_event = next(e for e in events if e.type == "ended")
    assert end_event.model_dump(mode="json")["reason"] == "early_stop"
    assert info.best_turn == 0


async def test_loop_cancelled(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = [_f()]
    plan = _Plan(score_seq=[0.5, 0.6, 0.7], propose_seq=[[_f()], [_f()]])
    _patched_score_and_propose(monkeypatch, plan)

    cancel = asyncio.Event()
    cancel.set()  # cancel before loop starts

    events: list[JobEvent] = []
    async def emit(e: JobEvent) -> None: events.append(e)

    info = await run_autoresearch_loop(
        workspace=workspace, project_id="p_aaaaaaaaaaaa",
        job_id="j_xxxxxxxxxxxx", initial_schema=schema,
        provider=AsyncMock(), model_id="stub",
        params=AutoresearchParams(max_turn=10, early_stop_no_improvement=5),
        emit=emit, cancel_event=cancel, pause_event=asyncio.Event(),
    )
    end_event = next(e for e in events if e.type == "ended")
    assert end_event.model_dump(mode="json")["reason"] == "cancelled"


async def test_loop_handles_proposer_structural_change(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = [_f()]
    counters = {"score": 0, "propose": 0}

    async def _score(**kwargs):
        i = counters["score"]
        counters["score"] += 1
        return _fake_score(0.5 if i == 0 else 0.7), {}

    async def _propose(**kwargs):
        counters["propose"] += 1
        if counters["propose"] == 1:
            raise ProposerStructuralChangeError("tried to add field")
        return [_f()], "ok"

    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)

    events: list[JobEvent] = []
    async def emit(e: JobEvent) -> None: events.append(e)

    info = await run_autoresearch_loop(
        workspace=workspace, project_id="p_aaaaaaaaaaaa",
        job_id="j_xxxxxxxxxxxx", initial_schema=schema,
        provider=AsyncMock(), model_id="stub",
        params=AutoresearchParams(max_turn=2, early_stop_no_improvement=99),
        emit=emit, cancel_event=asyncio.Event(), pause_event=asyncio.Event(),
    )
    # The structural-change failure is logged as a `proposer_failed` event but
    # does NOT terminate the loop — turn just doesn't improve.
    types = [e.type for e in events]
    assert "proposer_failed" in types
    assert info.best_macro_f1 == 0.7   # second propose succeeded
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_autoresearch_loop.py -v`
Expected: ImportError on `run_autoresearch_loop` / `AutoresearchParams`.

- [ ] **Step 3: Append loop to `app/jobs/autoresearch.py`**

```python
import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.jobs.events import now_iso_filename_safe
from app.schemas.job import JobEvent, JobInfo, JobStatus
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import candidate_dir, candidate_turn_path


@dataclass
class AutoresearchParams:
    max_turn: int = 30
    early_stop_no_improvement: int = 5


EmitFn = Callable[[JobEvent], Awaitable[None]]


def _save_candidate_turn(
    *,
    workspace: Path,
    project_id: str,
    job_id: str,
    turn: int,
    schema: list[SchemaField],
    score_result: ScoreResult,
    predictions: dict[str, list[dict[str, Any]]],
    rationale: str,
    parent_turn: int | None,
) -> Path:
    candidate_dir(workspace, project_id, job_id).mkdir(parents=True, exist_ok=True)
    target = candidate_turn_path(workspace, project_id, job_id, turn)
    payload = {
        "turn": turn,
        "parent_turn": parent_turn,
        "schema": [f.model_dump(mode="json") for f in schema],
        "rationale": rationale,
        "macro_f1": score_result.macro_f1,
        "per_field": [fs.model_dump(mode="json") for fs in score_result.per_field],
        "predictions": predictions,
        "ts": score_result.ts,
    }
    atomic_write_json(target, payload)
    return target


async def run_autoresearch_loop(
    *,
    workspace: Path,
    project_id: str,
    job_id: str,
    initial_schema: list[SchemaField],
    provider: Provider,
    model_id: str,
    params: AutoresearchParams,
    emit: EmitFn,
    cancel_event: asyncio.Event,
    pause_event: asyncio.Event,
) -> JobInfo:
    """The autoresearch loop. Returns final JobInfo with best_turn / best_macro_f1.

    Caller is responsible for persisting the JobInfo to its in-memory registry;
    per-event JSONL persistence is the caller's job too (via `emit`)."""
    info = JobInfo(
        job_id=job_id, project_id=project_id, skill="autoresearch",
        status=JobStatus.RUNNING, params={
            "max_turn": params.max_turn,
            "early_stop_no_improvement": params.early_stop_no_improvement,
        },
        created_at=now_iso_filename_safe(),
    )
    await emit(JobEvent(type="started", ts=now_iso_filename_safe(),
                        job_id=job_id, project_id=project_id))

    if cancel_event.is_set():
        await emit(JobEvent(type="ended", ts=now_iso_filename_safe(), reason="cancelled",
                            best_turn=None, best_macro_f1=None))
        info.status = JobStatus.CANCELLED
        return info

    # turn 0: baseline score on the initial schema
    baseline, baseline_predictions = await score_with_schema(
        workspace=workspace, project_id=project_id, schema=initial_schema,
        provider=provider, model_id=model_id,
    )
    _save_candidate_turn(
        workspace=workspace, project_id=project_id, job_id=job_id, turn=0,
        schema=initial_schema, score_result=baseline, predictions=baseline_predictions,
        rationale="baseline", parent_turn=None,
    )
    await emit(JobEvent(
        type="turn", ts=now_iso_filename_safe(), turn=0,
        macro_f1=baseline.macro_f1,
        per_field=[fs.model_dump(mode="json") for fs in baseline.per_field],
        saved=True,
    ))

    best_macro_f1 = baseline.macro_f1
    best_turn = 0
    no_improvement = 0
    current_schema = initial_schema

    for turn in range(1, params.max_turn + 1):
        # Honour pause, then cancel.
        if pause_event.is_set():
            await emit(JobEvent(type="paused", ts=now_iso_filename_safe(), turn=turn))
            while pause_event.is_set() and not cancel_event.is_set():
                await asyncio.sleep(0.05)
            if not cancel_event.is_set():
                await emit(JobEvent(type="resumed", ts=now_iso_filename_safe(), turn=turn))
        if cancel_event.is_set():
            await emit(JobEvent(type="ended", ts=now_iso_filename_safe(), reason="cancelled",
                                best_turn=best_turn, best_macro_f1=best_macro_f1))
            info.status = JobStatus.CANCELLED
            info.best_turn = best_turn
            info.best_macro_f1 = best_macro_f1
            return info

        # Read latest reviewed (with _notes) for the proposer prompt.
        reviewed_blob, notes_blob = _load_reviewed_with_notes(workspace, project_id)

        try:
            proposed, rationale = await propose_schema(
                provider=provider, model_id=model_id, schema=current_schema,
                reviewed=reviewed_blob, predictions=baseline_predictions,
                per_field=[fs.model_dump(mode="json") for fs in baseline.per_field],
                notes=notes_blob,
            )
        except ProposerStructuralChangeError as exc:
            await emit(JobEvent(type="proposer_failed", ts=now_iso_filename_safe(),
                                turn=turn, error=str(exc)))
            no_improvement += 1
            if no_improvement >= params.early_stop_no_improvement:
                await emit(JobEvent(type="ended", ts=now_iso_filename_safe(),
                                    reason="early_stop",
                                    best_turn=best_turn, best_macro_f1=best_macro_f1))
                info.status = JobStatus.DONE
                info.best_turn = best_turn
                info.best_macro_f1 = best_macro_f1
                return info
            continue

        scored, predictions = await score_with_schema(
            workspace=workspace, project_id=project_id, schema=proposed,
            provider=provider, model_id=model_id,
        )
        improved = scored.macro_f1 > best_macro_f1
        if improved:
            _save_candidate_turn(
                workspace=workspace, project_id=project_id, job_id=job_id, turn=turn,
                schema=proposed, score_result=scored, predictions=predictions,
                rationale=rationale, parent_turn=best_turn,
            )
            best_macro_f1 = scored.macro_f1
            best_turn = turn
            no_improvement = 0
        else:
            no_improvement += 1
        await emit(JobEvent(
            type="turn", ts=now_iso_filename_safe(), turn=turn,
            macro_f1=scored.macro_f1,
            per_field=[fs.model_dump(mode="json") for fs in scored.per_field],
            saved=improved, rationale=rationale,
        ))
        current_schema = proposed
        baseline = scored
        baseline_predictions = predictions

        if no_improvement >= params.early_stop_no_improvement:
            await emit(JobEvent(type="ended", ts=now_iso_filename_safe(),
                                reason="early_stop",
                                best_turn=best_turn, best_macro_f1=best_macro_f1))
            info.status = JobStatus.DONE
            info.best_turn = best_turn
            info.best_macro_f1 = best_macro_f1
            return info

    await emit(JobEvent(type="ended", ts=now_iso_filename_safe(), reason="max_turn",
                        best_turn=best_turn, best_macro_f1=best_macro_f1))
    info.status = JobStatus.DONE
    info.best_turn = best_turn
    info.best_macro_f1 = best_macro_f1
    return info


def _load_reviewed_with_notes(
    workspace: Path, project_id: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, str]]]:
    rdir = reviewed_dir(workspace, project_id)
    reviewed: dict[str, list[dict[str, Any]]] = {}
    notes: dict[str, dict[str, str]] = {}
    if not rdir.exists():
        return reviewed, notes
    for p in sorted(rdir.glob("*.json")):
        blob = json.loads(p.read_text())
        reviewed[p.stem] = blob.get("entities", [])
        if blob.get("_notes"):
            notes[p.stem] = blob["_notes"]
    return reviewed, notes
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_autoresearch_loop.py -v`
Expected: 5 passed.

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: 161 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/autoresearch.py backend/tests/unit/test_autoresearch_loop.py
git commit -m "feat(autoresearch): run_autoresearch_loop orchestrator (max_turn, early_stop, cancel, pause)"
```

---

## Phase 3 — JobRunner

### Task 8: `JobRunner` singleton

**Files:**
- Create: `backend/app/jobs/runner.py`
- Create: `backend/tests/unit/test_job_runner.py`
- Modify: `backend/app/api/routes/_safety.py` (add `safe_job_id`)

JobRunner is a process-wide singleton that:
- Spawns asyncio tasks for jobs.
- Tracks `_JobHandle` per `job_id`: `info: JobInfo`, `task: asyncio.Task`, `pause_event: asyncio.Event`, `cancel_event: asyncio.Event`.
- Exposes `start(skill, project_id, params)`, `get(job_id)`, `pause(job_id)`, `resume(job_id)`, `cancel(job_id)`.
- Persists each emitted `JobEvent` to `jobs/{job_id}.jsonl` AND keeps the live JobInfo in memory.

For v1 the only supported `skill` is `"autoresearch"`. Other skills raise `UnknownSkillError`.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_job_runner.py
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.jobs import autoresearch as ar
from app.jobs.runner import JobNotFoundError, JobRunner, UnknownSkillError
from app.schemas.job import JobStatus
from app.schemas.schema_field import FieldType, SchemaField
from app.schemas.score import FieldScore, ScoreResult
from app.tools.projects import create_project
from app.tools.schema import write_schema


def _fake_score(macro_f1: float) -> ScoreResult:
    return ScoreResult(
        n_docs=1, n_reviewed=1, macro_f1=macro_f1,
        per_field=[FieldScore(field="x", tp=1, fp=0, fn=0, support=1,
                              precision=1.0, recall=1.0, f1=macro_f1)],
        errors=[], ts="t", schema_field_count=1,
    )


@pytest.fixture
def patched_loop(monkeypatch: pytest.MonkeyPatch):
    """Replace propose_schema and score_with_schema with deterministic stubs.
    Score sequence improves once then plateaus, so the loop ends quickly."""
    seq = [0.5, 0.7]

    async def _score(**kwargs):
        i = min(len(seq) - 1, _score.calls)
        _score.calls += 1
        return _fake_score(seq[i]), {}
    _score.calls = 0

    async def _propose(**kwargs):
        return kwargs["schema"], "rat"

    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)


async def test_runner_starts_and_completes(workspace: Path, patched_loop) -> None:
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    runner = JobRunner(workspace=workspace, provider=AsyncMock(), model_id="stub")
    job_id = await runner.start(skill="autoresearch", project_id=pid, params={"max_turn": 1})
    info = await runner.wait(job_id, timeout=5.0)
    assert info.status == JobStatus.DONE
    # Events file has at least started + turn(0) + turn(1) + ended
    events_file = workspace / pid / "jobs" / f"{job_id}.jsonl"
    assert events_file.exists()
    types = [json.loads(ln)["type"] for ln in events_file.read_text().splitlines()]
    assert types[0] == "started"
    assert types[-1] == "ended"


async def test_runner_cancel(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )

    # Slow score so we have time to cancel.
    async def _score(**kwargs):
        await asyncio.sleep(0.2)
        return _fake_score(0.5), {}
    async def _propose(**kwargs):
        return kwargs["schema"], "rat"
    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)

    runner = JobRunner(workspace=workspace, provider=AsyncMock(), model_id="stub")
    job_id = await runner.start(skill="autoresearch", project_id=pid, params={"max_turn": 30})
    await asyncio.sleep(0.05)   # let the baseline turn start
    await runner.cancel(job_id)
    info = await runner.wait(job_id, timeout=5.0)
    assert info.status == JobStatus.CANCELLED


async def test_runner_pause_resume(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    seq = [0.5, 0.6, 0.7, 0.8]

    async def _score(**kwargs):
        i = min(len(seq) - 1, _score.calls)
        _score.calls += 1
        await asyncio.sleep(0.02)
        return _fake_score(seq[i]), {}
    _score.calls = 0
    async def _propose(**kwargs):
        return kwargs["schema"], "rat"
    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)

    runner = JobRunner(workspace=workspace, provider=AsyncMock(), model_id="stub")
    job_id = await runner.start(skill="autoresearch", project_id=pid, params={"max_turn": 3})
    await asyncio.sleep(0.05)
    await runner.pause(job_id)
    info = await runner.get(job_id)
    # After pause request the loop reaches the next checkpoint and reports paused.
    # Allow up to 200ms for the loop to transition.
    for _ in range(20):
        info = await runner.get(job_id)
        if info.status == JobStatus.PAUSED:
            break
        await asyncio.sleep(0.02)
    assert info.status == JobStatus.PAUSED
    await runner.resume(job_id)
    info = await runner.wait(job_id, timeout=5.0)
    assert info.status == JobStatus.DONE


async def test_runner_get_unknown_raises(workspace: Path) -> None:
    runner = JobRunner(workspace=workspace, provider=AsyncMock(), model_id="stub")
    with pytest.raises(JobNotFoundError):
        await runner.get("j_nonexistentaa")


async def test_runner_unknown_skill_raises(workspace: Path) -> None:
    pid = await create_project(workspace, name="t")
    runner = JobRunner(workspace=workspace, provider=AsyncMock(), model_id="stub")
    with pytest.raises(UnknownSkillError):
        await runner.start(skill="not_a_skill", project_id=pid, params={})


def test_safe_job_id_validates() -> None:
    from app.api.routes._safety import safe_job_id
    from fastapi import HTTPException
    assert safe_job_id("j_abc123def456") == "j_abc123def456"
    with pytest.raises(HTTPException):
        safe_job_id("../etc/passwd")
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_job_runner.py -v`
Expected: ImportError on `JobRunner` / `safe_job_id`.

- [ ] **Step 3: Implement runner**

```python
# backend/app/jobs/runner.py
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.jobs import autoresearch as ar
from app.jobs.events import append_event_jsonl, now_iso_filename_safe
from app.provider.base import Provider
from app.schemas.job import JobEvent, JobInfo, JobStatus
from app.schemas.schema_field import SchemaField
from app.workspace.ids import new_job_id
from app.workspace.paths import job_log_path, schema_path


class JobNotFoundError(KeyError):
    pass


class UnknownSkillError(ValueError):
    pass


@dataclass
class _JobHandle:
    info: JobInfo
    task: asyncio.Task[Any]
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class JobRunner:
    """Process-wide registry of running jobs.

    For now there is no concurrency cap (single-user lab tool); the loop's
    extract calls naturally pace it. Crash recovery is M3 territory."""

    def __init__(self, *, workspace: Path, provider: Provider, model_id: str) -> None:
        self.workspace = workspace
        self.provider = provider
        self.model_id = model_id
        self._jobs: dict[str, _JobHandle] = {}
        self._lock = asyncio.Lock()

    async def start(
        self, *, skill: str, project_id: str, params: dict[str, Any],
    ) -> str:
        if skill != "autoresearch":
            raise UnknownSkillError(f"unknown skill: {skill!r}")
        initial_schema = [
            SchemaField(**f) for f in json.loads(schema_path(self.workspace, project_id).read_text())
        ]
        if not initial_schema:
            raise ValueError("project has empty schema; nothing to autoresearch")
        job_id = new_job_id()
        info = JobInfo(
            job_id=job_id, project_id=project_id, skill=skill,
            status=JobStatus.PENDING, params=params,
            created_at=now_iso_filename_safe(),
        )
        pause_event = asyncio.Event()
        cancel_event = asyncio.Event()
        log_path = job_log_path(self.workspace, project_id, job_id)

        async def emit(ev: JobEvent) -> None:
            await append_event_jsonl(log_path, ev)
            # Mirror live state into JobInfo so HTTP /lab/jobs/{job_id} reads up-to-date.
            data = ev.model_dump(mode="json")
            if ev.type == "turn":
                handle.info.latest_turn = int(data.get("turn", handle.info.latest_turn))
                if data.get("saved"):
                    handle.info.best_turn = handle.info.latest_turn
                    handle.info.best_macro_f1 = float(data["macro_f1"])
            elif ev.type == "paused":
                handle.info.status = JobStatus.PAUSED
            elif ev.type == "resumed":
                handle.info.status = JobStatus.RUNNING

        async def _run() -> JobInfo:
            handle.info.status = JobStatus.RUNNING
            try:
                ar_params = ar.AutoresearchParams(
                    max_turn=int(params.get("max_turn", 30)),
                    early_stop_no_improvement=int(params.get("early_stop_no_improvement", 5)),
                )
                final = await ar.run_autoresearch_loop(
                    workspace=self.workspace, project_id=project_id, job_id=job_id,
                    initial_schema=initial_schema,
                    provider=self.provider, model_id=self.model_id,
                    params=ar_params, emit=emit,
                    cancel_event=cancel_event, pause_event=pause_event,
                )
                # Adopt loop's final status / best fields onto our live info.
                handle.info.status = final.status
                handle.info.best_turn = final.best_turn
                handle.info.best_macro_f1 = final.best_macro_f1
                return handle.info
            except Exception as exc:
                handle.info.status = JobStatus.ERROR
                handle.info.error_code = "autoresearch_failure"
                handle.info.error_message_en = str(exc)
                await append_event_jsonl(
                    log_path,
                    JobEvent(type="ended", ts=now_iso_filename_safe(),
                             reason="error", error=str(exc)),
                )
                return handle.info

        task = asyncio.create_task(_run(), name=f"job:{job_id}")
        handle = _JobHandle(info=info, task=task,
                            pause_event=pause_event, cancel_event=cancel_event)
        async with self._lock:
            self._jobs[job_id] = handle
        return job_id

    async def get(self, job_id: str) -> JobInfo:
        handle = self._jobs.get(job_id)
        if handle is None:
            raise JobNotFoundError(job_id)
        return handle.info

    async def wait(self, job_id: str, *, timeout: float | None = None) -> JobInfo:
        handle = self._jobs.get(job_id)
        if handle is None:
            raise JobNotFoundError(job_id)
        await asyncio.wait_for(handle.task, timeout=timeout)
        return handle.info

    async def pause(self, job_id: str) -> None:
        handle = self._jobs.get(job_id)
        if handle is None:
            raise JobNotFoundError(job_id)
        handle.pause_event.set()

    async def resume(self, job_id: str) -> None:
        handle = self._jobs.get(job_id)
        if handle is None:
            raise JobNotFoundError(job_id)
        handle.pause_event.clear()
        handle.info.status = JobStatus.RUNNING

    async def cancel(self, job_id: str) -> None:
        handle = self._jobs.get(job_id)
        if handle is None:
            raise JobNotFoundError(job_id)
        handle.cancel_event.set()
        handle.pause_event.clear()  # unblock paused loop so it can observe cancel
```

- [ ] **Step 4: Add `safe_job_id`**

Modify `backend/app/api/routes/_safety.py`:

```python
_JOB_ID = re.compile(r"^j_[a-z0-9]{12}$")


def safe_job_id(job_id: str) -> str:
    if not _JOB_ID.match(job_id):
        raise HTTPException(status_code=400, detail="invalid job_id")
    return job_id
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_job_runner.py -v`
Expected: 6 passed.

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: 167 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/jobs/runner.py backend/app/api/routes/_safety.py backend/tests/unit/test_job_runner.py
git commit -m "feat(jobs): JobRunner singleton (start/get/pause/resume/cancel/wait)"
```

---

### Task 9: process-wide JobRunner factory

**Files:**
- Modify: `backend/app/jobs/__init__.py`

Expose a module-level `get_runner(workspace, provider, model_id)` factory that returns a single shared `JobRunner` instance. Subsequent calls return the same instance regardless of args (warns if args differ — for v1 just return the cached one).

- [ ] **Step 1: Append failing test**

Append to `backend/tests/unit/test_job_runner.py`:

```python
async def test_get_runner_singleton(workspace: Path) -> None:
    from app.jobs import get_runner, reset_runner_for_tests
    reset_runner_for_tests()
    a = get_runner(workspace=workspace, provider=AsyncMock(), model_id="stub")
    b = get_runner(workspace=workspace, provider=AsyncMock(), model_id="stub")
    assert a is b
    reset_runner_for_tests()  # leave clean for next test
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_job_runner.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/jobs/__init__.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.jobs.runner import JobRunner
from app.provider.base import Provider


_runner: Optional[JobRunner] = None


def get_runner(*, workspace: Path, provider: Provider, model_id: str) -> JobRunner:
    """Return the process-wide JobRunner. First call creates it; subsequent
    calls return the same instance regardless of args."""
    global _runner
    if _runner is None:
        _runner = JobRunner(workspace=workspace, provider=provider, model_id=model_id)
    return _runner


def reset_runner_for_tests() -> None:
    """Test-only: drop the cached singleton so the next get_runner re-creates."""
    global _runner
    _runner = None
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_job_runner.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/__init__.py backend/tests/unit/test_job_runner.py
git commit -m "feat(jobs): get_runner singleton factory"
```

---

## Phase 4 — Chat SSE pairing

### Task 10: emit `tool_result` SSE event with `tool_use_id` pairing

**Files:**
- Modify: `backend/app/chat/service.py`
- Create: `backend/tests/unit/test_chat_tool_result.py`

INSIGHTS.md #7 explicitly anticipated this M2C work: when a `ToolResultBlock` arrives, emit a `tool_result` event containing `{tool_use_id, result_text, ok}`. Frontend uses the `tool_use_id` to attach the result to the existing `tool_call` card. Without this the frontend can't see the `job_id` returned by `start_job`.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_chat_tool_result.py
from app.chat.service import _events_from_message
from claude_agent_sdk import (
    AssistantMessage, ToolResultBlock, ToolUseBlock,
)


def test_tool_use_block_emits_tool_call() -> None:
    msg = AssistantMessage(
        content=[ToolUseBlock(id="t1", name="mcp__emerge_tools__start_job",
                              input={"skill": "autoresearch", "project_id": "p_x"})],
        model="m",
    )
    events = _events_from_message(msg)
    assert len(events) == 1
    etype, payload = events[0]
    assert etype == "tool_call"
    assert payload["tool_use_id"] == "t1"
    assert payload["tool_name"] == "mcp__emerge_tools__start_job"


def test_tool_result_block_emits_tool_result_event() -> None:
    msg = AssistantMessage(
        content=[
            ToolResultBlock(tool_use_id="t1", content="j_abc123def456", is_error=False),
        ],
        model="m",
    )
    events = _events_from_message(msg)
    assert len(events) == 1
    etype, payload = events[0]
    assert etype == "tool_result"
    assert payload["tool_use_id"] == "t1"
    assert payload["result_text"] == "j_abc123def456"
    assert payload["ok"] is True


def test_tool_result_block_handles_list_content() -> None:
    """SDK sometimes provides ToolResultBlock.content as a list of dicts."""
    msg = AssistantMessage(
        content=[
            ToolResultBlock(
                tool_use_id="t2",
                content=[{"type": "text", "text": "hello"}],
                is_error=False,
            ),
        ],
        model="m",
    )
    events = _events_from_message(msg)
    assert events[0][1]["result_text"] == "hello"


def test_tool_result_block_is_error_propagates() -> None:
    msg = AssistantMessage(
        content=[
            ToolResultBlock(tool_use_id="t3", content="boom", is_error=True),
        ],
        model="m",
    )
    events = _events_from_message(msg)
    assert events[0][1]["ok"] is False
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_chat_tool_result.py -v`
Expected: failures — current code drops ToolResultBlock.

- [ ] **Step 3: Update `_events_from_message` in `backend/app/chat/service.py`**

Replace the `elif isinstance(block, ToolResultBlock):` branch with:

```python
            elif isinstance(block, ToolResultBlock):
                # Emit a `tool_result` event paired by tool_use_id. Frontend looks
                # up the matching `tool_call` card and attaches the result.
                # Insight #7: the original drop-the-block design left the
                # frontend blind to tool output. M2C needs job_id surfaced
                # so the JobProgressCard can subscribe to /lab/jobs/{job_id}/events.
                content = block.content
                if isinstance(content, list):
                    text_pieces = [
                        c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    ]
                    result_text = "".join(text_pieces)
                else:
                    result_text = str(content) if content is not None else ""
                out.append(
                    (
                        "tool_result",
                        {
                            "tool_use_id": block.tool_use_id,
                            "result_text": result_text,
                            "ok": not block.is_error,
                        },
                    )
                )
                continue
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_chat_tool_result.py tests/integration/test_chat_service.py -v`
Expected: 4 new passes; existing chat tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/service.py backend/tests/unit/test_chat_tool_result.py
git commit -m "feat(chat): pair ToolResultBlock to tool_call via tool_use_id (Insight #7)"
```

---

## Phase 5 — Tools + skill + chat

### Task 11: Job MCP tools (`start_job`, `get_job`, `pause_job`, `resume_job`, `cancel_job`)

**Files:**
- Create: `backend/app/tools/jobs.py`
- Modify: `backend/app/tools/__init__.py`
- Modify: `backend/tests/unit/test_tool_registration.py`
- Create: `backend/tests/unit/test_tool_jobs.py`

The tools wrap the JobRunner. They take a `JobRunner` arg via closure (extend `build_emerge_mcp` signature).

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
        "score",
        # M2C additions
        "start_job",
        "get_job",
        "pause_job",
        "resume_job",
        "cancel_job",
    }
```

Also update `build_emerge_mcp` invocations to pass a stub runner:

```python
async def test_build_emerge_mcp_lists_tools(workspace: Path, stub_provider: AsyncMock) -> None:
    from app.jobs.runner import JobRunner
    runner = JobRunner(workspace=workspace, provider=stub_provider, model_id="stub")
    server = build_emerge_mcp(workspace=workspace, provider=stub_provider, job_runner=runner)
    ...
```

- [ ] **Step 2: Write failing tests for tool wrappers**

```python
# backend/tests/unit/test_tool_jobs.py
from pathlib import Path
from unittest.mock import AsyncMock

from app.jobs.runner import JobRunner
from app.schemas.job import JobInfo, JobStatus
from app.tools import jobs as tool_jobs


async def test_start_job_returns_job_id(workspace: Path) -> None:
    runner = AsyncMock(spec=JobRunner)
    runner.start.return_value = "j_abc123def456"
    out = await tool_jobs.start_job_impl(runner, skill="autoresearch", project_id="p_x", params={"max_turn": 10})
    assert out == "j_abc123def456"
    runner.start.assert_awaited_once_with(skill="autoresearch", project_id="p_x", params={"max_turn": 10})


async def test_get_job_returns_info_dict(workspace: Path) -> None:
    runner = AsyncMock(spec=JobRunner)
    runner.get.return_value = JobInfo(
        job_id="j_x", project_id="p_x", skill="autoresearch",
        status=JobStatus.RUNNING, params={}, created_at="t",
    )
    out = await tool_jobs.get_job_impl(runner, job_id="j_x")
    assert out["status"] == "running"
    assert out["job_id"] == "j_x"
```

- [ ] **Step 3: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_tool_jobs.py tests/unit/test_tool_registration.py -v`
Expected: ImportError on `tools/jobs.py` and assertion in registration test.

- [ ] **Step 4: Implement tool wrappers**

```python
# backend/app/tools/jobs.py
from __future__ import annotations

from typing import Any

from app.jobs.runner import JobRunner


async def start_job_impl(runner: JobRunner, *, skill: str, project_id: str, params: dict[str, Any]) -> str:
    return await runner.start(skill=skill, project_id=project_id, params=params)


async def get_job_impl(runner: JobRunner, *, job_id: str) -> dict[str, Any]:
    info = await runner.get(job_id)
    return info.model_dump(mode="json")


async def pause_job_impl(runner: JobRunner, *, job_id: str) -> None:
    await runner.pause(job_id)


async def resume_job_impl(runner: JobRunner, *, job_id: str) -> None:
    await runner.resume(job_id)


async def cancel_job_impl(runner: JobRunner, *, job_id: str) -> None:
    await runner.cancel(job_id)
```

- [ ] **Step 5: Register MCP tools**

Modify `backend/app/tools/__init__.py`:

```python
def build_emerge_mcp(
    workspace: Path,
    provider: Provider,
    job_runner: "JobRunner",   # forward-ref import below
) -> McpSdkServerConfig:
```

Add `from app.jobs.runner import JobRunner` and `from app.tools import jobs as jobs_mod`. Inside the builder, before the `return create_sdk_mcp_server(...)` line, register:

```python
    @tool(
        "start_job",
        "Kick off a background job. v1 supports skill='autoresearch'. Returns a job_id; subscribe to /lab/jobs/{job_id}/events for progress.",
        {"skill": str, "project_id": str, "params": dict},
    )
    async def t_start_job(args: dict[str, Any]) -> dict[str, Any]:
        jid = await jobs_mod.start_job_impl(
            job_runner, skill=args["skill"], project_id=args["project_id"],
            params=args.get("params") or {},
        )
        return {"content": [{"type": "text", "text": jid}]}

    @tool("get_job", "Get current job status (latest turn, best F1 so far).", {"job_id": str})
    async def t_get_job(args: dict[str, Any]) -> dict[str, Any]:
        info = await jobs_mod.get_job_impl(job_runner, job_id=args["job_id"])
        return {"content": [{"type": "text", "text": str(info)}]}

    @tool("pause_job", "Pause a running job at the next turn boundary.", {"job_id": str})
    async def t_pause_job(args: dict[str, Any]) -> dict[str, Any]:
        await jobs_mod.pause_job_impl(job_runner, job_id=args["job_id"])
        return {"content": [{"type": "text", "text": "paused"}]}

    @tool("resume_job", "Resume a paused job.", {"job_id": str})
    async def t_resume_job(args: dict[str, Any]) -> dict[str, Any]:
        await jobs_mod.resume_job_impl(job_runner, job_id=args["job_id"])
        return {"content": [{"type": "text", "text": "resumed"}]}

    @tool("cancel_job", "Cancel a running or paused job. Discards remaining turns.", {"job_id": str})
    async def t_cancel_job(args: dict[str, Any]) -> dict[str, Any]:
        await jobs_mod.cancel_job_impl(job_runner, job_id=args["job_id"])
        return {"content": [{"type": "text", "text": "cancelled"}]}
```

Add the new tools to the `tools=[...]` list in `create_sdk_mcp_server(...)`.

- [ ] **Step 6: Update chat service constructor**

In `backend/app/chat/service.py`, modify `ChatService.__init__` to construct a runner:

```python
from app.jobs import get_runner

class ChatService:
    def __init__(
        self, *,
        workspace: Path,
        provider: Provider,
        agent_model: str = "claude-sonnet-4-6",
        extract_model: str = "gemini-2.0-flash",
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self.agent_model = agent_model
        self.system_prompt = load_skill("emerge_extractor")
        self.job_runner = get_runner(
            workspace=workspace, provider=provider, model_id=extract_model,
        )
        self.mcp_server = build_emerge_mcp(
            workspace=workspace, provider=provider, job_runner=self.job_runner,
        )
```

Update `backend/app/api/routes/chat.py` `_get_chat_service()` to pass `extract_model=settings.default_extract_model`.

- [ ] **Step 7: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_tool_jobs.py tests/unit/test_tool_registration.py tests/integration/test_chat_service.py -v`
Expected: all pass.

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: 175 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/tools/jobs.py backend/app/tools/__init__.py backend/app/chat/service.py backend/app/api/routes/chat.py backend/tests/unit/test_tool_jobs.py backend/tests/unit/test_tool_registration.py
git commit -m "feat(tools): start/get/pause/resume/cancel_job MCP tools"
```

---

### Task 12: `emerge-autoresearch` SKILL.md + multi-skill loader

**Files:**
- Create: `backend/app/skills/emerge_autoresearch.md`
- Modify: `backend/app/skills/__init__.py`
- Create: `backend/tests/unit/test_skills_loader.py`

Skill content tells the agent what to do when `/improve` arrives: ensure ≥5 reviewed, then call `start_job(skill='autoresearch', project_id=…, params={…})` and tell the user to watch the progress card.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_skills_loader.py
import pytest

from app.skills import load_skill, load_skills


def test_load_skill_extractor() -> None:
    text = load_skill("emerge_extractor")
    assert "emerge-extractor" in text


def test_load_skill_autoresearch_exists() -> None:
    text = load_skill("emerge_autoresearch")
    assert "autoresearch" in text.lower()
    # Discipline red lines must be encoded
    assert "schema.json" in text  # never directly mutate
    assert "candidate" in text.lower()


def test_load_skills_concatenates_with_separator() -> None:
    text = load_skills(["emerge_extractor", "emerge_autoresearch"])
    assert "emerge-extractor" in text
    assert "autoresearch" in text.lower()
    # A clear visual divider so the agent sees them as two skills
    assert "---" in text or "\n\n---\n\n" in text


def test_load_skill_missing_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_skill("not_a_real_skill")
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_skills_loader.py -v`
Expected: FileNotFoundError on missing autoresearch skill, ImportError on `load_skills`.

- [ ] **Step 3: Create the autoresearch SKILL**

Write `backend/app/skills/emerge_autoresearch.md`:

```markdown
<!-- backend/app/skills/emerge_autoresearch.md -->
# emerge-autoresearch (loaded on /improve)

You are running the autoresearch loop on top of the extractor skill. Your job
on this turn is to KICK OFF a background job — not to run the loop yourself.

## Discipline (red lines — never violate)

- AutoResearch NEVER auto-promotes. The job writes candidates to
  `versions/_candidate/{job_id}/turn_{k}.json`. The user must explicitly
  click "accept" to overwrite `schema.json`.
- The proposer LLM may only edit `description` text. Field add/remove/
  rename/retype is forbidden — the job's response_schema enforces this and
  rejects violations as proposer_failed events.
- Counterexample triplets (M3 territory) must NEVER enter the proposer prompt.
  In M2C only `_notes` from reviewed examples feed the proposer as
  high-priority hints.
- Bound by `max_turn` and `early_stop_no_improvement`. No token / $ budget.

## Workflow on `/improve`

1. Call `list_reviewed`. If fewer than 5 reviewed examples exist, stop here:
   tell the user "/improve needs ≥5 reviewed examples to have signal — you
   currently have N. Please /review more docs first." Do NOT call start_job.
2. Otherwise call `start_job` with:
   ```
   {"skill": "autoresearch", "project_id": <pid>,
    "params": {"max_turn": 30, "early_stop_no_improvement": 5}}
   ```
   The tool returns a `job_id` string.
3. Tell the user briefly: "Started autoresearch (job <id>). The progress
   card below streams per-turn F1. You can pause / cancel at any time, and
   accept the best candidate when you're satisfied."

Do NOT call extract_one / extract_batch / score yourself in the /improve
turn — the job loop owns those.

## Slash commands relevant here

- `/improve` — entry point handled by this skill.
- `/pause`, `/resume`, `/cancel` — direct frontend buttons on the job card.
  If the user types them in chat, call `pause_job` / `resume_job` /
  `cancel_job` with the most recent `job_id`.

## When the job ends

The frontend's progress card subscribes to `/lab/jobs/{job_id}/events` and
shows the user the best candidate. Acceptance is a UI button calling
`/lab/projects/{pid}/schema/accept-candidate` directly — you do NOT
overwrite `schema.json` from chat.
```

- [ ] **Step 4: Add `load_skills`**

Modify `backend/app/skills/__init__.py`:

```python
from pathlib import Path

_SKILLS_DIR = Path(__file__).parent


def load_skill(name: str) -> str:
    p = _SKILLS_DIR / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"skill not found: {name}")
    return p.read_text(encoding="utf-8")


def load_skills(names: list[str]) -> str:
    """Concatenate multiple skills with a visual divider so the agent reads
    them as distinct discipline pages."""
    return "\n\n---\n\n".join(load_skill(n) for n in names)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_skills_loader.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/skills/__init__.py backend/app/skills/emerge_autoresearch.md backend/tests/unit/test_skills_loader.py
git commit -m "feat(skills): emerge-autoresearch skill + load_skills concat helper"
```

---

### Task 13: ChatService loads autoresearch on `/improve`

**Files:**
- Modify: `backend/app/chat/service.py`
- Modify: `backend/tests/integration/test_chat_service.py`

When the user message starts with `/improve`, build the system prompt by concatenating extractor + autoresearch skills. Otherwise extractor only.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/integration/test_chat_service.py`:

```python
def _build_options_for(svc: ChatService, msg: str) -> str:
    """Re-construct the system_prompt the service would send for this user
    message. Uses the new _select_system_prompt helper."""
    return svc._select_system_prompt(msg)


def test_improve_loads_autoresearch_skill(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    text = _build_options_for(svc, "/improve")
    assert "emerge-extractor" in text
    assert "emerge-autoresearch" in text


def test_non_improve_keeps_extractor_only(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    text = _build_options_for(svc, "give me a status update")
    assert "emerge-extractor" in text
    assert "emerge-autoresearch" not in text


def test_leading_space_or_slash_both_match_improve(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    assert "emerge-autoresearch" in _build_options_for(svc, "/improve")
    assert "emerge-autoresearch" in _build_options_for(svc, " /improve")
    assert "emerge-autoresearch" in _build_options_for(svc, "/improve please")
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/integration/test_chat_service.py -v`
Expected: failures — no `_select_system_prompt`.

- [ ] **Step 3: Implement skill selection**

Modify `backend/app/chat/service.py`:

```python
from app.skills import load_skill, load_skills


class ChatService:
    # __init__ now also loads the autoresearch skill content (cheap, one-time)
    def __init__(self, *, workspace, provider, agent_model="claude-sonnet-4-6", extract_model="gemini-2.0-flash"):
        ...
        self._extractor_skill = load_skill("emerge_extractor")
        self._autoresearch_skill = load_skill("emerge_autoresearch")
        # Default system_prompt for non-/improve turns; recomputed per turn below.
        self.system_prompt = self._extractor_skill
        ...

    def _select_system_prompt(self, user_message: str) -> str:
        """Choose which skills to load based on the slash intent."""
        stripped = user_message.lstrip()
        if stripped.startswith("/improve"):
            return self._extractor_skill + "\n\n---\n\n" + self._autoresearch_skill
        return self._extractor_skill
```

In `chat_turn`, change `_build_options` to accept the user_message and pick the prompt:

```python
    def _build_options(self, user_message: str) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            system_prompt=self._select_system_prompt(user_message),
            ...
        )
```

And in `chat_turn`:

```python
        options = self._build_options(user_message)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_chat_service.py -v`
Expected: 3 new passes.

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: ~178 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/service.py backend/tests/integration/test_chat_service.py
git commit -m "feat(chat): load autoresearch skill on /improve"
```

---

## Phase 6 — HTTP routes

### Task 14: GET `/lab/jobs/{job_id}` (status) + GET `/lab/jobs/{job_id}/events` (SSE)

**Files:**
- Create: `backend/app/api/routes/jobs.py`
- Modify: `backend/app/main.py` (mount router)
- Create: `backend/tests/integration/test_lab_jobs.py`

Frontend's `useJob` store subscribes to the SSE route. The status route is for non-streaming polls (e.g. test setups, fallback).

The SSE route reads `jobs/{job_id}.jsonl` from the start, then watches the file for new lines. On reconnect with `Last-Event-ID` (or just simpler: read all + tail), the client gets backfilled events. v1 uses a simple poll-tail loop with 200ms granularity — no inotify.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/integration/test_lab_jobs.py
import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.jobs import autoresearch as ar
from app.jobs import reset_runner_for_tests
from app.main import app
from app.schemas.schema_field import FieldType, SchemaField
from app.schemas.score import FieldScore, ScoreResult
from app.tools.projects import create_project
from app.tools.schema import write_schema


def _fake_score(macro_f1):
    return ScoreResult(
        n_docs=1, n_reviewed=1, macro_f1=macro_f1,
        per_field=[FieldScore(field="x", tp=1, fp=0, fn=0, support=1,
                              precision=1.0, recall=1.0, f1=macro_f1)],
        errors=[], ts="t", schema_field_count=1,
    )


@pytest.fixture(autouse=True)
def _reset_runner_singleton():
    reset_runner_for_tests()
    yield
    reset_runner_for_tests()


async def test_get_job_status(workspace: Path, monkeypatch) -> None:
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )

    async def _score(**kwargs): return _fake_score(0.5), {}
    async def _propose(**kwargs): return kwargs["schema"], "rat"
    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)

    client = TestClient(app)
    r = client.post(f"/lab/jobs", json={"skill": "autoresearch", "project_id": pid, "params": {"max_turn": 0}})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    # Wait a moment for the job to finish.
    await asyncio.sleep(0.2)
    r2 = client.get(f"/lab/jobs/{job_id}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["job_id"] == job_id
    assert body["status"] in ("running", "done")


def test_get_job_events_sse_streams(workspace: Path, monkeypatch) -> None:
    """Smoke: connecting to the SSE endpoint returns an event-stream content
    type and at least one line. Full event semantics are covered in
    test_autoresearch_loop / test_job_runner."""
    # Create a job log file directly to avoid needing a live job.
    pid = "p_aaaaaaaaaaaa"
    job_id = "j_xxxxxxxxxxxx"
    p = workspace / pid / "jobs" / f"{job_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"type": "started", "ts": "t0"}) + "\n", encoding="utf-8")

    client = TestClient(app)
    with client.stream("GET", f"/lab/jobs/{job_id}/events?project_id={pid}") as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        # Read a small chunk and verify the started event arrives.
        body = b""
        for chunk in r.iter_raw():
            body += chunk
            if b"\"type\": \"started\"" in body:
                break
        assert b"started" in body


def test_get_job_unknown_id_404() -> None:
    client = TestClient(app)
    r = client.get("/lab/jobs/j_nonexistentaa")
    assert r.status_code == 404


async def test_post_job_cancel(workspace: Path, monkeypatch) -> None:
    async def _score(**kwargs):
        await asyncio.sleep(0.5)
        return _fake_score(0.5), {}
    async def _propose(**kwargs): return kwargs["schema"], "rat"
    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)

    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    client = TestClient(app)
    r = client.post("/lab/jobs", json={"skill": "autoresearch", "project_id": pid, "params": {"max_turn": 30}})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    rc = client.post(f"/lab/jobs/{job_id}/cancel")
    assert rc.status_code == 200
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/integration/test_lab_jobs.py -v`
Expected: 404 — not mounted.

- [ ] **Step 3: Implement router**

```python
# backend/app/api/routes/jobs.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.routes._safety import safe_job_id, safe_project_id
from app.config import get_settings
from app.jobs import get_runner
from app.jobs.runner import JobNotFoundError, UnknownSkillError
from app.provider import get_provider_for_model
from app.workspace.paths import job_log_path


router = APIRouter()


class StartJobBody(BaseModel):
    skill: str
    project_id: str
    params: dict[str, Any] = {}


def _get_runner():
    settings = get_settings()
    provider = get_provider_for_model(settings.default_extract_model)
    return get_runner(
        workspace=settings.workspace_root, provider=provider,
        model_id=settings.default_extract_model,
    )


@router.post("/lab/jobs")
async def start_job(body: StartJobBody) -> dict:
    safe_project_id(body.project_id)
    runner = _get_runner()
    try:
        jid = await runner.start(skill=body.skill, project_id=body.project_id, params=body.params)
    except UnknownSkillError as exc:
        raise HTTPException(status_code=400, detail={"error_code": "unknown_skill", "error_message_en": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error_code": "invalid_request", "error_message_en": str(exc)})
    return {"job_id": jid}


@router.get("/lab/jobs/{job_id}")
async def get_job_status(job_id: str) -> dict:
    safe_job_id(job_id)
    runner = _get_runner()
    try:
        info = await runner.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"})
    return info.model_dump(mode="json")


@router.post("/lab/jobs/{job_id}/pause")
async def post_pause(job_id: str) -> dict:
    safe_job_id(job_id)
    runner = _get_runner()
    try:
        await runner.pause(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"})
    return {"ok": True}


@router.post("/lab/jobs/{job_id}/resume")
async def post_resume(job_id: str) -> dict:
    safe_job_id(job_id)
    runner = _get_runner()
    try:
        await runner.resume(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"})
    return {"ok": True}


@router.post("/lab/jobs/{job_id}/cancel")
async def post_cancel(job_id: str) -> dict:
    safe_job_id(job_id)
    runner = _get_runner()
    try:
        await runner.cancel(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"})
    return {"ok": True}


@router.get("/lab/jobs/{job_id}/events")
async def get_job_events(
    job_id: str,
    project_id: str = Query(...),
) -> EventSourceResponse:
    """Tail the job's JSONL file as SSE. Backfills existing events on connect,
    then watches for new lines via 200ms poll. Closes when an `ended` event
    is observed (or after 30s of no new events post-end)."""
    safe_job_id(job_id)
    safe_project_id(project_id)
    settings = get_settings()
    log_path = job_log_path(settings.workspace_root, project_id, job_id)

    async def gen():
        seen = 0
        ended = False
        # Allow the file to appear (race against runner.start which writes it).
        for _ in range(25):  # ~5s max
            if log_path.exists():
                break
            await asyncio.sleep(0.2)
        if not log_path.exists():
            yield {"event": "error", "data": json.dumps({"error_code": "job_not_found"})}
            return
        while True:
            text = log_path.read_text(encoding="utf-8")
            lines = [ln for ln in text.split("\n") if ln.strip()]
            for ln in lines[seen:]:
                try:
                    blob = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                yield {"event": "job_event", "data": json.dumps(blob, ensure_ascii=False)}
                if blob.get("type") == "ended":
                    ended = True
            seen = len(lines)
            if ended:
                return
            await asyncio.sleep(0.2)

    return EventSourceResponse(gen())
```

Mount in `backend/app/main.py`:

```python
from app.api.routes import jobs as jobs_route
...
app.include_router(jobs_route.router)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_lab_jobs.py -v`
Expected: 4 passed.

Full suite: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: ~182 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/jobs.py backend/app/main.py backend/tests/integration/test_lab_jobs.py
git commit -m "feat(api): /lab/jobs (start), /lab/jobs/{id} (status), /lab/jobs/{id}/events (SSE), pause/resume/cancel"
```

---

### Task 15: POST `/lab/projects/{pid}/schema/accept-candidate` + GET `/lab/projects/{pid}/schema`

**Files:**
- Create: `backend/app/api/routes/schema.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_lab_accept_candidate.py`

The accept-candidate route reads `versions/_candidate/{job_id}/turn_{k}.json`, extracts its `schema`, and writes it to `schema.json` via `write_schema(allow_structural=False)` — by definition only descriptions changed. The GET schema route is what `frontend/ReviewMode/ReviewMode.tsx` already calls (`fetchSchema`); M2A shipped the call but the route was missing — fix it here.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/integration/test_lab_accept_candidate.py
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.projects import create_project
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import candidate_dir, candidate_turn_path, schema_path


async def test_get_schema_returns_current(workspace: Path) -> None:
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/schema")
    assert r.status_code == 200
    fields = r.json()
    assert fields[0]["name"] == "invoice_no"


async def test_accept_candidate_overwrites_schema(workspace: Path) -> None:
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="OLD")],
        reason="seed", allow_structural=True,
    )
    job_id = "j_aaaaaaaaaaaa"
    candidate_dir(workspace, pid, job_id).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        candidate_turn_path(workspace, pid, job_id, 3),
        {
            "turn": 3, "parent_turn": 0,
            "schema": [{"name": "invoice_no", "type": "string", "description": "NEW"}],
            "rationale": "tightened",
            "macro_f1": 0.92, "per_field": [], "predictions": {}, "ts": "t",
        },
    )
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/schema/accept-candidate",
        json={"job_id": job_id, "turn": 3},
    )
    assert r.status_code == 200
    new_schema = json.loads(schema_path(workspace, pid).read_text())
    assert new_schema[0]["description"] == "NEW"


async def test_accept_candidate_404_on_missing_candidate(workspace: Path) -> None:
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/schema/accept-candidate",
        json={"job_id": "j_nonexistentaa", "turn": 1},
    )
    assert r.status_code == 404


async def test_accept_candidate_rejects_structural_diff(workspace: Path) -> None:
    """If a malformed candidate file tries to add a new field, reject."""
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    job_id = "j_aaaaaaaaaaaa"
    candidate_dir(workspace, pid, job_id).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        candidate_turn_path(workspace, pid, job_id, 1),
        {
            "turn": 1, "parent_turn": 0,
            "schema": [
                {"name": "x", "type": "string", "description": "d"},
                {"name": "snuck_in", "type": "string", "description": "e"},
            ],
            "rationale": "bad", "macro_f1": 0.5, "per_field": [],
            "predictions": {}, "ts": "t",
        },
    )
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/schema/accept-candidate",
        json={"job_id": job_id, "turn": 1},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/integration/test_lab_accept_candidate.py -v`
Expected: 404 (not mounted).

- [ ] **Step 3: Implement router**

```python
# backend/app/api/routes/schema.py
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.routes._safety import safe_job_id, safe_project_id
from app.config import get_settings
from app.schemas.schema_field import SchemaField
from app.tools.schema import StructuralChangeError, write_schema
from app.workspace.paths import candidate_turn_path, schema_path


router = APIRouter()


class AcceptBody(BaseModel):
    job_id: str
    turn: int


@router.get("/lab/projects/{project_id}/schema")
async def get_schema(project_id: str) -> list[dict]:
    safe_project_id(project_id)
    settings = get_settings()
    p = schema_path(settings.workspace_root, project_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail={"error_code": "schema_not_found"})
    return json.loads(p.read_text())


@router.post("/lab/projects/{project_id}/schema/accept-candidate")
async def accept_candidate(project_id: str, body: AcceptBody) -> dict:
    safe_project_id(project_id)
    safe_job_id(body.job_id)
    settings = get_settings()
    cp = candidate_turn_path(settings.workspace_root, project_id, body.job_id, body.turn)
    if not cp.exists():
        raise HTTPException(status_code=404, detail={"error_code": "candidate_not_found"})
    blob = json.loads(cp.read_text())
    fields_blob = blob.get("schema") or []
    fields = [SchemaField(**f) for f in fields_blob]
    try:
        await write_schema(
            settings.workspace_root, project_id, fields,
            reason=f"accept candidate j={body.job_id} turn={body.turn}",
            allow_structural=False,
        )
    except StructuralChangeError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "structural_change_in_candidate", "error_message_en": str(exc)},
        )
    return {"ok": True, "rationale": blob.get("rationale", "")}
```

Mount in `backend/app/main.py`:

```python
from app.api.routes import schema as schema_route
...
app.include_router(schema_route.router)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_lab_accept_candidate.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/schema.py backend/app/main.py backend/tests/integration/test_lab_accept_candidate.py
git commit -m "feat(api): GET /lab/projects/{pid}/schema + POST .../schema/accept-candidate"
```

---

## Phase 7 — Frontend job UI

### Task 16: `useJob` store + types + api helpers

**Files:**
- Create: `frontend/src/types/job.ts`
- Create: `frontend/src/stores/jobs.ts`
- Modify: `frontend/src/lib/api.ts`

The store opens an SSE connection to `/lab/jobs/{job_id}/events?project_id=…`, parses `job_event` messages into typed turn / paused / resumed / ended states, exposes `pause()` / `resume()` / `cancel()` / `accept(turn)`.

- [ ] **Step 1: Add types**

```typescript
// frontend/src/types/job.ts
export interface FieldScoreSummary {
  field: string
  tp: number
  fp: number
  fn: number
  support: number
  precision: number
  recall: number
  f1: number
}

export interface TurnEvent {
  type: 'turn'
  turn: number
  macro_f1: number
  per_field: FieldScoreSummary[]
  saved: boolean
  rationale?: string
}

export interface JobLifecycleEvent {
  type: 'started' | 'paused' | 'resumed' | 'proposer_failed' | 'ended'
  ts: string
  reason?: 'max_turn' | 'early_stop' | 'cancelled' | 'error'
  best_turn?: number
  best_macro_f1?: number
  error?: string
}

export type JobEvent = TurnEvent | JobLifecycleEvent

export type JobStatus = 'pending' | 'running' | 'paused' | 'done' | 'cancelled' | 'error'
```

- [ ] **Step 2: Add API helpers**

Append to `frontend/src/lib/api.ts`:

```typescript
export async function startJob(projectId: string, params: Record<string, unknown> = {}): Promise<{ job_id: string }> {
  const r = await fetch('/lab/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skill: 'autoresearch', project_id: projectId, params }),
  })
  if (!r.ok) throw new Error(`startJob ${r.status}`)
  return r.json()
}

export async function pauseJob(jobId: string): Promise<void> {
  const r = await fetch(`/lab/jobs/${jobId}/pause`, { method: 'POST' })
  if (!r.ok) throw new Error(`pauseJob ${r.status}`)
}

export async function resumeJob(jobId: string): Promise<void> {
  const r = await fetch(`/lab/jobs/${jobId}/resume`, { method: 'POST' })
  if (!r.ok) throw new Error(`resumeJob ${r.status}`)
}

export async function cancelJob(jobId: string): Promise<void> {
  const r = await fetch(`/lab/jobs/${jobId}/cancel`, { method: 'POST' })
  if (!r.ok) throw new Error(`cancelJob ${r.status}`)
}

export async function acceptCandidate(projectId: string, jobId: string, turn: number): Promise<{ ok: boolean }> {
  const r = await fetch(`/lab/projects/${projectId}/schema/accept-candidate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, turn }),
  })
  if (!r.ok) throw new Error(`acceptCandidate ${r.status}`)
  return r.json()
}

export function jobEventsUrl(projectId: string, jobId: string): string {
  return `/lab/jobs/${jobId}/events?project_id=${encodeURIComponent(projectId)}`
}
```

- [ ] **Step 3: Implement store**

```typescript
// frontend/src/stores/jobs.ts
import { create } from 'zustand'

import { jobEventsUrl, pauseJob, resumeJob, cancelJob, acceptCandidate } from '../lib/api'
import { streamSSE } from '../lib/sse'
import type { JobEvent, JobStatus, TurnEvent } from '../types/job'

interface State {
  status: JobStatus
  jobId: string | null
  projectId: string | null
  turns: TurnEvent[]
  bestTurn: TurnEvent | null
  endedReason: string | null
  err: string | null
  subscribe: (projectId: string, jobId: string) => Promise<void>
  pause: () => Promise<void>
  resume: () => Promise<void>
  cancel: () => Promise<void>
  accept: (turn: number) => Promise<void>
  reset: () => void
}

export const useJob = create<State>((set, get) => ({
  status: 'pending',
  jobId: null,
  projectId: null,
  turns: [],
  bestTurn: null,
  endedReason: null,
  err: null,
  reset: () => set({ status: 'pending', jobId: null, projectId: null, turns: [], bestTurn: null, endedReason: null, err: null }),
  subscribe: async (projectId, jobId) => {
    set({ status: 'running', jobId, projectId, turns: [], bestTurn: null, endedReason: null, err: null })
    try {
      for await (const ev of streamSSE(jobEventsUrl(projectId, jobId), { method: 'GET' })) {
        if (ev.event !== 'job_event') continue
        const data = ev.data as JobEvent
        if (data.type === 'turn') {
          set(s => {
            const turns = [...s.turns, data]
            const best = data.saved && (!s.bestTurn || data.macro_f1 > s.bestTurn.macro_f1) ? data : s.bestTurn
            return { turns, bestTurn: best }
          })
        } else if (data.type === 'paused') {
          set({ status: 'paused' })
        } else if (data.type === 'resumed') {
          set({ status: 'running' })
        } else if (data.type === 'ended') {
          const reason = data.reason ?? null
          const status: JobStatus = reason === 'cancelled' ? 'cancelled' : reason === 'error' ? 'error' : 'done'
          set({ status, endedReason: reason })
        }
      }
    } catch (e) {
      set({ err: String(e), status: 'error' })
    }
  },
  pause: async () => { const { jobId } = get(); if (jobId) await pauseJob(jobId) },
  resume: async () => { const { jobId } = get(); if (jobId) await resumeJob(jobId) },
  cancel: async () => { const { jobId } = get(); if (jobId) await cancelJob(jobId) },
  accept: async (turn) => {
    const { jobId, projectId } = get()
    if (!jobId || !projectId) return
    await acceptCandidate(projectId, jobId, turn)
  },
}))
```

- [ ] **Step 4: Build to confirm types**

```
cd frontend && npm run build 2>&1 | tail -8
```
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/job.ts frontend/src/stores/jobs.ts frontend/src/lib/api.ts
git commit -m "feat(frontend): useJob store, job api helpers, JobEvent types"
```

---

### Task 17: `JobProgressCard` + chat store wiring + MessageList

**Files:**
- Modify: `frontend/src/types/chat.ts`
- Modify: `frontend/src/stores/chat.ts`
- Create: `frontend/src/components/Chat/JobProgressCard.tsx`
- Modify: `frontend/src/components/Chat/MessageList.tsx`
- Create: `frontend/tests/unit/JobProgressCard.test.tsx`

Backend now emits `tool_result` events paired by `tool_use_id` (T10). The chat store updates the matching `tool_call` event so frontend can read the `start_job` result. `MessageList` detects a `tool_call` whose name is `mcp__emerge_tools__start_job` and whose `tool_result` contains a job_id, then renders `JobProgressCard` with `useJob` subscription.

- [ ] **Step 1: Extend chat types**

In `frontend/src/types/chat.ts`:

```typescript
export type ChatEvent =
  | { type: 'user'; text: string }
  | { type: 'agent_text'; text: string }
  | { type: 'tool_call'; tool_use_id?: string; tool_name: string; tool_input: unknown; tool_result: unknown; ok: boolean }
  | { type: 'error'; error_code: string; error_message_en: string }
  | { type: 'turn_end' }
```

(Add `tool_use_id?` field — paired by T10.)

- [ ] **Step 2: Update chat store to fold tool_result into tool_call**

In `frontend/src/stores/chat.ts`'s `mapSse`, add:

```typescript
  if (event === 'tool_result') {
    // Returned as a separate event by backend (Insight #7 follow-up).
    // Caller writes through to existing tool_call event by tool_use_id.
    return null   // signal: handled by separate callback
  }
```

But returning null discards it. We need a different path — actually mapSse returns ChatEvent | null and caller appends to `events`. Easier: add a new event variant `tool_result_update` that the store handles by patching:

In `chat.ts`, change `for await (const ev …)` block to:

```typescript
      for await (const ev of streamSSE('/lab/chat', {...})) {
        if (ev.event === 'tool_result') {
          const d = ev.data as { tool_use_id: string; result_text: string; ok: boolean }
          set(s => ({
            events: s.events.map(e => {
              if (e.type === 'tool_call' && e.tool_use_id === d.tool_use_id) {
                return { ...e, tool_result: d.result_text, ok: d.ok }
              }
              return e
            }),
          }))
          continue
        }
        const mapped = mapSse(ev.event, ev.data)
        if (mapped === null) continue
        if (mapped.type === 'turn_end') break
        set(s => ({ events: [...s.events, mapped] }))
      }
```

Also update the `tool_call` branch in `mapSse` to extract `tool_use_id`:

```typescript
  if (event === 'tool_call') {
    const d = data as { tool_use_id?: string; tool_name: string; tool_input: unknown; tool_result: unknown; ok?: boolean }
    return {
      type: 'tool_call',
      tool_use_id: d.tool_use_id,
      tool_name: d.tool_name,
      tool_input: d.tool_input,
      tool_result: d.tool_result,
      ok: d.ok ?? true,
    }
  }
```

- [ ] **Step 3: Create `JobProgressCard`**

```tsx
// frontend/src/components/Chat/JobProgressCard.tsx
import { useEffect } from 'react'
import { Pause, Play, X, Check } from 'lucide-react'

import { useJob } from '../../stores/jobs'
import { useProjects } from '../../stores/projects'

interface Props { jobId: string }

export default function JobProgressCard({ jobId }: Props) {
  const { selectedId } = useProjects()
  const { status, turns, bestTurn, endedReason, subscribe, pause, resume, cancel, accept } = useJob()

  useEffect(() => {
    if (selectedId && jobId) void subscribe(selectedId, jobId)
  }, [selectedId, jobId, subscribe])

  return (
    <div className="border-l-2 border-accent-info bg-surface px-3 py-2 font-mono text-xs space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-fg-muted">job</span>
        <span>{jobId}</span>
        <span className="px-1 py-0.5 bg-subtle rounded text-[10px] uppercase">{status}</span>
        <span className="ml-auto flex items-center gap-1">
          {status === 'running' && (
            <button aria-label="pause" onClick={() => void pause()} className="p-1 hover:bg-subtle">
              <Pause size={12} />
            </button>
          )}
          {status === 'paused' && (
            <button aria-label="resume" onClick={() => void resume()} className="p-1 hover:bg-subtle">
              <Play size={12} />
            </button>
          )}
          {(status === 'running' || status === 'paused') && (
            <button aria-label="cancel" onClick={() => void cancel()} className="p-1 hover:bg-subtle">
              <X size={12} />
            </button>
          )}
        </span>
      </div>
      <div className="text-fg-secondary">
        {turns.length === 0 ? 'starting…' : (
          <>turn {turns.length - 1} · best f1 {(bestTurn?.macro_f1 ?? turns[0]?.macro_f1).toFixed(2)} (turn {bestTurn?.turn ?? 0})</>
        )}
      </div>
      {endedReason && (
        <div className="flex items-center gap-2 text-fg-muted">
          ended ({endedReason})
          {bestTurn && (status === 'done') && (
            <button
              onClick={() => void accept(bestTurn.turn)}
              className="ml-auto inline-flex items-center gap-1 px-2 py-1 bg-accent-primary text-canvas rounded uppercase tracking-wide text-[10px]"
              aria-label="accept candidate"
            >
              <Check size={12} /> accept turn {bestTurn.turn}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Render in MessageList**

In `frontend/src/components/Chat/MessageList.tsx`, replace the `tool_call` branch:

```tsx
        if (e.type === 'tool_call') {
          if (e.tool_name === 'mcp__emerge_tools__start_job' && typeof e.tool_result === 'string' && e.tool_result.startsWith('j_')) {
            return <JobProgressCard key={i} jobId={e.tool_result} />
          }
          return <ToolCallCard key={i} event={e} />
        }
```

(Add `import JobProgressCard from './JobProgressCard'` at the top.)

- [ ] **Step 5: Vitest test for JobProgressCard**

```tsx
// frontend/tests/unit/JobProgressCard.test.tsx
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

import JobProgressCard from '../../src/components/Chat/JobProgressCard'
import { useJob } from '../../src/stores/jobs'

beforeEach(() => {
  useJob.setState({
    status: 'running', jobId: 'j_xyz', projectId: 'p_x',
    turns: [
      { type: 'turn', turn: 0, macro_f1: 0.5, per_field: [], saved: true },
      { type: 'turn', turn: 1, macro_f1: 0.7, per_field: [], saved: true },
    ],
    bestTurn: { type: 'turn', turn: 1, macro_f1: 0.7, per_field: [], saved: true },
    endedReason: null, err: null,
    subscribe: vi.fn().mockResolvedValue(undefined),
    pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(), accept: vi.fn(), reset: vi.fn(),
  })
})


describe('JobProgressCard', () => {
  it('renders turn and best-f1 line', () => {
    render(<JobProgressCard jobId="j_xyz" />)
    expect(screen.getByText(/turn 1/i)).toBeInTheDocument()
    expect(screen.getByText(/0\.70/)).toBeInTheDocument()
  })

  it('shows pause button when running, hides resume', () => {
    render(<JobProgressCard jobId="j_xyz" />)
    expect(screen.getByRole('button', { name: /pause/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /resume/i })).not.toBeInTheDocument()
  })

  it('shows accept-candidate button after ended=done', () => {
    useJob.setState(s => ({ ...s, status: 'done', endedReason: 'max_turn' }))
    render(<JobProgressCard jobId="j_xyz" />)
    expect(screen.getByRole('button', { name: /accept candidate/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 6: Run tests + build**

Run: `cd frontend && npm run test`
Expected: 16 passed (13 + 3 new).

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: success.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/chat.ts frontend/src/stores/chat.ts frontend/src/components/Chat/JobProgressCard.tsx frontend/src/components/Chat/MessageList.tsx frontend/tests/unit/JobProgressCard.test.tsx
git commit -m "feat(frontend): JobProgressCard + tool_result→tool_call pairing"
```

---

### Task 18: Slash menu — drop `(M2)` annotation on `/improve`

**Files:**
- Modify: `frontend/src/components/Chat/SlashMenu.tsx`
- Modify: `backend/app/skills/emerge_extractor.md`

- [ ] **Step 1: Update slash menu**

Change `frontend/src/components/Chat/SlashMenu.tsx`:

```typescript
const ITEMS: Item[] = [
  { command: '/new', hint: 'create a new project' },
  { command: '/extract', hint: 'run extraction over project docs' },
  { command: '/eval', hint: 'score against reviewed examples' },
  { command: '/review', hint: 'review predictions' },
  { command: '/improve', hint: 'autoresearch loop (≥5 reviewed)' },
  { command: '/publish', hint: '(M3) freeze version + API key' },
  { command: '/feedback', hint: 'address client feedback' },
]
```

- [ ] **Step 2: Update extractor SKILL.md**

In `backend/app/skills/emerge_extractor.md`, find the `For \`/improve\` and \`/publish\`` section. Replace it with:

```markdown
For `/improve`: a separate skill (emerge-autoresearch) is loaded on this turn.
Follow that skill's directions.

For `/publish`: a separate skill (emerge-publish) will be loaded — not yet
shipped.
```

- [ ] **Step 3: Build / smoke**

```
cd frontend && npm run build 2>&1 | tail -3
```
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Chat/SlashMenu.tsx backend/app/skills/emerge_extractor.md
git commit -m "chore: slash menu + extractor skill — /improve no longer (M2+)"
```

---

## Phase 8 — Spec deferred items

### Task 19: FieldEditor — type-derived controls + `_evidence` round-trip on save

**Files:**
- Modify: `backend/app/schemas/reviewed.py`
- Modify: `backend/tests/unit/test_reviewed_schema.py`
- Modify: `backend/tests/integration/test_lab_reviewed.py` (verify round-trip)
- Modify: `frontend/src/components/ReviewMode/FieldEditor.tsx`
- Modify: `frontend/tests/unit/FieldEditor.test.tsx`
- Modify: `frontend/src/types/review.ts`
- Modify: `frontend/src/stores/review.ts`

Scope:
- Backend: extend `Reviewed` to accept `Optional` `evidence` field aliased to `_evidence` (mirroring `notes`). Persist on save_reviewed.
- Frontend: FieldEditor renders enum chips, number stepper, boolean toggle based on field.type. (Date picker + array<object> nested editor deferred to M4.)

- [ ] **Step 1: Failing backend test**

Append to `backend/tests/unit/test_reviewed_schema.py`:

```python
def test_reviewed_round_trips_evidence() -> None:
    from app.schemas.reviewed import Reviewed
    blob = {
        "entities": [{"x": "y"}],
        "source": "manual",
        "_evidence": [{"x": 2}],
    }
    r = Reviewed(**blob)
    assert r.evidence == [{"x": 2}]
    out = r.model_dump(by_alias=True, exclude_none=True, mode="json")
    assert out["_evidence"] == [{"x": 2}]


def test_reviewed_evidence_optional() -> None:
    from app.schemas.reviewed import Reviewed
    r = Reviewed(entities=[{"x": "y"}])
    assert r.evidence is None
    out = r.model_dump(by_alias=True, exclude_none=True, mode="json")
    assert "_evidence" not in out
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd backend && uv run pytest tests/unit/test_reviewed_schema.py -v`
Expected: AttributeError on `evidence`.

- [ ] **Step 3: Extend `Reviewed`**

Modify `backend/app/schemas/reviewed.py`:

```python
class Reviewed(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entities: list[dict[str, Any]]
    source: ReviewedSource = ReviewedSource.MANUAL
    notes: Optional[dict[str, str]] = Field(default=None, alias="_notes")
    evidence: Optional[list[dict[str, Optional[int]]]] = Field(default=None, alias="_evidence")
```

Update `backend/app/tools/reviewed.py` `save_reviewed` signature to accept optional `evidence`:

```python
async def save_reviewed(
    workspace, project_id, doc_id, *,
    entities, source=ReviewedSource.MANUAL, notes=None, evidence=None,
) -> None:
    payload = Reviewed(entities=entities, source=source, notes=notes, evidence=evidence).model_dump(
        by_alias=True, exclude_none=True, mode="json",
    )
    ...
```

Update `backend/app/api/routes/reviewed.py` to accept and forward `_evidence` in the POST body. (Mirror the existing `_notes` handling — pydantic's `populate_by_name=True` already accepts both `_evidence` and `evidence` keys.)

- [ ] **Step 4: Frontend — failing FieldEditor tests**

Add to `frontend/tests/unit/FieldEditor.test.tsx` (append, do not replace existing tests):

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import FieldEditor from '../../src/components/ReviewMode/FieldEditor'


describe('FieldEditor type-derived controls', () => {
  it('renders enum chips for an enum string field', () => {
    const onChange = vi.fn()
    render(<FieldEditor
      schema={[{ name: 'doc_type', type: 'string', description: 'd', enum: ['invoice', 'others'] }]}
      values={{ doc_type: 'invoice' }}
      onChange={onChange} onSave={() => {}} saving={false}
    />)
    expect(screen.getByRole('button', { name: 'invoice' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'others' })).toBeInTheDocument()
  })

  it('clicking an enum chip emits onChange', () => {
    const onChange = vi.fn()
    render(<FieldEditor
      schema={[{ name: 'doc_type', type: 'string', description: 'd', enum: ['a', 'b'] }]}
      values={{ doc_type: 'a' }}
      onChange={onChange} onSave={() => {}} saving={false}
    />)
    fireEvent.click(screen.getByRole('button', { name: 'b' }))
    expect(onChange).toHaveBeenCalledWith('doc_type', 'b')
  })

  it('renders number stepper for type=number', () => {
    render(<FieldEditor
      schema={[{ name: 'amount', type: 'number', description: 'd' }]}
      values={{ amount: 100 }}
      onChange={vi.fn()} onSave={() => {}} saving={false}
    />)
    expect(screen.getByRole('button', { name: '−' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+' })).toBeInTheDocument()
  })

  it('renders toggle for type=boolean', () => {
    const onChange = vi.fn()
    render(<FieldEditor
      schema={[{ name: 'is_paid', type: 'boolean', description: 'd' }]}
      values={{ is_paid: false }}
      onChange={onChange} onSave={() => {}} saving={false}
    />)
    const toggle = screen.getByRole('switch', { name: /is_paid/i })
    expect(toggle).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(onChange).toHaveBeenCalledWith('is_paid', true)
  })
})
```

- [ ] **Step 5: Run, confirm fail**

Run: `cd frontend && npm run test`
Expected: 4 new failures.

- [ ] **Step 6: Implement FieldEditor type controls**

Replace the `schema.map(...)` body in `frontend/src/components/ReviewMode/FieldEditor.tsx` with type-aware rendering:

```tsx
{schema.map((f) => {
  const current = values[f.name]
  const labelEl = (
    <label htmlFor={`f-${f.name}`} className="font-mono text-xs text-fg-secondary">
      {f.name} <span className="text-fg-muted">({f.type})</span>
    </label>
  )
  let control: React.ReactNode

  if (f.type === 'string' && f.enum && f.enum.length > 0) {
    control = (
      <div className="flex gap-2 flex-wrap">
        {f.enum.map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(f.name, opt)}
            className={
              'px-2 py-1 border text-xs rounded ' +
              (current === opt ? 'bg-accent-primary text-canvas border-transparent' : 'border-subtle hover:bg-subtle')
            }
          >
            {opt}
          </button>
        ))}
      </div>
    )
  } else if (f.type === 'number') {
    const display = current == null ? '' : String(current)
    const num = typeof current === 'number' ? current : Number(current ?? 0)
    control = (
      <div className="flex items-center gap-2">
        <button type="button" aria-label="−" onClick={() => onChange(f.name, num - 1)}
                className="px-2 py-1 border border-subtle font-mono">−</button>
        <input
          id={`f-${f.name}`}
          type="text"
          value={display}
          onChange={(e) => onChange(f.name, e.target.value)}
          className="bg-surface border border-subtle px-2 py-1 font-mono text-sm w-32"
        />
        <button type="button" aria-label="+" onClick={() => onChange(f.name, num + 1)}
                className="px-2 py-1 border border-subtle font-mono">+</button>
      </div>
    )
  } else if (f.type === 'boolean') {
    const checked = !!current
    control = (
      <button
        role="switch"
        aria-label={f.name}
        aria-checked={checked}
        onClick={() => onChange(f.name, !checked)}
        className={
          'inline-flex items-center w-10 h-5 rounded-full transition-colors ' +
          (checked ? 'bg-accent-success' : 'bg-subtle')
        }
      >
        <span className={`inline-block w-4 h-4 rounded-full bg-canvas transform transition-transform ${checked ? 'translate-x-5' : 'translate-x-1'}`} />
      </button>
    )
  } else {
    const display = current == null ? '' : String(current)
    control = (
      <input
        id={`f-${f.name}`}
        type="text"
        value={display}
        onChange={(e) => onChange(f.name, e.target.value)}
        className="bg-surface border border-subtle px-2 py-1 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-accent-primary"
      />
    )
  }

  return (
    <div key={f.name} className="flex flex-col gap-1">
      {labelEl}
      {control}
      {f.description && (
        <span className="text-xs text-fg-muted leading-tight">{f.description}</span>
      )}
    </div>
  )
})}
```

(Make sure the `SchemaField` interface in this file gets a `type: string` enum-tolerant string — it already does.)

- [ ] **Step 7: Run tests + build**

Run: `cd frontend && npm run test`
Expected: 20 passed.

Run: `cd frontend && npm run build 2>&1 | tail -3`
Expected: success.

Run backend tests: `cd backend && uv run pytest -q 2>&1 | tail -3`
Expected: ~187 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/reviewed.py backend/app/tools/reviewed.py backend/app/api/routes/reviewed.py backend/tests/unit/test_reviewed_schema.py frontend/src/components/ReviewMode/FieldEditor.tsx frontend/tests/unit/FieldEditor.test.tsx
git commit -m "feat(review): _evidence round-trip + type-derived FieldEditor controls (enum/number/boolean)"
```

---

### Task 20: Inline `_notes` UI in review mode

**Files:**
- Create: `frontend/src/components/ReviewMode/NotesPopover.tsx`
- Modify: `frontend/src/components/ReviewMode/FieldEditor.tsx`
- Modify: `frontend/src/stores/review.ts`
- Modify: `frontend/src/types/review.ts`
- Create: `frontend/tests/unit/NotesPopover.test.tsx`

User right-clicks (or long-presses) any field's value → small popover with a textarea. Saves into `useReview.notes` keyed by field name. On `save()`, sends the `_notes` map alongside `entities`.

- [ ] **Step 1: Failing test**

```tsx
// frontend/tests/unit/NotesPopover.test.tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import NotesPopover from '../../src/components/ReviewMode/NotesPopover'


describe('NotesPopover', () => {
  it('renders existing note text', () => {
    render(<NotesPopover fieldName="x" initial="hello" onSave={() => {}} onClose={() => {}} />)
    expect(screen.getByDisplayValue('hello')).toBeInTheDocument()
  })

  it('calls onSave with edited text', () => {
    const onSave = vi.fn()
    const onClose = vi.fn()
    render(<NotesPopover fieldName="x" initial="" onSave={onSave} onClose={onClose} />)
    const ta = screen.getByRole('textbox')
    fireEvent.change(ta, { target: { value: 'corrected note' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    expect(onSave).toHaveBeenCalledWith('corrected note')
    expect(onClose).toHaveBeenCalled()
  })

  it('calls onClose without save on cancel', () => {
    const onSave = vi.fn()
    const onClose = vi.fn()
    render(<NotesPopover fieldName="x" initial="abc" onSave={onSave} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onSave).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd frontend && npm run test`
Expected: import errors on NotesPopover.

- [ ] **Step 3: Implement NotesPopover**

```tsx
// frontend/src/components/ReviewMode/NotesPopover.tsx
import { useState } from 'react'

interface Props {
  fieldName: string
  initial: string
  onSave: (text: string) => void
  onClose: () => void
}

export default function NotesPopover({ fieldName, initial, onSave, onClose }: Props) {
  const [text, setText] = useState(initial)
  return (
    <div className="absolute right-0 top-full z-10 mt-1 w-72 bg-surface border border-subtle p-2 shadow-md">
      <div className="text-xs text-fg-muted font-mono mb-1">note · {fieldName}</div>
      <textarea
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        className="w-full bg-canvas border border-subtle px-2 py-1 text-sm resize-none"
      />
      <div className="flex justify-end gap-2 mt-1">
        <button type="button" onClick={onClose} className="px-2 py-1 text-xs hover:bg-subtle">cancel</button>
        <button
          type="button"
          onClick={() => { onSave(text); onClose() }}
          className="px-2 py-1 text-xs bg-accent-primary text-canvas"
        >
          save
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Wire into FieldEditor**

In `FieldEditor.tsx`, accept new props `notes`, `onSetNote`. Right-click on the control wrapper opens NotesPopover positioned absolutely. State `openFor: string | null` tracks which field's popover is open.

```tsx
// inside FieldEditor function — add notes/onSetNote props:
interface Props {
  schema: SchemaField[]
  values: Record<string, unknown>
  notes: Record<string, string>
  onChange: (name: string, value: unknown) => void
  onSetNote: (name: string, note: string) => void
  onSave: () => void
  saving: boolean
}

// Add useState:
const [openFor, setOpenFor] = useState<string | null>(null)

// Wrap each row:
return (
  <div key={f.name} className="relative flex flex-col gap-1"
       onContextMenu={(e) => { e.preventDefault(); setOpenFor(f.name) }}>
    {labelEl}
    {control}
    {notes[f.name] && (
      <span className="text-xs text-accent-info" title="note">💬 {notes[f.name]}</span>
    )}
    {f.description && (
      <span className="text-xs text-fg-muted leading-tight">{f.description}</span>
    )}
    {openFor === f.name && (
      <NotesPopover
        fieldName={f.name}
        initial={notes[f.name] ?? ''}
        onSave={(t) => onSetNote(f.name, t)}
        onClose={() => setOpenFor(null)}
      />
    )}
  </div>
)
```

- [ ] **Step 5: Update review store + ReviewedPayload type**

In `frontend/src/types/review.ts` (already has `_notes: Record<string, string>?` — confirmed existing).

In `frontend/src/stores/review.ts`:

```typescript
interface State {
  ...
  notes: Record<string, string>
  setNote: (name: string, note: string) => void
  ...
}

// initial state:
notes: {},
setNote: (name, note) => set((s) => ({ notes: { ...s.notes, [name]: note } })),

// In open():
const reviewed = await getReviewed(projectId, docId)
if (reviewed) {
  set({
    fields: reviewed.entities[0] ?? {},
    notes: reviewed._notes ?? {},
    loading: false,
  })
  return
}
const pred = await getPrediction(projectId, docId)
set({ fields: pred?.entities[0] ?? {}, notes: {}, loading: false })

// In save():
const payload: ReviewedPayload = {
  entities: [fields],
  source: 'manual',
  ...(Object.keys(notes).length > 0 ? { _notes: notes } : {}),
}
```

In `frontend/src/components/ReviewMode/ReviewMode.tsx`, pass the new props to FieldEditor:

```tsx
const { activeProjectId, activeDocId, fields, notes, setField, setNote, save, close, saving, err } = useReview()
...
<FieldEditor
  schema={schema}
  values={fields}
  notes={notes}
  onChange={setField}
  onSetNote={setNote}
  onSave={save}
  saving={saving}
/>
```

- [ ] **Step 6: Run tests + build**

Run: `cd frontend && npm run test`
Expected: 23 passed (20 + 3 new).

Run: `cd frontend && npm run build 2>&1 | tail -3`
Expected: success.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ReviewMode/NotesPopover.tsx frontend/src/components/ReviewMode/FieldEditor.tsx frontend/src/components/ReviewMode/ReviewMode.tsx frontend/src/stores/review.ts frontend/tests/unit/NotesPopover.test.tsx
git commit -m "feat(review): inline _notes UI (right-click popover) wired to save"
```

---

## Phase 9 — Smoke

### Task 21: End-to-end manual smoke + acceptance check

After all 20 tasks land, validate the milestone end-to-end against a real project. Use the existing `us-invoice` project (3+ reviewed PDFs from M2A dogfood) so autoresearch has signal.

- [ ] **Step 1: Restart servers**

```
pkill -f "uvicorn app.main" 2>/dev/null; sleep 1
mkdir -p /tmp/emerge-logs
cd backend && uv run uvicorn app.main:app --port 8080 --reload > /tmp/emerge-logs/backend.log 2>&1 &
cd frontend && npm run dev -- --port 5172 > /tmp/emerge-logs/frontend.log 2>&1 &
```

- [ ] **Step 2: Wait for ready**

```
until curl -sf http://localhost:8080/healthz >/dev/null 2>&1; do sleep 0.5; done; echo "ok"
```

- [ ] **Step 3: Drive autoresearch via chat**

Open http://localhost:5172/ → click `us-invoice` project. In chat type:

```
/improve
```

Expected:
- Agent loads autoresearch skill (visible because it tells you `/improve needs ≥5 reviewed` if there aren't enough — otherwise it confirms job started).
- Agent calls `mcp__emerge_tools__start_job`. The frontend shows a JobProgressCard with `status=running` and per-turn macro_f1 updating.
- Pause / cancel buttons functional.

- [ ] **Step 4: Verify on disk**

```
ls /Users/qinqiang02/colab/codespace/ai/emerge/backend/workspace/p_4w6rzeuz9dfi/jobs/
ls /Users/qinqiang02/colab/codespace/ai/emerge/backend/workspace/p_4w6rzeuz9dfi/versions/_candidate/
```

Expected: at least one `j_*.jsonl` file and a `j_*/turn_*.json` file.

- [ ] **Step 5: Accept best candidate**

When the job ends with reason=max_turn or early_stop, click "accept turn N" on the card.

```
diff <(jq -S . /Users/qinqiang02/colab/codespace/ai/emerge/backend/workspace/p_4w6rzeuz9dfi/schema.json) \
     <(jq -S . /Users/qinqiang02/colab/codespace/ai/emerge/backend/workspace/p_4w6rzeuz9dfi/versions/_candidate/<job_id>/turn_<n>.json | jq -S .schema)
```
Expected: schema.json now matches the candidate's `schema` (descriptions only differ from the original).

- [ ] **Step 6: Run /eval to confirm improvement**

In chat:

```
/eval
```

Expected: `macro_f1` printed in agent response is ≥ baseline before /improve.

- [ ] **Step 7: Acceptance command sweep**

```
cd backend && uv run pytest -q
# expect ~190 passed
```

```
cd frontend && npm run test
# expect 23 passed
```

```
cd frontend && npm run e2e
# expect 2 passed (no e2e additions in M2C; T19/T20 changes don't break the existing draft → reviewed flow)
```

If all steps pass, M2C is verified end-to-end. No commit.

---

## Acceptance check

```
cd backend && uv run pytest -q
# expect ~190 passed (142 baseline + ~48 added)

cd frontend && npm run test
# expect 23 passed (13 baseline + 3 JobProgressCard + 4 FieldEditor + 3 NotesPopover)

cd frontend && npm run e2e
# expect 2 passed
```

Manual smoke: `/improve` end-to-end + accept candidate + `/eval` shows improved macro_f1.

---

## Spec coverage check

| Spec section | Covered by |
|---|---|
| §3.2 `versions/_candidate/{job_id}/turn_{k}.json` filesystem layout | T1, T7 |
| §3.2 `jobs/{job_id}.jsonl` filesystem layout | T1, T3 |
| §4.2 emerge-autoresearch discipline (max_turn, early_stop, no auto-promote, _notes hints, candidate-only writes) | T7, T11, T12, T15 |
| §5.6 long-running job tools (start_job/get_job/pause/resume/cancel) | T11 |
| §5.6 tail_job — split into HTTP-only SSE route | T14 |
| §6.1 `/improve` slash command (≥5 reviewed gate) | T12, T13 |
| §6.3 risk gate: "Accept autoresearch candidate → overwrite schema.json" | T15 (POST accept-candidate is explicit user action; no auto-promote) |
| §10 testing layers (tool unit + skill loader + route integration + frontend) | T2-T15, T17, T19, T20 |
| §12 hard rules (no SDK recursion, candidate-only writes, no auto-promote, no counterexample) | T5 (structural-change guard), T7 (loop only writes _candidate), T11 (start_job uses provider, not SDK) |
| Insight #7 (tool_use_id pairing) | T10 |
| ROADMAP fold-in: type-derived field controls | T19 |
| ROADMAP fold-in: `_evidence` round-trip on review save | T19 |
| ROADMAP fold-in: inline `_notes` UI | T20 |

---

## Self-Review notes

- The autoresearch loop deliberately skips counterexample triplet handling — that scaffolding is M3 territory, and `_notes` from reviewed are sufficient as the user-priority hint channel for M2C. The reviewed set IS the regression set (we score on it every turn). Spec §4.2 is satisfied.
- Crash recovery: if the backend dies mid-job, the in-memory JobRunner forgets the job. The JSONL log on disk survives but no `ended` event will be appended. Spec §9.2 mentions a startup scan for stale `_job_locks/`; M3 will need it. M2C's smoke is single-process, single-user.
- Per-job proposer model override is unimplemented; v1 uses the project's `extract_model`. Adding a `params.proposer_model` is a one-liner change in T11 + T7 if needed.
- The FieldEditor's `array<object>` handling is unchanged — it falls through to the default text input, same as M2A. Nested-table editing is M4.
- `_evidence` round-trip persists on save (T19) but the click-to-page UX (Insight pointer "use _evidence to jump to the page on click") is M4 polish — needs a deliberate UX call between text-search highlight vs. raw page jump.
- The chat store's tool_result→tool_call patching (T17) assumes the backend always emits `tool_use_id` on the original `tool_call`. T10's test verifies this. If the SDK ever changes the field, both tests will catch it.
- `start_job` returns the raw `j_xxx` string in `tool_result.text`. The frontend's MessageList detects this with a `startsWith('j_')` guard. If we ever return a richer payload here, update the matcher accordingly.
- The SSE route uses a 200ms poll-tail rather than inotify. For lab use this is fine. Production publish API is unaffected (M3).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-09-m2c-autoresearch.md`. Default execution mode (per user's stated preference): `superpowers:subagent-driven-development` — fresh subagent per task with two-stage review between tasks.

## After M2C ships

Open `docs/superpowers/plans/ROADMAP.md` and update the M2C row to ✅ shipped with the commit range. Then move to M3 (publish + prod fast-path + API key) — the next plan to write. Use `superpowers:writing-plans` to produce `docs/superpowers/plans/YYYY-MM-DD-m3-publish.md` from the M3 entry under "What each milestone delivers".
