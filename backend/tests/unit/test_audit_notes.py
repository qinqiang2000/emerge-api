"""digest_board_annotations — board doodles → pure text (app/tools/audit_notes.py).

Sidecars are written as real cache files (the warm-cache path of
``extract_textlayer`` with ``skip_ocr=True`` reads them straight from disk),
so the digest is exercised end-to-end with no LLM / fitz work.

RED LINE under test: the digest (and the report that embeds it) must never
carry a rect / bbox / coordinate array — rects die inside audit_notes.py.
"""
from __future__ import annotations

import json

from app.tools.audit_notes import digest_board_annotations
from app.tools.audit_run import read_audit_report
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    audits_dir,
    docs_dir,
    docs_meta_dir,
    doc_textlayer_path,
)

_RUN = "au_test1"


# --- fixtures / helpers ------------------------------------------------------


def _span(text: str, bbox: tuple[float, float, float, float]) -> dict:
    return {"bbox": list(bbox), "text": text, "font_size": 9.0}


def _put_doc(workspace, slug: str, fn: str, *, spans_by_page: dict[int, list[dict]]):
    """One stub doc + its meta + warm textlayer sidecars (the digest only ever
    reads warm sidecars — skip_ocr keeps it off the OCR path)."""
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    docs_meta_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    (docs_dir(workspace, slug) / fn).write_bytes(b"stub:" + fn.encode())
    atomic_write_json(
        docs_meta_dir(workspace, slug) / f"{fn}.json",
        {"filename": fn, "sha256": f"sha-{fn}", "page_count": max(spans_by_page, default=1),
         "ext": fn.rsplit(".", 1)[-1].lower()},
    )
    for page, spans in spans_by_page.items():
        sc = doc_textlayer_path(workspace, slug, fn, page)
        sc.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(sc, {
            "filename": fn, "page": page,
            "page_w": 600.0, "page_h": 800.0, "image_w": 600, "image_h": 800,
            "scanned": False, "text_source": "fitz", "ocr_attempted": False,
            "spans": spans,
        })


def _put_notes(workspace, slug: str, annotations: list | None, *, run_id: str = _RUN):
    run_dir = audits_dir(workspace, slug) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    blob: dict = {"run_id": run_id, "elements": []}
    if annotations is not None:
        blob["annotations"] = annotations
    atomic_write_json(run_dir / "board_notes.json", blob)


def _put_report(workspace, slug: str, *, run_id: str = _RUN):
    run_dir = audits_dir(workspace, slug) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(run_dir / "report.json", {
        "run_id": run_id, "created_at": "2026-06-12T00:00:00+00:00",
        "group": {"报价单.pdf": "报价单.pdf"}, "checks": [], "overall": "pass",
    })


