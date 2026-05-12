import json
from pathlib import Path

import pytest

from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    experiment_meta_path,
    model_path,
    project_json_path,
    prompt_path,
)


def _now() -> str:
    return "2026-05-13T00:00:00+00:00"


def _seed_axes(workspace: Path, pid: str) -> None:
    """Seed a project with one active prompt + one active model."""
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "project_id": pid,
        "name": "Test",
        "created_at": _now(),
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
    })
    atomic_write_json(prompt_path(workspace, pid, "pr_baseline"), {
        "prompt_id": "pr_baseline",
        "label": "Baseline",
        "schema": [
            {"name": "supplier", "type": "string", "description": "Supplier name", "required": False},
        ],
        "global_notes": "",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, pid, "m_default"), {
        "model_id": "m_default",
        "label": "Default",
        "provider": "google",
        "provider_model_id": "gemini-2.5-flash",
        "params": {"temperature": 0.0},
        "created_at": _now(),
    })


async def test_create_experiment_defaults_to_active(workspace: Path) -> None:
    from app.tools.experiment import create_experiment, read_experiment
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    assert eid.startswith("ex_")
    ex = await read_experiment(workspace, pid, eid)
    assert ex.prompt_id == "pr_baseline"
    assert ex.model_id == "m_default"
    assert ex.status == "draft"
    assert ex.eval is None
    assert ex.label.startswith("trial_")


async def test_create_experiment_explicit_axes(workspace: Path) -> None:
    from app.tools.experiment import create_experiment, read_experiment
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # seed a second prompt and a second model
    atomic_write_json(prompt_path(workspace, pid, "pr_v2"), {
        "prompt_id": "pr_v2", "label": "v2",
        "schema": [{"name": "x", "type": "string", "description": "x", "required": False}],
        "global_notes": "", "derived_from": "pr_baseline",
        "created_at": _now(), "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, pid, "m_other"), {
        "model_id": "m_other", "label": "Other",
        "provider": "anthropic",
        "provider_model_id": "claude-haiku-4-5-20251001",
        "params": {}, "created_at": _now(),
    })
    eid = await create_experiment(
        workspace, pid, label="custom", prompt_id="pr_v2", model_id="m_other",
    )
    ex = await read_experiment(workspace, pid, eid)
    assert ex.label == "custom"
    assert ex.prompt_id == "pr_v2"
    assert ex.model_id == "m_other"


async def test_create_experiment_missing_prompt_raises(workspace: Path) -> None:
    from app.tools.experiment import create_experiment
    from app.tools.prompt import PromptNotFoundError
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await create_experiment(workspace, pid, prompt_id="pr_missing")


async def test_create_experiment_missing_model_raises(workspace: Path) -> None:
    from app.tools.experiment import create_experiment
    from app.tools.model import ModelNotFoundError
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    with pytest.raises(ModelNotFoundError):
        await create_experiment(workspace, pid, model_id="m_missing")


async def test_list_experiments_excludes_archived_by_default(workspace: Path) -> None:
    from app.tools.experiment import (
        archive_experiment,
        create_experiment,
        list_experiments,
    )
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    e1 = await create_experiment(workspace, pid, label="keep")
    e2 = await create_experiment(workspace, pid, label="hide")
    await archive_experiment(workspace, pid, e2)
    rows_default = await list_experiments(workspace, pid)
    assert [r["experiment_id"] for r in rows_default] == [e1]
    rows_all = await list_experiments(workspace, pid, include_archived=True)
    assert {r["experiment_id"] for r in rows_all} == {e1, e2}


async def test_list_experiments_returns_score_when_available(workspace: Path) -> None:
    from app.tools.experiment import create_experiment, list_experiments
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    meta = json.loads(experiment_meta_path(workspace, pid, eid).read_text())
    meta["status"] = "ran"
    meta["eval"] = {
        "ran_at": _now(), "score": 0.91,
        "per_field": {"supplier": 1.0}, "per_doc": {},
        "run_id": "r_1", "coverage": 0,
    }
    atomic_write_json(experiment_meta_path(workspace, pid, eid), meta)
    rows = await list_experiments(workspace, pid)
    assert rows[0]["status"] == "ran"
    assert rows[0]["score"] == 0.91


async def test_read_experiment_missing_raises(workspace: Path) -> None:
    from app.tools.experiment import ExperimentNotFoundError, read_experiment
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    with pytest.raises(ExperimentNotFoundError):
        await read_experiment(workspace, pid, "ex_missing00000")


async def test_archive_experiment_idempotent_on_archived(workspace: Path) -> None:
    """Archiving an already-archived experiment is a silent no-op."""
    from app.tools.experiment import (
        archive_experiment,
        create_experiment,
        read_experiment,
    )
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    await archive_experiment(workspace, pid, eid)
    # second call should not raise
    await archive_experiment(workspace, pid, eid)
    ex = await read_experiment(workspace, pid, eid)
    assert ex.status == "archived"


