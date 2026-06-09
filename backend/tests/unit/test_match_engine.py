"""Pairing engine: full-pairing + greedy 1:1 (app/match/engine.py)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.match.engine import run_engine
from app.schemas.match import KeyMapping, MatchPromptVariant, Tol
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    docs_dir,
    docs_meta_dir,
    prediction_draft_path,
)


async def _seed(workspace, name: str, docs: dict[str, dict]) -> str:
    """Create an extract project with `docs = {filename: field_record}`. Writes
    the doc file + a meta sidecar (so list_docs returns it without sniffing
    bytes) + a draft prediction `{entities: [record]}`."""
    slug = (await create_project(workspace, name=name))["slug"]
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    docs_meta_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    for fn, rec in docs.items():
        (docs_dir(workspace, slug) / fn).write_bytes(b"stub")
        atomic_write_json(
            docs_meta_dir(workspace, slug) / f"{fn}.json",
            {"filename": fn, "sha256": "x", "page_count": 1, "ext": "jpg"},
        )
        pd = prediction_draft_path(workspace, slug, fn)
        pd.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(pd, {"entities": [rec]})
    return slug


def _mpv(mappings: dict[str, list[KeyMapping]]) -> MatchPromptVariant:
    now = datetime.now(timezone.utc).isoformat()
    return MatchPromptVariant(
        prompt_id="mpr_test", label="t", mappings=mappings, rules="",
        created_at=now, updated_at=now, version=1, content_hash="x",
    )


_AMOUNT_ORDER = lambda src: [
    KeyMapping(anchor="amount", source="amount", tol=Tol(type="number", abs=0.01)),
    KeyMapping(anchor="order_no", source="ref_no", tol=Tol(type="exact")),
]


async def test_clean_one_to_one_complete(workspace):
    anchor = await _seed(workspace, "inv", {"inv1.jpg": {"amount": "100.00", "order_no": "A1"}})
    src = await _seed(workspace, "pay", {"pay1.jpg": {"amount": "100.00", "ref_no": "A1"}})
    mpv = _mpv({src: _AMOUNT_ORDER(src)})

    res = await run_engine(
        workspace, run_id="mr_1", anchor_project=anchor, source_projects=[src],
        match_prompt=mpv, provider=None,
    )
    assert len(res.cards) == 1
    card = res.cards[0]
    assert card.overall == "complete"
    assert card.pairs[0].status == "match" and card.pairs[0].doc == "pay1.jpg"
    assert res.orphans[src] == []


async def test_greedy_exclusivity(workspace):
    # two anchors both match the single source doc → only one gets it (1:1)
    anchor = await _seed(workspace, "inv", {
        "inv1.jpg": {"amount": "50.00", "order_no": "X"},
        "inv2.jpg": {"amount": "50.00", "order_no": "X"},
    })
    src = await _seed(workspace, "pay", {"pay1.jpg": {"amount": "50.00", "ref_no": "X"}})
    mpv = _mpv({src: _AMOUNT_ORDER(src)})

    res = await run_engine(
        workspace, run_id="mr_2", anchor_project=anchor, source_projects=[src],
        match_prompt=mpv, provider=None,
    )
    by_anchor = {c.anchor_doc: c for c in res.cards}
    matched = [a for a, c in by_anchor.items() if c.pairs[0].status == "match"]
    missing = [a for a, c in by_anchor.items() if c.pairs[0].status == "missing"]
    assert len(matched) == 1 and len(missing) == 1   # exactly one claim
    assert res.orphans[src] == []                     # the source doc was claimed


async def test_orphan_source_doc(workspace):
    anchor = await _seed(workspace, "inv", {"inv1.jpg": {"amount": "10.00", "order_no": "A"}})
    src = await _seed(workspace, "pay", {
        "pay1.jpg": {"amount": "10.00", "ref_no": "A"},
        "pay_orphan.jpg": {"amount": "999.00", "ref_no": "Z"},
    })
    mpv = _mpv({src: _AMOUNT_ORDER(src)})

    res = await run_engine(
        workspace, run_id="mr_3", anchor_project=anchor, source_projects=[src],
        match_prompt=mpv, provider=None,
    )
    assert res.orphans[src] == ["pay_orphan.jpg"]


async def test_unmatched_anchor(workspace):
    anchor = await _seed(workspace, "inv", {"inv1.jpg": {"amount": "10.00", "order_no": "A"}})
    src = await _seed(workspace, "pay", {"pay1.jpg": {"amount": "999.00", "ref_no": "Z"}})
    mpv = _mpv({src: _AMOUNT_ORDER(src)})

    res = await run_engine(
        workspace, run_id="mr_4", anchor_project=anchor, source_projects=[src],
        match_prompt=mpv, provider=None,
    )
    card = res.cards[0]
    assert card.overall == "unmatched" and card.pairs[0].status == "missing"
    assert res.orphans[src] == ["pay1.jpg"]
