# backend/tests/unit/test_tool_save_reviewed_consumed.py
"""Phase B `save_reviewed` + `_notes_consumed` round-trip.

Verifies:
    * Reviewed pydantic model parses old files (no `_notes_consumed` key) as
      None (backward compat — zero migration).
    * save_reviewed round-trips an explicit `_notes_consumed` map.
    * save_reviewed defensive merge: omitting `notes_consumed` preserves any
      existing on-disk map (the load-bearing safety net for agent value
      corrections that don't round-trip consumption metadata).
    * save_reviewed passing explicit `{}` clears the map.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.reviewed import NoteConsumption, Reviewed, ReviewedSource
from app.tools.reviewed import get_reviewed, save_reviewed
from app.workspace.paths import reviewed_path


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def test_reviewed_model_parses_old_file_without_notes_consumed() -> None:
    """Files written before Phase B simply lack `_notes_consumed`. They must
    still parse cleanly with `notes_consumed = None`."""
    blob = {
        "entities": [{"buyer_name": "ACME"}],
        "source": "manual",
        "_notes": {"buyer_name": "should be ACME Sdn Bhd"},
    }
    r = Reviewed(**blob)
    assert r.notes == {"buyer_name": "should be ACME Sdn Bhd"}
    assert r.notes_consumed is None
    out = r.model_dump(by_alias=True, exclude_none=True, mode="json")
    assert "_notes_consumed" not in out


def test_reviewed_model_round_trips_notes_consumed() -> None:
    blob = {
        "entities": [{"buyer_name": "ACME"}],
        "source": "manual",
        "_notes": {"buyer_name": "official: ACME Sdn Bhd"},
        "_notes_consumed": {
            "buyer_name": {
                "consumed_at": "2026-05-16T10:32:00Z",
                "consumed_via": "accept_candidate",
                "source_ref": "j_3a8c9.turn_4",
                "active_prompt_id": "pr_baseline",
            },
        },
    }
    r = Reviewed(**blob)
    assert r.notes_consumed is not None
    assert "buyer_name" in r.notes_consumed
    assert r.notes_consumed["buyer_name"].consumed_via == "accept_candidate"
    out = r.model_dump(by_alias=True, exclude_none=True, mode="json")
    assert out["_notes_consumed"]["buyer_name"]["source_ref"] == "j_3a8c9.turn_4"


async def test_save_reviewed_round_trips_explicit_notes_consumed(workspace: Path) -> None:
    await save_reviewed(
        workspace,
        "p_a",
        "inv-001.pdf",
        entities=[{"buyer_name": "ACME"}],
        notes={"buyer_name": "should be ACME Sdn Bhd"},
        notes_consumed={
            "buyer_name": {
                "consumed_at": "2026-05-16T10:32:00Z",
                "consumed_via": "accept_candidate",
                "source_ref": "j_x.turn_1",
                "active_prompt_id": "pr_baseline",
            },
        },
    )
    blob = json.loads(reviewed_path(workspace, "p_a", "inv-001.pdf").read_text())
    assert blob["_notes_consumed"]["buyer_name"]["consumed_via"] == "accept_candidate"


async def test_save_reviewed_omitted_notes_consumed_preserves_existing(workspace: Path) -> None:
    """Defensive merge: agent does a value correction without passing
    `notes_consumed`. The on-disk consumption record must NOT be cleared."""
    # Seed an on-disk reviewed file WITH a consumed entry.
    await save_reviewed(
        workspace,
        "p_a",
        "inv-001.pdf",
        entities=[{"buyer_name": "OLD"}],
        notes={"buyer_name": "should be ACME"},
        notes_consumed={
            "buyer_name": {
                "consumed_at": "2026-05-16T10:00:00Z",
                "consumed_via": "accept_candidate",
                "source_ref": "j_x.turn_3",
                "active_prompt_id": "pr_baseline",
            },
        },
    )
    # Agent value-correction call that OMITS notes_consumed.
    await save_reviewed(
        workspace,
        "p_a",
        "inv-001.pdf",
        entities=[{"buyer_name": "ACME"}],
        notes={"buyer_name": "should be ACME"},
        # notes_consumed omitted
    )
    blob = json.loads(reviewed_path(workspace, "p_a", "inv-001.pdf").read_text())
    # Value was updated.
    assert blob["entities"][0]["buyer_name"] == "ACME"
    # Audit trail survives.
    assert blob["_notes_consumed"]["buyer_name"]["source_ref"] == "j_x.turn_3"


async def test_save_reviewed_explicit_empty_dict_clears(workspace: Path) -> None:
    """Explicit `{}` is the only way for a caller to genuinely clear the
    consumption map. (None / omitted both preserve.)"""
    await save_reviewed(
        workspace,
        "p_a",
        "inv-001.pdf",
        entities=[{}],
        notes_consumed={
            "buyer_name": {
                "consumed_at": "2026-05-16T10:00:00Z",
                "consumed_via": "accept_candidate",
                "source_ref": "j_x.turn_3",
                "active_prompt_id": "pr_baseline",
            },
        },
    )
    await save_reviewed(
        workspace,
        "p_a",
        "inv-001.pdf",
        entities=[{}],
        notes_consumed={},
    )
    blob = json.loads(reviewed_path(workspace, "p_a", "inv-001.pdf").read_text())
    assert "_notes_consumed" not in blob


async def test_save_reviewed_none_notes_consumed_preserves_existing(workspace: Path) -> None:
    """Explicit None is treated like omitted — preserves on-disk."""
    await save_reviewed(
        workspace,
        "p_a",
        "inv-001.pdf",
        entities=[{}],
        notes_consumed={
            "buyer_name": {
                "consumed_at": "2026-05-16T10:00:00Z",
                "consumed_via": "accept_candidate",
                "source_ref": "j_x.turn_3",
                "active_prompt_id": "pr_baseline",
            },
        },
    )
    await save_reviewed(
        workspace,
        "p_a",
        "inv-001.pdf",
        entities=[{}],
        notes_consumed=None,
    )
    blob = json.loads(reviewed_path(workspace, "p_a", "inv-001.pdf").read_text())
    assert blob["_notes_consumed"]["buyer_name"]["source_ref"] == "j_x.turn_3"


async def test_get_reviewed_returns_notes_consumed(workspace: Path) -> None:
    await save_reviewed(
        workspace,
        "p_a",
        "inv-001.pdf",
        entities=[{}],
        notes_consumed={
            "buyer_name": {
                "consumed_at": "2026-05-16T10:00:00Z",
                "consumed_via": "accept_candidate",
                "source_ref": "j_x.turn_3",
                "active_prompt_id": "pr_baseline",
            },
        },
    )
    payload = await get_reviewed(workspace, "p_a", "inv-001.pdf")
    assert payload is not None
    assert payload["_notes_consumed"]["buyer_name"]["consumed_via"] == "accept_candidate"


# --- Phase B: _corrections passthrough + corrections_since_tune counter ---


def test_reviewed_model_round_trips_corrections() -> None:
    blob = {
        "entities": [{"buyer_name": "ACME"}],
        "source": "manual",
        "_corrections": {
            "buyer_name": {"before": "ACM", "after": "ACME"},
            "total": {"before": 100, "after": 120},
        },
    }
    r = Reviewed(**blob)
    assert r.corrections is not None
    assert r.corrections["buyer_name"]["after"] == "ACME"
    out = r.model_dump(by_alias=True, exclude_none=True, mode="json")
    assert out["_corrections"]["total"]["before"] == 100
    # exclude_none drops the key entirely when there are no corrections.
    r2 = Reviewed(entities=[{}])
    assert "_corrections" not in r2.model_dump(by_alias=True, exclude_none=True, mode="json")


async def test_save_reviewed_round_trips_corrections(workspace: Path) -> None:
    await save_reviewed(
        workspace,
        "p_a",
        "inv-001.pdf",
        entities=[{"buyer_name": "ACME"}],
        corrections={"buyer_name": {"before": "ACM", "after": "ACME"}},
    )
    blob = json.loads(reviewed_path(workspace, "p_a", "inv-001.pdf").read_text())
    assert blob["_corrections"]["buyer_name"]["after"] == "ACME"


async def test_save_reviewed_corrections_bump_counter(workspace: Path) -> None:
    """A non-empty `corrections` map increments project.json.corrections_since_tune
    by the number of corrected fields, inside the same save lock."""
    from app.tools.projects import create_project
    from app.workspace.paths import project_json_path

    pid = (await create_project(workspace, name="t"))["slug"]
    # First save: 2 corrected fields → counter 0 → 2.
    await save_reviewed(
        workspace,
        pid,
        "inv-001.pdf",
        entities=[{"buyer_name": "ACME", "total": 120}],
        corrections={
            "buyer_name": {"before": "ACM", "after": "ACME"},
            "total": {"before": 100, "after": 120},
        },
    )
    blob = json.loads(project_json_path(workspace, pid).read_text())
    assert blob["corrections_since_tune"] == 2
    # Second save on another doc: 1 corrected field → 2 → 3.
    await save_reviewed(
        workspace,
        pid,
        "inv-002.pdf",
        entities=[{"buyer_name": "Globex"}],
        corrections={"buyer_name": {"before": "Glob", "after": "Globex"}},
    )
    blob = json.loads(project_json_path(workspace, pid).read_text())
    assert blob["corrections_since_tune"] == 3


async def test_save_reviewed_no_corrections_does_not_move_counter(workspace: Path) -> None:
    """Omitting / empty corrections leaves the counter untouched."""
    from app.tools.projects import create_project
    from app.workspace.paths import project_json_path

    pid = (await create_project(workspace, name="t"))["slug"]
    pj = project_json_path(workspace, pid)
    seed = json.loads(pj.read_text())
    seed["corrections_since_tune"] = 4
    pj.write_text(json.dumps(seed))
    await save_reviewed(
        workspace,
        pid,
        "inv-001.pdf",
        entities=[{"buyer_name": "ACME"}],
        # no corrections kwarg
    )
    blob = json.loads(pj.read_text())
    assert blob["corrections_since_tune"] == 4


async def test_save_reviewed_revert_nets_to_zero(workspace: Path) -> None:
    """Correcting a field on a doc, then re-saving that SAME doc with the field
    reverted (empty corrections), retires the doc's contribution — the counter
    returns to 0 rather than double-counting the round-trip."""
    from app.tools.projects import create_project
    from app.workspace.paths import project_json_path

    pid = (await create_project(workspace, name="t"))["slug"]
    pj = project_json_path(workspace, pid)
    # Save 1: the human filled an empty field → 1 correction.
    await save_reviewed(
        workspace,
        pid,
        "inv-001.pdf",
        entities=[{"deliveryOrderNumber": "X"}],
        corrections={"deliveryOrderNumber": {"before": "", "after": "X"}},
    )
    blob = json.loads(pj.read_text())
    assert blob["corrections_since_tune"] == 1
    assert blob["corrections_by_field"] == {"deliveryOrderNumber": 1}
    # Save 2: realised it was wrong, cleared the value → the frontend ships an
    # empty diff. The doc's prior contribution is retired.
    await save_reviewed(
        workspace,
        pid,
        "inv-001.pdf",
        entities=[{"deliveryOrderNumber": ""}],
        # net diff is empty → no corrections kwarg
    )
    blob = json.loads(pj.read_text())
    assert blob["corrections_since_tune"] == 0
    assert blob["corrections_by_field"] == {}


async def test_save_reviewed_resave_same_field_is_idempotent(workspace: Path) -> None:
    """Re-saving the same doc with the same single correction doesn't inflate
    the counter (delta reconcile, not blind increment)."""
    from app.tools.projects import create_project
    from app.workspace.paths import project_json_path

    pid = (await create_project(workspace, name="t"))["slug"]
    pj = project_json_path(workspace, pid)
    for _ in range(3):
        await save_reviewed(
            workspace,
            pid,
            "inv-001.pdf",
            entities=[{"currency": "USD"}],
            corrections={"currency": {"before": "MYR", "after": "USD"}},
        )
    blob = json.loads(pj.read_text())
    assert blob["corrections_since_tune"] == 1
    assert blob["corrections_by_field"] == {"currency": 1}
