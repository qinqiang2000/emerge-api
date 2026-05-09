import json
from pathlib import Path

from app.schemas.reviewed import ReviewedSource
from app.tools.projects import create_project
from app.tools.reviewed import get_reviewed, list_reviewed, save_reviewed


async def test_save_reviewed_writes_file(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await save_reviewed(
        workspace,
        pid,
        "d_test",
        entities=[{"invoice_no": "INV-1", "total_amount": 99.5}],
        source=ReviewedSource.MANUAL,
    )
    target = workspace / pid / "reviewed" / "d_test.json"
    assert target.exists()
    blob = json.loads(target.read_text())
    assert blob["entities"] == [{"invoice_no": "INV-1", "total_amount": 99.5}]
    assert blob["source"] == "manual"
    assert "_notes" not in blob   # default None excluded


async def test_save_reviewed_with_notes(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await save_reviewed(
        workspace,
        pid,
        "d_test",
        entities=[{"buyer_name": "ACME"}],
        source=ReviewedSource.MANUAL,
        notes={"buyer_name": "double-checked"},
    )
    blob = json.loads((workspace / pid / "reviewed" / "d_test.json").read_text())
    assert blob["_notes"] == {"buyer_name": "double-checked"}


async def test_save_reviewed_overwrites_existing(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await save_reviewed(
        workspace, pid, "d_test", entities=[{"a": 1}], source=ReviewedSource.MANUAL
    )
    await save_reviewed(
        workspace, pid, "d_test", entities=[{"a": 2}], source=ReviewedSource.MANUAL
    )
    blob = json.loads((workspace / pid / "reviewed" / "d_test.json").read_text())
    assert blob["entities"] == [{"a": 2}]


async def test_save_reviewed_creates_reviewed_dir(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    rd = workspace / pid / "reviewed"
    assert not rd.exists()  # not auto-created on project init
    await save_reviewed(
        workspace, pid, "d_test", entities=[{}], source=ReviewedSource.MANUAL
    )
    assert rd.is_dir()


async def test_list_reviewed_empty(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    assert await list_reviewed(workspace, pid) == []


async def test_list_reviewed_returns_doc_ids(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await save_reviewed(
        workspace, pid, "d_aaa", entities=[{}], source=ReviewedSource.MANUAL
    )
    await save_reviewed(
        workspace, pid, "d_bbb", entities=[{}], source=ReviewedSource.MANUAL
    )
    items = await list_reviewed(workspace, pid)
    assert {it["doc_id"] for it in items} == {"d_aaa", "d_bbb"}


async def test_get_reviewed_returns_payload(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await save_reviewed(
        workspace,
        pid,
        "d_test",
        entities=[{"invoice_no": "INV-1"}],
        source=ReviewedSource.MANUAL,
        notes={"invoice_no": "verified"},
    )
    got = await get_reviewed(workspace, pid, "d_test")
    assert got is not None
    assert got["entities"] == [{"invoice_no": "INV-1"}]
    assert got["_notes"] == {"invoice_no": "verified"}


async def test_get_reviewed_returns_none_for_missing(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    assert await get_reviewed(workspace, pid, "d_unreviewed") is None