def _assert_no_coords(obj) -> None:
    """No rect/bbox keys, no 4-number arrays — anywhere in the structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in ("rect", "rects", "bbox"), f"coordinate key leaked: {k}"
            _assert_no_coords(v)
    elif isinstance(obj, list):
        assert not (
            len(obj) == 4 and all(isinstance(v, (int, float)) for v in obj)
        ), f"coordinate array leaked: {obj}"
        for v in obj:
            _assert_no_coords(v)


# --- digest: anchored circles → region_text ----------------------------------


async def test_circled_spans_join_in_reading_order(workspace):
    slug = (await create_project(workspace, name="审核"))["slug"]
    _put_doc(workspace, slug, "报价单.pdf", spans_by_page={1: [
        _span("环胜科技", (10, 100, 110, 112)),     # inside, lower on the page
        _span("甲方:", (10, 60, 60, 72)),           # inside, higher → comes first
        _span("总价 ¥9,800", (10, 400, 140, 412)),  # center outside the rect
    ]})
    _put_notes(workspace, slug, [
        {"id": "e1", "kind": "draw", "doc": "报价单.pdf", "page": 1,
         "rect": [0.0, 50.0, 200.0, 150.0]},
    ])
    digest = await digest_board_annotations(workspace, slug, _RUN)
    assert digest == [{
        "doc": "报价单.pdf", "page": 1, "kind": "draw",
        "region_text": "甲方: 环胜科技",
    }]


async def test_region_text_truncates_at_200_chars(workspace):
    slug = (await create_project(workspace, name="审核"))["slug"]
    long = "x" * 150
    _put_doc(workspace, slug, "a.pdf", spans_by_page={1: [
        _span(long, (10, 10, 110, 22)), _span(long, (10, 30, 110, 42)),
    ]})
    _put_notes(workspace, slug, [
        {"id": "e1", "kind": "shape", "doc": "a.pdf", "page": 1,
         "rect": [0.0, 0.0, 600.0, 800.0]},
    ])
    [entry] = await digest_board_annotations(workspace, slug, _RUN)
    assert len(entry["region_text"]) == 201
    assert entry["region_text"].endswith("…")


async def test_text_annotation_carries_user_text(workspace):
    slug = (await create_project(workspace, name="审核"))["slug"]
    _put_doc(workspace, slug, "a.pdf", spans_by_page={1: [
        _span("金额 100", (10, 10, 80, 22)),
    ]})
    _put_notes(workspace, slug, [
        {"id": "e1", "kind": "text", "text": " 这里金额应该核对订单 ",
         "doc": "a.pdf", "page": 1, "rect": [0.0, 0.0, 200.0, 50.0]},
    ])
    [entry] = await digest_board_annotations(workspace, slug, _RUN)
    assert entry["user_text"] == "这里金额应该核对订单"
    assert entry["region_text"] == "金额 100"


async def test_anchorless_doodle_is_kept(workspace):
    """Drawn on blank board space → doc/page null, entry still surfaces (N
    strokes on the board IS a signal)."""
    slug = (await create_project(workspace, name="审核"))["slug"]
    _put_notes(workspace, slug, [
        {"id": "e1", "kind": "draw", "doc": None, "page": None, "rect": None},
        {"id": "e2", "kind": "text", "text": "整体没问题", "doc": None,
         "page": None, "rect": None},
    ])
    digest = await digest_board_annotations(workspace, slug, _RUN)
    assert digest == [
        {"doc": None, "page": None, "kind": "draw"},
        {"doc": None, "page": None, "kind": "text", "user_text": "整体没问题"},
    ]


async def test_cold_sidecar_omits_region_text(workspace):
    """Anchored onto a doc whose sidecar (or whole doc) is missing → entry
    survives without region_text, never a hard failure."""
    slug = (await create_project(workspace, name="审核"))["slug"]
    _put_notes(workspace, slug, [
        {"id": "e1", "kind": "draw", "doc": "ghost.pdf", "page": 1,
         "rect": [0.0, 0.0, 100.0, 100.0]},
    ])
    digest = await digest_board_annotations(workspace, slug, _RUN)
    assert digest == [{"doc": "ghost.pdf", "page": 1, "kind": "draw"}]


async def test_missing_file_and_pre_d1_format_yield_empty(workspace):
    slug = (await create_project(workspace, name="审核"))["slug"]
    # no board_notes.json at all
    assert await digest_board_annotations(workspace, slug, _RUN) == []
    # pre-D1 blob: elements only, no annotations key
    _put_notes(workspace, slug, None)
    assert await digest_board_annotations(workspace, slug, _RUN) == []
    # empty annotations list
    _put_notes(workspace, slug, [])
    assert await digest_board_annotations(workspace, slug, _RUN) == []


async def test_red_line_digest_carries_no_coordinates(workspace):
    slug = (await create_project(workspace, name="审核"))["slug"]
    _put_doc(workspace, slug, "a.pdf", spans_by_page={1: [
        _span("环胜", (10, 10, 50, 22)),
    ]})
    _put_notes(workspace, slug, [
        {"id": "e1", "kind": "draw", "doc": "a.pdf", "page": 1,
         "rect": [0.0, 0.0, 600.0, 800.0]},
        {"id": "e2", "kind": "text", "text": "看这里", "doc": "a.pdf",
         "page": 1, "rect": [5.0, 5.0, 60.0, 30.0]},
        {"id": "e3", "kind": "draw", "doc": None, "page": None, "rect": None},
    ])
    digest = await digest_board_annotations(workspace, slug, _RUN)
    assert len(digest) == 3
    dumped = json.dumps(digest, ensure_ascii=False)
    assert '"rect"' not in dumped and '"bbox"' not in dumped
    _assert_no_coords(digest)


# --- read_audit_report integration -------------------------------------------


async def test_report_carries_board_annotations_when_present(workspace):
    slug = (await create_project(workspace, name="审核"))["slug"]
    _put_report(workspace, slug)
    _put_doc(workspace, slug, "报价单.pdf", spans_by_page={1: [
        _span("环胜科技", (10, 10, 110, 22)),
    ]})
    _put_notes(workspace, slug, [
        {"id": "e1", "kind": "draw", "doc": "报价单.pdf", "page": 1,
         "rect": [0.0, 0.0, 200.0, 50.0]},
    ])
    report = await read_audit_report(workspace, slug)
    assert report["run_id"] == _RUN          # existing shape intact
    assert report["board_annotations"] == [{
        "doc": "报价单.pdf", "page": 1, "kind": "draw", "region_text": "环胜科技",
    }]
    _assert_no_coords(report["board_annotations"])


async def test_report_omits_key_without_annotations(workspace):
    slug = (await create_project(workspace, name="审核"))["slug"]
    _put_report(workspace, slug)
    report = await read_audit_report(workspace, slug)
    assert "board_annotations" not in report
    # pre-D1 notes blob (no annotations key) must not surface the key either
    _put_notes(workspace, slug, None)
    report = await read_audit_report(workspace, slug)
    assert "board_annotations" not in report
