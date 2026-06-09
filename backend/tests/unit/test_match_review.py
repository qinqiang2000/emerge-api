"""Match review + scoring (app/tools/match_review.py)."""
from __future__ import annotations

import pytest

import app.tools.match_run as match_run_mod
from app.tools.match_project import MatchProjectError, create_match_project
from app.tools.match_prompt import write_match_prompt
from app.tools.match_review import save_reviewed_match, score_match
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    docs_dir,
    docs_meta_dir,
    prediction_draft_path,
    reviewed_match_path,
)


async def _seed_extract(workspace, name, docs):
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


@pytest.fixture(autouse=True)
def _force_pure_l1(monkeypatch):
    """Keep scoring deterministic + offline: never resolve a real L2 provider."""
    async def _none(ws, slug):
        return None, None
    monkeypatch.setattr(match_run_mod, "_resolve_judge_provider", _none)


async def _build(workspace):
    anchor = await _seed_extract(workspace, "inv", {
        "inv1.jpg": {"amount": "100.00", "order_no": "A1"},
        "inv2.jpg": {"amount": "200.00", "order_no": "A2"},  # will be unpaid
    })
    src = await _seed_extract(workspace, "pay", {
        "pay1.jpg": {"amount": "100.00", "ref_no": "A1"},
    })
    slug = (await create_match_project(workspace, name="对账", anchor=anchor, sources=[src]))["slug"]
    await write_match_prompt(workspace, slug, mappings={src: [
        {"anchor": "amount", "source": "amount", "tol": {"type": "number", "abs": 0.01}},
        {"anchor": "order_no", "source": "ref_no", "tol": {"type": "exact"}},
    ]}, rules="")
    return slug, src


async def test_save_reviewed_match_writes_ground_truth(workspace):
    slug, src = await _build(workspace)
    out = await save_reviewed_match(
        workspace, slug, anchor_doc="inv1.jpg", expected={src: "pay1.jpg"},
    )
    assert out["anchor_doc"] == "inv1.jpg"
    assert reviewed_match_path(workspace, slug, "inv1.jpg").exists()


async def test_save_reviewed_rejects_unknown_source(workspace):
    slug, _src = await _build(workspace)
    with pytest.raises(MatchProjectError) as ei:
        await save_reviewed_match(
            workspace, slug, anchor_doc="inv1.jpg", expected={"ghost": "x.jpg"},
        )
    assert ei.value.error_code == "match_unknown_source"


async def test_score_no_reviewed_is_zero(workspace):
    slug, _src = await _build(workspace)
    res = await score_match(workspace, slug)
    assert res["reviewed"] == 0


async def test_score_perfect(workspace):
    slug, src = await _build(workspace)
    # ground truth: inv1 pairs pay1; inv2 correctly unpaired (None)
    await save_reviewed_match(workspace, slug, anchor_doc="inv1.jpg", expected={src: "pay1.jpg"})
    await save_reviewed_match(workspace, slug, anchor_doc="inv2.jpg", expected={src: None})

    res = await score_match(workspace, slug)
    assert res["reviewed"] == 2
    ps = res["per_source"][src]
    assert ps["precision"] == 1.0 and ps["recall"] == 1.0
    assert ps["tp"] == 1 and ps["fp"] == 0 and ps["fn"] == 0
    assert res["doc_completeness"] == 1.0


async def test_score_false_negative(workspace):
    # truth says inv2 pairs pay1, but engine pairs it to inv1 (amount/order match
    # inv1 not inv2) → for inv2 the engine predicts missing → a recall miss.
    slug, src = await _build(workspace)
    await save_reviewed_match(workspace, slug, anchor_doc="inv2.jpg", expected={src: "pay1.jpg"})
    res = await score_match(workspace, slug)
    ps = res["per_source"][src]
    assert ps["recall"] == 0.0 and ps["fn"] == 1   # missed the (wrong) declared truth
    assert res["doc_completeness"] == 0.0
