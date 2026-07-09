"""Reviewed-store tests after the filename-native cutover.

`save_reviewed` / `get_reviewed` / `list_reviewed` are now keyed by the doc's
on-disk filename (no `d_xxx`). Reviewed JSON sits at
`reviewed/<filename>.json`, with the file stem == the doc handle.
"""
import json
from pathlib import Path

from app.schemas.reviewed import ReviewedSource
from app.tools.projects import create_project
from app.tools.reviewed import get_reviewed, list_reviewed, save_reviewed


async def test_save_reviewed_writes_file(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await save_reviewed(
        workspace,
        pid,
        "invoice-001.pdf",
        entities=[{"invoice_no": "INV-1", "total_amount": 99.5}],
        source=ReviewedSource.MANUAL,
    )
    target = workspace / pid / "reviewed" / "invoice-001.pdf.json"
    assert target.exists()
    blob = json.loads(target.read_text())
    assert blob["entities"] == [{"invoice_no": "INV-1", "total_amount": 99.5}]
    assert blob["source"] == "manual"
    assert "_notes" not in blob   # default None excluded


async def test_save_reviewed_with_notes(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await save_reviewed(
        workspace,
        pid,
        "invoice-001.pdf",
        entities=[{"buyer_name": "ACME"}],
        source=ReviewedSource.MANUAL,
        notes={"buyer_name": "double-checked"},
    )
    blob = json.loads((workspace / pid / "reviewed" / "invoice-001.pdf.json").read_text())
    assert blob["_notes"] == {"buyer_name": "double-checked"}


async def test_save_reviewed_overwrites_existing(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await save_reviewed(
        workspace, pid, "x.pdf", entities=[{"a": 1}], source=ReviewedSource.MANUAL
    )
    await save_reviewed(
        workspace, pid, "x.pdf", entities=[{"a": 2}], source=ReviewedSource.MANUAL
    )
    blob = json.loads((workspace / pid / "reviewed" / "x.pdf.json").read_text())
    assert blob["entities"] == [{"a": 2}]


async def test_save_reviewed_creates_reviewed_dir(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    rd = workspace / pid / "reviewed"
    assert not rd.exists()  # not auto-created on project init
    await save_reviewed(
        workspace, pid, "x.pdf", entities=[{}], source=ReviewedSource.MANUAL
    )
    assert rd.is_dir()


async def test_list_reviewed_empty(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    assert await list_reviewed(workspace, pid) == []


async def test_list_reviewed_returns_filenames(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await save_reviewed(
        workspace, pid, "alpha.pdf", entities=[{}], source=ReviewedSource.MANUAL
    )
    await save_reviewed(
        workspace, pid, "beta.png", entities=[{}], source=ReviewedSource.MANUAL
    )
    items = await list_reviewed(workspace, pid)
    assert {it["filename"] for it in items} == {"alpha.pdf", "beta.png"}
    # No legacy doc_id leakage.
    for it in items:
        assert "doc_id" not in it


async def test_get_reviewed_returns_payload(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await save_reviewed(
        workspace,
        pid,
        "rcpt.pdf",
        entities=[{"invoice_no": "INV-1"}],
        source=ReviewedSource.MANUAL,
        notes={"invoice_no": "verified"},
    )
    got = await get_reviewed(workspace, pid, "rcpt.pdf")
    assert got is not None
    assert got["entities"] == [{"invoice_no": "INV-1"}]
    assert got["_notes"] == {"invoice_no": "verified"}


async def test_get_reviewed_returns_none_for_missing(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    assert await get_reviewed(workspace, pid, "nope.pdf") is None


# ── `_run` anchor: which prompt's schema was this ground truth edited against? ──
#
# A reviewer can adopt a prediction from an experiment whose prompt differs from
# the project's active one. `entities` is written verbatim, so those extra fields
# land on disk; without this anchor the review UI re-renders the blob through the
# ACTIVE schema and they become invisible (saved but unshowable).


async def test_save_reviewed_stamps_active_prompt_by_default(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await save_reviewed(workspace, pid, "a.pdf", entities=[{"k": "v"}])

    blob = json.loads((workspace / pid / "reviewed" / "a.pdf.json").read_text())
    from app.tools.prompt import read_active_prompt

    active = await read_active_prompt(workspace, pid)
    assert blob["_run"]["kind"] == "reviewed"
    assert blob["_run"]["prompt_id"] == active.prompt_id
    # A human, not a model, produced these values.
    assert blob["_run"].get("extract_model") is None
    assert blob["_run"].get("model_id") is None


async def test_save_reviewed_honors_explicit_prompt_id(workspace: Path) -> None:
    """Adopting an experiment's prediction anchors the review to THAT prompt."""
    from app.tools.prompt import create_prompt, read_active_prompt

    pid = (await create_project(workspace, name="x"))["slug"]
    active = await read_active_prompt(workspace, pid)
    other_id = await create_prompt(workspace, pid, label="lodging")
    assert other_id != active.prompt_id

    await save_reviewed(
        workspace, pid, "b.pdf",
        entities=[{"checkInDate": "2025-06-18"}],
        prompt_id=other_id,
    )
    blob = json.loads((workspace / pid / "reviewed" / "b.pdf.json").read_text())
    assert blob["_run"]["prompt_id"] == other_id
    assert blob["_run"]["prompt_label"] == "lodging"


async def test_save_reviewed_survives_unknown_prompt_id(workspace: Path) -> None:
    """A bad/deleted prompt id must never block a save of human work."""
    pid = (await create_project(workspace, name="x"))["slug"]
    await save_reviewed(
        workspace, pid, "c.pdf", entities=[{"k": "v"}], prompt_id="pr_does_not_exist",
    )
    blob = json.loads((workspace / pid / "reviewed" / "c.pdf.json").read_text())
    assert blob["entities"] == [{"k": "v"}]
    assert "_run" not in blob  # best-effort stamp omitted, save still succeeded
