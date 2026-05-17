"""Tests for `pre_label` — the Pro Labeler batch draft tool."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import upload_doc
from app.tools.pre_label import (
    LabelerNotConfiguredError,
    pre_label,
    set_labeler_model,
)
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    pending_reviewed_path,
    project_json_path,
    reviewed_path,
)
from tests.conftest import make_provider_result


_FIXTURE = Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf"


def _basic_schema() -> list[SchemaField]:
    return [
        SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number"),
        SchemaField(name="total_amount", type=FieldType.NUMBER, description="Total amount"),
    ]


async def _seed(workspace: Path, n_docs: int = 1) -> tuple[str, list[str]]:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf = _FIXTURE.read_bytes()
    fns: list[str] = []
    for i in range(n_docs):
        meta = await upload_doc(workspace, pid, pdf, f"inv-{i}.pdf")
        fns.append(meta["filename"])
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)
    return pid, fns


async def test_pre_label_writes_pending_with_metadata(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    slug, [fn] = await _seed(workspace, n_docs=1)
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "INV-1", "total_amount": 99.5}],
         "_evidence": [{"invoice_no": 1, "total_amount": 1}]},
    )
    out = await pre_label(
        workspace, slug,
        filenames=[fn],
        labeler_model="gemini-pro-latest",
        provider=stub_provider,
    )
    assert out["processed"] == [fn]
    assert out["skipped"] == []
    assert out["errors"] == []
    assert out["labeler_model"] == "gemini-pro-latest"
    p = pending_reviewed_path(workspace, slug, fn)
    assert p.exists()
    blob = json.loads(p.read_text())
    assert blob["entities"][0]["invoice_no"] == "INV-1"
    assert blob["labeler_model"] == "gemini-pro-latest"
    assert "created_at" in blob
    # pending is NOT reviewed — must not have source/notes/notes_consumed
    assert "source" not in blob


async def test_pre_label_skips_already_reviewed(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    slug, [fn] = await _seed(workspace, n_docs=1)
    await save_reviewed(
        workspace, slug, fn,
        entities=[{"invoice_no": "INV-0"}],
        source=ReviewedSource.MANUAL,
    )
    out = await pre_label(
        workspace, slug, filenames=[fn],
        labeler_model="gemini-pro-latest", provider=stub_provider,
    )
    assert out["processed"] == []
    assert out["skipped"] == [{"filename": fn, "reason": "already_reviewed"}]
    # Provider must NOT have been called.
    assert stub_provider.extract.await_count == 0


async def test_pre_label_overwrites_existing_pending(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    slug, [fn] = await _seed(workspace, n_docs=1)
    # First run with model A
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "OLD", "total_amount": 1.0}],
         "_evidence": [{"invoice_no": 1, "total_amount": 1}]},
    )
    await pre_label(
        workspace, slug, filenames=[fn],
        labeler_model="model-a", provider=stub_provider,
    )
    # Second run with model B — should overwrite
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "NEW", "total_amount": 2.0}],
         "_evidence": [{"invoice_no": 1, "total_amount": 1}]},
    )
    await pre_label(
        workspace, slug, filenames=[fn],
        labeler_model="model-b", provider=stub_provider,
    )
    blob = json.loads(pending_reviewed_path(workspace, slug, fn).read_text())
    assert blob["entities"][0]["invoice_no"] == "NEW"
    assert blob["labeler_model"] == "model-b"


async def test_pre_label_resolves_labeler_priority_arg_over_project(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    slug, [fn] = await _seed(workspace, n_docs=1)
    # Persist a project labeler_model that should be overridden by the arg.
    pj = project_json_path(workspace, slug)
    blob = json.loads(pj.read_text())
    blob["labeler_model"] = "project-default"
    atomic_write_json(pj, blob)

    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "x", "total_amount": 1.0}],
         "_evidence": [{"invoice_no": 1, "total_amount": 1}]},
    )
    out = await pre_label(
        workspace, slug, filenames=[fn],
        labeler_model="override-model", provider=stub_provider,
    )
    assert out["labeler_model"] == "override-model"


async def test_pre_label_resolves_project_over_env(
    workspace: Path, stub_provider: AsyncMock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug, [fn] = await _seed(workspace, n_docs=1)
    monkeypatch.setenv("EMERGE_DEFAULT_LABELER_MODEL", "env-default")
    pj = project_json_path(workspace, slug)
    blob = json.loads(pj.read_text())
    blob["labeler_model"] = "project-default"
    atomic_write_json(pj, blob)

    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "x", "total_amount": 1.0}],
         "_evidence": [{"invoice_no": 1, "total_amount": 1}]},
    )
    out = await pre_label(
        workspace, slug, filenames=[fn], provider=stub_provider,
    )
    assert out["labeler_model"] == "project-default"


async def test_pre_label_falls_back_to_env_default(
    workspace: Path, stub_provider: AsyncMock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug, [fn] = await _seed(workspace, n_docs=1)
    monkeypatch.setenv("EMERGE_DEFAULT_LABELER_MODEL", "env-default")
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "x", "total_amount": 1.0}],
         "_evidence": [{"invoice_no": 1, "total_amount": 1}]},
    )
    out = await pre_label(
        workspace, slug, filenames=[fn], provider=stub_provider,
    )
    assert out["labeler_model"] == "env-default"


async def test_pre_label_raises_when_unconfigured(
    workspace: Path, stub_provider: AsyncMock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EMERGE_DEFAULT_LABELER_MODEL", raising=False)
    slug, [fn] = await _seed(workspace, n_docs=1)
    with pytest.raises(LabelerNotConfiguredError):
        await pre_label(
            workspace, slug, filenames=[fn], provider=stub_provider,
        )


async def test_pre_label_defaults_filenames_to_all_unreviewed(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    slug, fns = await _seed(workspace, n_docs=3)
    # Mark one as already reviewed — pre_label must skip it.
    await save_reviewed(
        workspace, slug, fns[0],
        entities=[{}], source=ReviewedSource.MANUAL,
    )
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "x", "total_amount": 1.0}],
         "_evidence": [{"invoice_no": 1, "total_amount": 1}]},
    )
    out = await pre_label(
        workspace, slug,
        labeler_model="model-x", provider=stub_provider,
    )
    assert set(out["processed"]) == {fns[1], fns[2]}
    assert out["skipped"] == [{"filename": fns[0], "reason": "already_reviewed"}]


async def test_set_labeler_model_persists_to_project_json(workspace: Path) -> None:
    slug, _ = await _seed(workspace, n_docs=0)
    await set_labeler_model(workspace, slug, "claude-opus-4-1")
    blob = json.loads(project_json_path(workspace, slug).read_text())
    assert blob["labeler_model"] == "claude-opus-4-1"


async def test_pre_label_collects_per_doc_errors(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    slug, fns = await _seed(workspace, n_docs=2)
    # First doc succeeds, second raises.
    stub_provider.extract.side_effect = [
        make_provider_result(
            {"entities": [{"invoice_no": "OK", "total_amount": 1.0}],
             "_evidence": [{"invoice_no": 1, "total_amount": 1}]},
        ),
        RuntimeError("provider 503"),
    ]
    out = await pre_label(
        workspace, slug, filenames=fns,
        labeler_model="m", provider=stub_provider,
    )
    assert out["processed"] == [fns[0]]
    assert out["errors"] == [{
        "filename": fns[1],
        "error_code": "pre_label_failed",
        "error_message_en": "provider 503",
    }]
