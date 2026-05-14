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
    # Label is auto-derived from prompt label + model provider_model_id
    assert ex.label == "Baseline × gemini-2.5-flash"


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
        workspace, pid, prompt_id="pr_v2", model_id="m_other",
    )
    ex = await read_experiment(workspace, pid, eid)
    assert ex.label == "v2 × claude-haiku-4-5-20251001"
    assert ex.prompt_id == "pr_v2"
    assert ex.model_id == "m_other"


async def test_create_experiment_is_upsert_by_axes_pair(workspace: Path) -> None:
    """Calling create_experiment twice with the same (prompt, model) returns
    the same experiment_id — by-axes upsert, no duplicate experiments."""
    from app.tools.experiment import create_experiment
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid1 = await create_experiment(workspace, pid)
    eid2 = await create_experiment(workspace, pid)
    assert eid1 == eid2

    # Same upsert behavior for explicit axes
    atomic_write_json(prompt_path(workspace, pid, "pr_v2"), {
        "prompt_id": "pr_v2", "label": "v2",
        "schema": [{"name": "x", "type": "string", "description": "x", "required": False}],
        "global_notes": "", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })
    eid3 = await create_experiment(workspace, pid, prompt_id="pr_v2")
    eid4 = await create_experiment(workspace, pid, prompt_id="pr_v2")
    assert eid3 == eid4
    # Different axes pair → different experiment
    assert eid3 != eid1


async def test_create_experiment_upsert_returns_archived_match(workspace: Path) -> None:
    """If an archived experiment matches the (prompt, model), it's still
    returned — caller can revive it by running eval again."""
    from app.tools.experiment import archive_experiment, create_experiment, read_experiment
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    await archive_experiment(workspace, pid, eid)
    # Upsert returns the archived one (no new mint)
    eid2 = await create_experiment(workspace, pid)
    assert eid2 == eid
    ex = await read_experiment(workspace, pid, eid)
    assert ex.status == "archived"  # status unchanged by upsert


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
    # Two experiments must have DIFFERENT axes pairs (upsert dedups same-axes)
    atomic_write_json(prompt_path(workspace, pid, "pr_v2"), {
        "prompt_id": "pr_v2", "label": "v2",
        "schema": [{"name": "x", "type": "string", "description": "x", "required": False}],
        "global_notes": "", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })
    e1 = await create_experiment(workspace, pid)  # (baseline, default)
    e2 = await create_experiment(workspace, pid, prompt_id="pr_v2")  # (v2, default)
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


async def test_extract_with_experiment_writes_to_predictions_dir(
    workspace: Path, stub_provider,
):
    from app.tools.experiment import create_experiment, extract_with_experiment
    from app.workspace.paths import doc_meta_path, doc_path, docs_dir, experiment_prediction_path
    from tests.conftest import make_provider_result
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    filename = "invoice.png"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, filename).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 61)
    meta_p = doc_meta_path(workspace, pid, filename)
    meta_p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(meta_p, {"filename": filename, "ext": "png"})

    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"supplier": "ACME"}]},
    )

    eid = await create_experiment(workspace, pid)
    payload = await extract_with_experiment(
        workspace, pid, eid, filename, provider=stub_provider,
    )
    assert payload.get("entities") == [{"supplier": "ACME"}]
    on_disk = json.loads(
        experiment_prediction_path(workspace, pid, eid, filename).read_text(),
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
    filename = "doc.png"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, filename).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 61)
    meta_p = doc_meta_path(workspace, pid, filename)
    meta_p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(meta_p, {"filename": filename, "ext": "png"})
    stub_provider.extract.return_value = make_provider_result({"entities": [{}]})

    eid = await create_experiment(workspace, pid, prompt_id="pr_variant")
    await extract_with_experiment(workspace, pid, eid, filename, provider=stub_provider)

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
    filename = "doc.png"
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, filename).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 61)
    meta_p = doc_meta_path(workspace, pid, filename)
    meta_p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(meta_p, {"filename": filename, "ext": "png"})

    stub_provider.extract.return_value = make_provider_result({"entities": [{}]})
    eid = await create_experiment(workspace, pid)
    await extract_with_experiment(workspace, pid, eid, filename, provider=stub_provider)

    call_kwargs = stub_provider.extract.call_args.kwargs
    assert call_kwargs["params"] == {"temperature": 0.42}
    assert call_kwargs["model_id"] == "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# T5 helpers
# ---------------------------------------------------------------------------