async def test_archive_experiment_blocks_promoted(workspace: Path) -> None:
    """Cannot archive a promoted experiment — audit trail must survive."""
    from app.tools.experiment import (
        ExperimentInUseError,
        archive_experiment,
        create_experiment,
    )
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    # promote_experiment isn't implemented yet (T6), so simulate by direct write
    meta_path = experiment_meta_path(workspace, pid, eid)
    meta = json.loads(meta_path.read_text())
    meta["status"] = "promoted"
    meta["promoted_at"] = _now()
    atomic_write_json(meta_path, meta)

    with pytest.raises(ExperimentInUseError):
        await archive_experiment(workspace, pid, eid)


async def test_extract_with_experiment_writes_to_extracts_dir(
    workspace: Path, stub_provider,
):
    from app.tools.experiment import create_experiment, extract_with_experiment
    from app.workspace.paths import doc_meta_path, doc_path, docs_dir, experiment_extract_path
    from tests.conftest import make_provider_result
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    did = "d_doc000000000"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, did, "png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 61)
    atomic_write_json(doc_meta_path(workspace, pid, did), {"doc_id": did, "ext": "png", "filename": "invoice.png"})

    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"supplier": "ACME"}]},
    )

    eid = await create_experiment(workspace, pid)
    payload = await extract_with_experiment(
        workspace, pid, eid, did, provider=stub_provider,
    )
    assert payload.get("entities") == [{"supplier": "ACME"}]
    on_disk = json.loads(
        experiment_extract_path(workspace, pid, eid, did).read_text(),
    )
    assert on_disk == payload


async def test_extract_with_experiment_uses_experiment_prompt_not_active(
    workspace: Path, stub_provider,
):
    """Even if active prompt has field 'supplier', if the experiment references
    a variant with field 'marker', the extract instructions must mention 'marker'
    (not 'supplier')."""
    from app.tools.experiment import create_experiment, extract_with_experiment
    from app.workspace.paths import doc_meta_path, doc_path, docs_dir
    from tests.conftest import make_provider_result
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # seed a variant prompt with a different field name
    atomic_write_json(prompt_path(workspace, pid, "pr_variant"), {
        "prompt_id": "pr_variant", "label": "variant",
        "schema": [
            {"name": "marker", "type": "string", "description": "unique field", "required": False},
        ],
        "global_notes": "", "derived_from": "pr_baseline",
        "created_at": _now(), "updated_at": _now(),
    })
    did = "d_doc000000000"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, did, "png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 61)
    atomic_write_json(doc_meta_path(workspace, pid, did), {"doc_id": did, "ext": "png", "filename": "doc.png"})
    stub_provider.extract.return_value = make_provider_result({"entities": [{}]})

    eid = await create_experiment(workspace, pid, prompt_id="pr_variant")
    await extract_with_experiment(workspace, pid, eid, did, provider=stub_provider)

    # Inspect what was passed to provider.extract — user_content is a list of
    # ContentBlock; the first block is TextBlock with the field instructions.
    call_kwargs = stub_provider.extract.call_args.kwargs
    user_content = call_kwargs["user_content"]
    # find the TextBlock(s) and concatenate their text
    text_payloads = " ".join(
        getattr(b, "text", "") for b in user_content
    )
    assert "marker" in text_payloads
    assert "supplier" not in text_payloads


async def test_extract_with_experiment_passes_model_params(
    workspace: Path, stub_provider,
):
    """The experiment's model.params (e.g. temperature override) must flow
    through to provider.extract via the new `params` argument."""
    from app.tools.experiment import create_experiment, extract_with_experiment
    from app.workspace.paths import doc_meta_path, doc_path, docs_dir, model_path
    from tests.conftest import make_provider_result
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # override model.params to a distinctive value
    atomic_write_json(model_path(workspace, pid, "m_default"), {
        "model_id": "m_default", "label": "Default",
        "provider": "google", "provider_model_id": "gemini-2.5-flash",
        "params": {"temperature": 0.42}, "created_at": _now(),
    })
    did = "d_doc000000000"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, did, "png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 61)
    atomic_write_json(doc_meta_path(workspace, pid, did), {"doc_id": did, "ext": "png", "filename": "doc.png"})

    stub_provider.extract.return_value = make_provider_result({"entities": [{}]})
    eid = await create_experiment(workspace, pid)
    await extract_with_experiment(workspace, pid, eid, did, provider=stub_provider)

    call_kwargs = stub_provider.extract.call_args.kwargs
    assert call_kwargs["params"] == {"temperature": 0.42}
    assert call_kwargs["model_id"] == "gemini-2.5-flash"
