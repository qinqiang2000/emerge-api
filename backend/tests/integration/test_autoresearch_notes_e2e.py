import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.jobs import autoresearch as ar
from app.jobs import get_runner, reset_runner_for_tests
from app.provider.base import Provider, ProviderResult
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.projects import create_project
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir, reviewed_dir


@pytest.fixture(autouse=True)
def _reset_runner():
    reset_runner_for_tests()
    yield
    reset_runner_for_tests()


@pytest.mark.asyncio
async def test_notes_from_disk_reach_proposer_prompt(workspace: Path, monkeypatch) -> None:
    pid = (await create_project(workspace, name="t-notes"))["slug"]
    await write_schema(
        workspace, pid,
        [SchemaField(name="buyer_name", type=FieldType.STRING, description="legal name")],
        reason="seed", allow_structural=True,
    )
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    for i in range(3):
        did = f"d_{i:012d}"
        rev = {"entities": [{"buyer_name": "ACME"}], "source": "manual"}
        if i == 0:
            rev["_notes"] = {"buyer_name": "official is ACME Sdn Bhd, never abbreviate"}
        atomic_write_json(reviewed_dir(workspace, pid) / f"{did}.json", rev)
        atomic_write_json(
            predictions_draft_dir(workspace, pid) / f"{did}.json",
            {"entities": [{"buyer_name": "ACME"}]},
        )

    captured: list[dict] = []

    async def _record_extract(**kwargs):
        captured.append(kwargs)
        return ProviderResult(
            raw_json={
                "fields": [
                    {
                        "name": "buyer_name",
                        "type": "string",
                        "description": "legal name (be exact, never abbreviate)",
                    }
                ],
                "rationale": "tightened wording per user notes",
            },
            model_id="stub",
            input_tokens=0,
            output_tokens=0,
        )

    fake_provider = AsyncMock(spec=Provider)
    fake_provider.extract.side_effect = _record_extract

    async def _fake_score(**kwargs):
        from app.schemas.score import FieldScore, ScoreResult
        return ScoreResult(
            n_docs=3,
            n_reviewed=3,
            macro_f1=0.9,
            per_field=[FieldScore(
                field="buyer_name", tp=3, fp=0, fn=0,
                support=3, precision=1.0, recall=1.0, f1=1.0,
            )],
            errors=[],
            ts="t",
            schema_field_count=1,
        ), {f"d_{i:012d}": [{"buyer_name": "ACME"}] for i in range(3)}

    monkeypatch.setattr(ar, "score_with_schema", _fake_score)

    runner = get_runner(workspace=workspace, provider=fake_provider, model_id="stub")
    job_id = await runner.start(
        skill="autoresearch",
        project_id=pid,
        params={"max_turn": 1, "early_stop_no_improvement": 1},
    )
    for _ in range(40):
        info = await runner.get(job_id)
        if info.status in ("done", "cancelled", "error"):
            break
        await asyncio.sleep(0.05)
    info = await runner.get(job_id)
    assert info.status == "done", f"job did not finish cleanly: status={info.status} err={info.error_code!r}"

    assert captured, "provider.extract was never called - proposer skipped?"
    call = captured[0]
    user_blocks = call.get("user_content") or []
    text_blocks = [b.text for b in user_blocks if hasattr(b, "text")]
    full = "\n".join(text_blocks)
    assert "official is ACME Sdn Bhd" in full, (
        "user notes did not reach the proposer prompt; full text was:\n" + full[:1500]
    )