def _seed_doc(workspace: Path, pid: str, filename: str) -> None:
    """Seed a minimal .png stub + sidecar so read_doc / _doc_to_block accept the doc.

    Post-d_xxx: layout is `docs/<filename>` + `docs/.meta/<filename>.json`.
    """
    from app.workspace.paths import doc_meta_path, doc_path, docs_dir
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    # Minimal 8x8 transparent PNG (~70 bytes)
    doc_path(workspace, pid, filename).write_bytes(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x08\x00\x00\x00\x08'
        b'\x08\x06\x00\x00\x00\xc4\x0f\xbe\x8b\x00\x00\x00\x0cIDATx\x9cc\xf8'
        b'\xcf\xc0\x00\x00\x00\x03\x00\x01]Z9o\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    meta_p = doc_meta_path(workspace, pid, filename)
    meta_p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(meta_p, {
        "filename": filename, "original_name": filename, "ext": "png",
        "sha256": "stub", "page_count": 1, "uploaded_at": _now(),
    })


# ---------------------------------------------------------------------------
# T5 tests
# ---------------------------------------------------------------------------

async def test_run_experiment_eval_writes_eval_meta_and_per_doc(
    workspace: Path, stub_provider,
):
    from app.tools.experiment import create_experiment, read_experiment, run_experiment_eval
    from app.workspace.paths import reviewed_dir, reviewed_path
    from tests.conftest import make_provider_result
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    for did in ("d_aaaaaaaaaaaa", "d_bbbbbbbbbbbb"):
        _seed_doc(workspace, pid, did)
        atomic_write_json(reviewed_path(workspace, pid, did), {
            "entities": [{"supplier": "ACME"}], "source": "manual",
        })
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"supplier": "ACME"}]},
    )
    eid = await create_experiment(workspace, pid)
    ev = await run_experiment_eval(workspace, pid, eid, provider=stub_provider)

    assert ev["score"] >= 0.0
    assert set(ev["per_doc"].keys()) == {"d_aaaaaaaaaaaa", "d_bbbbbbbbbbbb"}
    assert ev["coverage"] == 2
    ex = await read_experiment(workspace, pid, eid)
    assert ex.status == "ran"
    assert ex.eval is not None
    assert ex.eval.score == ev["score"]


async def test_run_experiment_eval_with_no_reviewed_raises(
    workspace: Path, stub_provider,
):
    from app.tools.experiment import create_experiment, run_experiment_eval
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    with pytest.raises(ValueError, match="no reviewed docs"):
        await run_experiment_eval(workspace, pid, eid, provider=stub_provider)


async def test_run_experiment_eval_reuses_existing_extract_when_present(
    workspace: Path, stub_provider,
):
    from app.tools.experiment import (
        create_experiment,
        extract_with_experiment,
        run_experiment_eval,
    )
    from app.workspace.paths import reviewed_dir, reviewed_path
    from tests.conftest import make_provider_result
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    did = "d_aaaaaaaaaaaa"
    _seed_doc(workspace, pid, did)
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(reviewed_path(workspace, pid, did), {
        "entities": [{"supplier": "ACME"}], "source": "manual",
    })
    eid = await create_experiment(workspace, pid)
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"supplier": "ACME"}]},
    )
    # priming extract — 1 provider call
    await extract_with_experiment(workspace, pid, eid, did, provider=stub_provider)
    primed_calls = stub_provider.extract.call_count
    # second pass: the extract file is present, so run_experiment_eval reuses it
    await run_experiment_eval(workspace, pid, eid, provider=stub_provider)
    assert stub_provider.extract.call_count == primed_calls


async def test_run_experiment_eval_blocks_promoted(workspace: Path, stub_provider):
    """Re-running eval on a promoted experiment would clobber audit trail."""
    from app.tools.experiment import (
        ExperimentInUseError,
        create_experiment,
        run_experiment_eval,
    )
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    # simulate T6's promote semantics by direct write
    meta_path = experiment_meta_path(workspace, pid, eid)
    meta = json.loads(meta_path.read_text())
    meta["status"] = "promoted"
    meta["promoted_at"] = _now()
    atomic_write_json(meta_path, meta)

    with pytest.raises(ExperimentInUseError, match="promoted"):
        await run_experiment_eval(workspace, pid, eid, provider=stub_provider)


# ---------------------------------------------------------------------------
# T6 tests
# ---------------------------------------------------------------------------

