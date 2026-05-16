# backend/tests/unit/test_autoresearch_consumed_filter.py
"""Phase B `_load_reviewed_with_notes` filters out fields whose `_notes` entry
has already been consumed (i.e. has a sibling `_notes_consumed[field]` entry).

Old reviewed files (pre-Phase-B, no `_notes_consumed` key) behave identically
to before — every `_notes[field]` surfaces."""
from __future__ import annotations

from pathlib import Path

from app.jobs.autoresearch import _load_reviewed_with_notes
from app.tools.reviewed import save_reviewed


async def test_load_reviewed_excludes_consumed_notes(tmp_path: Path) -> None:
    # File A: `buyer_name` consumed, `seller_name` not yet.
    await save_reviewed(
        tmp_path, "p_a", "inv-001.pdf",
        entities=[{"buyer_name": "ACME", "seller_name": "X"}],
        notes={"buyer_name": "consumed hint", "seller_name": "active hint"},
        notes_consumed={
            "buyer_name": {
                "consumed_at": "2026-05-16T10:00:00Z",
                "consumed_via": "accept_candidate",
                "source_ref": "j_x.turn_3",
                "active_prompt_id": "pr_baseline",
            },
        },
    )
    # File B: no consumed notes — both notes should surface.
    await save_reviewed(
        tmp_path, "p_a", "inv-002.pdf",
        entities=[{}],
        notes={"buyer_name": "active everywhere"},
    )

    reviewed, notes = _load_reviewed_with_notes(tmp_path, "p_a")
    assert "inv-001.pdf" in reviewed
    assert "inv-002.pdf" in reviewed
    # File A: only seller_name surfaces (buyer_name was consumed).
    assert notes["inv-001.pdf"] == {"seller_name": "active hint"}
    # File B: untouched.
    assert notes["inv-002.pdf"] == {"buyer_name": "active everywhere"}


async def test_load_reviewed_old_file_without_consumed_key_returns_all(tmp_path: Path) -> None:
    """Backward-compat: reviewed files written before Phase B have no
    `_notes_consumed` key. They must still surface all `_notes` entries."""
    # Write directly via the pre-Phase-B shape (no notes_consumed argument).
    await save_reviewed(
        tmp_path, "p_a", "inv-001.pdf",
        entities=[{}],
        notes={"buyer_name": "should be ACME", "seller_name": "x"},
    )
    _, notes = _load_reviewed_with_notes(tmp_path, "p_a")
    assert notes["inv-001.pdf"] == {"buyer_name": "should be ACME", "seller_name": "x"}


async def test_load_reviewed_empty_notes_omitted_from_map(tmp_path: Path) -> None:
    """When every note on a file is consumed, the file shouldn't appear in
    the notes dict at all (preserves the pre-Phase-B contract of `notes`
    keys being only files with non-empty notes)."""
    await save_reviewed(
        tmp_path, "p_a", "inv-001.pdf",
        entities=[{}],
        notes={"buyer_name": "consumed"},
        notes_consumed={
            "buyer_name": {
                "consumed_at": "2026-05-16T10:00:00Z",
                "consumed_via": "accept_candidate",
                "source_ref": "j_x.turn_1",
                "active_prompt_id": "pr_baseline",
            },
        },
    )
    _, notes = _load_reviewed_with_notes(tmp_path, "p_a")
    assert "inv-001.pdf" not in notes
