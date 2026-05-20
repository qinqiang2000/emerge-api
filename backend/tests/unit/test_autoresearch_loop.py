import asyncio
from dataclasses import dataclass
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


def _fake_score(field_accuracy_macro: float) -> ScoreResult:
    # M12.x — autoresearch loop now optimizes accuracy. Test fixtures expose
    # the input as `field_accuracy_macro`; the FieldScore carries the matching
    # `accuracy`. F1 family is left None (matches what the new scorer emits).
    return ScoreResult(
        n_docs=1, n_reviewed=1,
        field_accuracy_macro=field_accuracy_macro,
        macro_f1=None,
        per_field=[FieldScore(
            field="invoice_no",
            accuracy=field_accuracy_macro,
            correct=1, total=1, n_absent_both=0, not_applicable=False,
        )],
        errors=[], ts="t", schema_field_count=1,
    )


@dataclass
class _Plan:
    score_seq: list[float]
    propose_seq: list[list[SchemaField]]


def _patched_score_and_propose(monkeypatch: pytest.MonkeyPatch, plan: _Plan) -> dict[str, int]:
    counters = {"score": 0, "propose": 0}

    async def _fake_score_with_schema(**kwargs) -> tuple[ScoreResult, dict]:
        i = counters["score"]
        counters["score"] += 1
        return _fake_score(plan.score_seq[i]), {}

    async def _fake_propose_schema(**kwargs) -> tuple[list[SchemaField], str, list[str], list[str]]:
        i = counters["propose"]
        counters["propose"] += 1
        # Phase B: propose_schema now returns (proposed, rationale,
        # validated_notes_hit, filtered_notes_hit). The loop tests don't care
        # about notes_hit semantics so we return empty lists for both.
        return plan.propose_seq[i], "rat", [], []

    monkeypatch.setattr(ar, "score_with_schema", _fake_score_with_schema)
    monkeypatch.setattr(ar, "propose_schema", _fake_propose_schema)
    return counters


async def test_loop_improves_then_max_turn(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = [_f()]
    plan = _Plan(
        score_seq=[0.5, 0.7, 0.9],
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
    assert types.count("turn") == 3
    assert types[-1] == "ended"
    cand_dir = workspace / "p_aaaaaaaaaaaa" / "versions" / "_candidate" / "j_xxxxxxxxxxxx"
    assert (cand_dir / "turn_0.json").exists()
    assert (cand_dir / "turn_1.json").exists()
    assert (cand_dir / "turn_2.json").exists()


async def test_loop_no_improvement_does_not_save(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = [_f()]
    plan = _Plan(
        score_seq=[0.8, 0.5, 0.7],
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
    cancel.set()

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
        return [_f()], "ok", [], []

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
    types = [e.type for e in events]
    assert "proposer_failed" in types
    assert info.best_macro_f1 == 0.7
