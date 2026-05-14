"""Prediction-fetch tests after the filename-native cutover."""
from pathlib import Path

from app.tools.predictions import get_prediction
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir


async def test_get_prediction_returns_draft(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pred = {"entities": [{"invoice_no": "X-1"}], "_evidence": [{"invoice_no": 1}]}
    pdir = predictions_draft_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pdir / "inv-001.pdf.json", pred)
    got = await get_prediction(workspace, pid, "inv-001.pdf")
    assert got == pred


async def test_get_prediction_returns_none_for_missing(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    assert await get_prediction(workspace, pid, "missing.pdf") is None
