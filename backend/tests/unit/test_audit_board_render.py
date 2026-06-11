"""render_audit_board (B4) — composite renderer + board-render/-notes routes.

Renderer tests fabricate the report.json on disk (test_audit_run.py pattern)
and real single-page JPG docs, then drive the REAL locate machinery with
injected textlayer spans (test_locate_quotes.py `_install` pattern) — no LLM,
no OCR, no PDF rasterizer. Red-line check rides along implicitly: the payload
the tests assert on carries only legend text + image bytes, never rects.

Route tests exercise the HTTP twins via TestClient against the same per-test
workspace (`env_isolation` points EMERGE_WORKSPACE_ROOT at it, open mode →
bind_workspace resolves to the flat root).
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.tools import locate as locate_mod
from app.tools.audit_board_render import render_audit_board
from app.tools.audit_run import AuditError
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import audits_dir, docs_dir, docs_meta_dir


# --- fixtures / helpers ------------------------------------------------------


def _white_jpg(w: int = 600, h: int = 800) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="JPEG")
    return buf.getvalue()


def _make_docs(workspace: Path, slug: str, filenames: list[str]) -> None:
    """Real single-page JPG docs + meta sidecars (no project.json needed —
    the renderer reads only report + docs through the paths helpers)."""
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    docs_meta_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    for fn in filenames:
        (docs_dir(workspace, slug) / fn).write_bytes(_white_jpg())
        atomic_write_json(
            docs_meta_dir(workspace, slug) / f"{fn}.json",
            {"filename": fn, "sha256": "x", "page_count": 1, "ext": "jpg"},
        )


def _write_report(
    workspace: Path, slug: str, *, checks: list[dict],
    group_docs: list[str], run_id: str = "au_test0001",
) -> str:
    run_dir = audits_dir(workspace, slug) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(run_dir / "report.json", {
        "run_id": run_id,
        "created_at": "2026-06-11T00:00:00+00:00",
        "group": {fn: fn for fn in group_docs},
        "checks": checks,
        "overall": "pass",
    })
    return run_id


def _span(text: str, bbox=(10.0, 20.0, 110.0, 32.0), size: float = 9.0) -> dict:
    return {"bbox": list(bbox), "text": text, "font_size": size}


def _install_locate(monkeypatch, *, pages: dict[int, list[dict]]) -> None:
    """Inject textlayer spans under the real locate_quotes machinery
    (test_locate_quotes.py pattern; same spans serve every doc)."""

    async def fake_textlayer(ws, pid, fname, *, page, skip_ocr=False):
        assert skip_ocr is True  # warm-sidecar-only discipline
        return {
            "page_w": 600.0, "page_h": 800.0, "image_w": 600, "image_h": 800,
            "scanned": False, "text_source": "textlayer",
            "spans": pages.get(page, []),
        }

    monkeypatch.setattr(locate_mod, "extract_textlayer", fake_textlayer)

    async def fake_page_count(ws, pid, fname):
        return max(pages) if pages else 0

    monkeypatch.setattr(locate_mod, "_page_count", fake_page_count)


_DOCS = ["报价单.jpg", "收货单.jpg"]
_CHECKS = [
    {"rule": "报价单甲方为环胜", "status": "pass", "reason": "ok",
     "level": "critical", "decided_by": "judge",
     "evidence": [{"doc": "报价单.jpg", "page": 1, "quote": "Acme Corporation"}]},
    {"rule": "报价单金额与收货单一致", "status": "fail", "reason": "不一致",
     "level": "critical", "decided_by": "judge",
     "evidence": [{"doc": "收货单.jpg", "page": 1, "quote": "Total 111.00 USD"}]},
]
_PAGES = {1: [
    _span("Acme Corporation"),
    _span("Total 111.00 USD", bbox=(200.0, 300.0, 330.0, 316.0)),
]}


# --- renderer ------------------------------------------------------------------


async def test_legend_aligns_with_checks(workspace, monkeypatch):
    """Legend numbering is 1-based check order; status mirrors the verdict."""
    _make_docs(workspace, "审核板", _DOCS)
    _write_report(workspace, "审核板", checks=_CHECKS, group_docs=_DOCS)
    _install_locate(monkeypatch, pages=_PAGES)

    out = await render_audit_board(workspace, "审核板")
    assert out["legend"] == [
        {"n": 1, "rule": "报价单甲方为环胜", "status": "pass"},
        {"n": 2, "rule": "报价单金额与收货单一致", "status": "fail"},
    ]


async def test_one_image_per_doc_and_png_decodes(workspace, monkeypatch):
    _make_docs(workspace, "审核板", _DOCS)
    _write_report(workspace, "审核板", checks=_CHECKS, group_docs=_DOCS)
    _install_locate(monkeypatch, pages=_PAGES)

    out = await render_audit_board(workspace, "审核板")
    assert [img["doc"] for img in out["images"]] == _DOCS  # group order kept
    assert out["truncated"] is False
    for img in out["images"]:
        raw = base64.standard_b64decode(img["data_b64"])
        with Image.open(io.BytesIO(raw)) as im:
            assert im.size == (600, 800)  # single page, no stacking gap
            assert im.format in ("PNG", "JPEG")
        assert img["media_type"] in ("image/png", "image/jpeg")
    # red line: nothing rect-shaped leaves the render layer
    assert set(out) == {"legend", "images", "truncated"}
    assert all(set(i) == {"doc", "media_type", "data_b64"} for i in out["images"])


async def test_unlocated_evidence_takes_corner_badge_path(workspace, monkeypatch):
    """Evidence locate returns status none → corner badge, never a crash."""
    _make_docs(workspace, "审核板", ["报价单.jpg"])
    checks = [{"rule": "报价单盖红章", "status": "unclear", "reason": "图不清",
               "level": "critical", "decided_by": "judge",
               "evidence": [{"doc": "报价单.jpg", "page": 1,
                             "quote": "no such text anywhere"}]}]
    _write_report(workspace, "审核板", checks=checks, group_docs=["报价单.jpg"])
    _install_locate(monkeypatch, pages=_PAGES)

    out = await render_audit_board(workspace, "审核板")
    assert len(out["images"]) == 1  # the doc still renders, badge in corner
    assert out["legend"][0]["status"] == "unclear"


async def test_no_report_raises_audit_no_report(workspace):
    with pytest.raises(AuditError) as ei:
        await render_audit_board(workspace, "未审核")
    assert ei.value.error_code == "audit_no_report"


# --- routes ---------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app)


def test_route_board_render_happy_path(workspace, client, monkeypatch):
    _make_docs(workspace, "审核板", _DOCS)
    _write_report(workspace, "审核板", checks=_CHECKS, group_docs=_DOCS)
    _install_locate(monkeypatch, pages=_PAGES)

    resp = client.get("/lab/projects/审核板/audit/board-render")
    assert resp.status_code == 200
    body = resp.json()
    assert [e["n"] for e in body["legend"]] == [1, 2]
    assert len(body["images"]) == 2
    assert body["truncated"] is False


def test_route_board_render_no_report_404(workspace, client):
    resp = client.get("/lab/projects/未审核/audit/board-render")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "audit_no_report"


# --- board notes (render-layer persistence, route-without-tool) -------------------


def test_board_notes_get_empty_then_put_then_get(workspace, client):
    run_id = _write_report(workspace, "审核板", checks=_CHECKS, group_docs=_DOCS)

    resp = client.get("/lab/projects/审核板/audit/board-notes")
    assert resp.status_code == 200
    assert resp.json() == {"run_id": run_id, "elements": []}

    elements = [{"id": "e1", "type": "freedraw", "points": [[0, 0], [5, 5]]},
                {"id": "e2", "type": "text", "text": "缺章，周一补"}]
    resp = client.put(
        "/lab/projects/审核板/audit/board-notes",
        json={"run_id": run_id, "elements": elements},
    )
    assert resp.status_code == 200
    assert resp.json() == {"run_id": run_id, "elements_saved": 2}

    resp = client.get("/lab/projects/审核板/audit/board-notes")
    assert resp.status_code == 200
    assert resp.json() == {"run_id": run_id, "elements": elements}

    # persisted next to (not inside) the derived report blob, atomic JSON
    on_disk = json.loads(
        (audits_dir(workspace, "审核板") / run_id / "board_notes.json")
        .read_text(encoding="utf-8"))
    assert on_disk["elements"] == elements


def test_board_notes_get_without_report_404(workspace, client):
    resp = client.get("/lab/projects/未审核/audit/board-notes")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "audit_no_report"


def test_board_notes_put_unknown_run_404(workspace, client):
    _write_report(workspace, "审核板", checks=_CHECKS, group_docs=_DOCS)
    resp = client.put(
        "/lab/projects/审核板/audit/board-notes",
        json={"run_id": "au_nosuchrun", "elements": []},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "audit_run_not_found"
    # separator-shaped run_ids can never name a run dir — refused the same way
    resp = client.put(
        "/lab/projects/审核板/audit/board-notes",
        json={"run_id": "../escape", "elements": []},
    )
    assert resp.status_code == 404


def test_board_notes_put_oversize_400(workspace, client):
    run_id = _write_report(workspace, "审核板", checks=_CHECKS, group_docs=_DOCS)
    resp = client.put(
        "/lab/projects/审核板/audit/board-notes",
        json={"run_id": run_id, "elements": [{"blob": "x" * 1_100_000}]},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "board_notes_too_large"
    # the oversize write never landed
    assert not (audits_dir(workspace, "审核板") / run_id / "board_notes.json").exists()