async def test_promote_experiment_switches_active_and_seeds_predictions(
    workspace: Path, stub_provider,
):
    from app.tools.experiment import (
        create_experiment,
        extract_with_experiment,
        promote_experiment,
        read_experiment,
    )
    from app.workspace.paths import predictions_draft_dir
    from tests.conftest import make_provider_result
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # seed a variant prompt that the experiment will reference
    atomic_write_json(prompt_path(workspace, pid, "pr_v2"), {
        "prompt_id": "pr_v2", "label": "v2",
        "schema": [{"name": "x", "type": "string", "description": "x", "required": False}],
        "global_notes": "", "derived_from": "pr_baseline",
        "created_at": _now(), "updated_at": _now(),
    })
    did = "d_aaaaaaaaaaaa"
    _seed_doc(workspace, pid, did)
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"x": "1"}]},
    )

    eid = await create_experiment(workspace, pid, prompt_id="pr_v2")
    await extract_with_experiment(workspace, pid, eid, did, provider=stub_provider)
    await promote_experiment(workspace, pid, eid)

    project = json.loads(project_json_path(workspace, pid).read_text())
    assert project["active_prompt_id"] == "pr_v2"
    # active_model_id stays the same (experiment defaulted to active model)

    draft_dir = predictions_draft_dir(workspace, pid)
    draft_file = draft_dir / f"{did}.json"
    assert draft_file.exists()
    assert json.loads(draft_file.read_text())["entities"][0]["x"] == "1"

    ex = await read_experiment(workspace, pid, eid)
    assert ex.status == "promoted"
    assert ex.promoted_at is not None


async def test_promote_experiment_replaces_existing_predictions_draft(
    workspace: Path, stub_provider,
):
    """Spec §3.5 step 2: rm -rf predictions/_draft/* then re-fill from
    experiment.extracts. Pre-existing draft files must be cleared."""
    from app.tools.experiment import (
        create_experiment,
        extract_with_experiment,
        promote_experiment,
    )
    from app.workspace.paths import predictions_draft_dir
    from tests.conftest import make_provider_result
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # pre-existing draft from a previous active prompt
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    stale = predictions_draft_dir(workspace, pid) / "d_old0000000.json"
    stale.write_text(json.dumps({"entities": [{"supplier": "stale"}]}))

    did = "d_aaaaaaaaaaaa"
    _seed_doc(workspace, pid, did)
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"supplier": "fresh"}]},
    )
    eid = await create_experiment(workspace, pid)
    await extract_with_experiment(workspace, pid, eid, did, provider=stub_provider)
    await promote_experiment(workspace, pid, eid)
    # stale file gone
    assert not stale.exists()
    # fresh file present
    assert (predictions_draft_dir(workspace, pid) / f"{did}.json").exists()


async def test_delete_experiment_blocks_promoted(workspace: Path, stub_provider):
    from app.tools.experiment import (
        ExperimentInUseError,
        create_experiment,
        delete_experiment,
        extract_with_experiment,
        promote_experiment,
    )
    from tests.conftest import make_provider_result
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    did = "d_aaaaaaaaaaaa"
    _seed_doc(workspace, pid, did)
    stub_provider.extract.return_value = make_provider_result({"entities": [{}]})
    eid = await create_experiment(workspace, pid)
    await extract_with_experiment(workspace, pid, eid, did, provider=stub_provider)
    await promote_experiment(workspace, pid, eid)
    with pytest.raises(ExperimentInUseError):
        await delete_experiment(workspace, pid, eid)


async def test_delete_experiment_physical_removal(workspace: Path):
    from app.tools.experiment import (
        ExperimentNotFoundError,
        create_experiment,
        delete_experiment,
        read_experiment,
    )
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    eid = await create_experiment(workspace, pid)
    await delete_experiment(workspace, pid, eid)
    with pytest.raises(ExperimentNotFoundError):
        await read_experiment(workspace, pid, eid)
    # directory gone
    assert not experiment_meta_path(workspace, pid, eid).parent.exists()


async def test_promote_experiment_flips_active_model(
    workspace: Path, stub_provider,
):
    """promote_experiment must update active_model_id, not just active_prompt_id.
    Without this test, the model-axis flip is silently uncovered."""
    from app.tools.experiment import (
        create_experiment,
        extract_with_experiment,
        promote_experiment,
    )
    from tests.conftest import make_provider_result
    pid = "p_test12345678"
    _seed_axes(workspace, pid)
    # seed a second model the experiment will reference
    atomic_write_json(model_path(workspace, pid, "m_other"), {
        "model_id": "m_other", "label": "Other",
        "provider": "anthropic",
        "provider_model_id": "claude-haiku-4-5-20251001",
        "params": {}, "created_at": _now(),
    })
    did = "d_aaaaaaaaaaaa"
    _seed_doc(workspace, pid, did)
    stub_provider.extract.return_value = make_provider_result({"entities": [{}]})

    eid = await create_experiment(workspace, pid, model_id="m_other")
    await extract_with_experiment(workspace, pid, eid, did, provider=stub_provider)

    # Sanity: before promote, project's active_model_id is still the seeded default
    project_before = json.loads(project_json_path(workspace, pid).read_text())
    assert project_before["active_model_id"] == "m_default"

    await promote_experiment(workspace, pid, eid)

    project_after = json.loads(project_json_path(workspace, pid).read_text())
    assert project_after["active_model_id"] == "m_other"
