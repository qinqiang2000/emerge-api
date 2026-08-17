"""render_board(kind=) folds the two board renderers. render_review_board's own
description calls itself "the structured-data twin of render_audit_board's
page-image circling" — one noun, two media. Both take (slug), both read-only,
both zero-LLM.

kind is REQUIRED: auto-dispatching on project type would be a semantics change,
and this milestone is a pure surface refactor.

Fixtures below are modeled on the existing renderer-level tests (there was no
MCP-tool-level test to copy verbatim from — see task-10-report.md):
`test_audit_board_render.py`'s `_make_docs`/`_write_report`/`_install_locate`
pattern for `audited_project`, and `test_review_board_render.py`'s
`_write_doc`/`_write_pred`/`_pass_doc` pattern for `reconciled_project`.
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from app.tools import build_emerge_mcp, registered_tool_names
from app.tools import locate as locate_mod
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    audits_dir,
    docs_dir,
    docs_meta_dir,
    prediction_draft_path,
)


async def _call(server, name: str, args: dict):
    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = server["instance"].request_handlers[CallToolRequest]
    return await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=args),
        )
    )


def _white_jpg(w: int = 600, h: int = 800) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def audited_project(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A project with one audited doc + report — no project.json needed (the
    renderer reads only report + docs through the paths helpers, same as
    test_audit_board_render.py). Locate machinery is faked the same way
    `_install_locate` fakes it there, so the evidence quote actually locates
    and an image gets composed (no real OCR/PDF rasterizer)."""
    slug = "审核板"
    fn = "报价单.jpg"
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    docs_meta_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    (docs_dir(workspace, slug) / fn).write_bytes(_white_jpg())
    atomic_write_json(
        docs_meta_dir(workspace, slug) / f"{fn}.json",
        {"filename": fn, "sha256": "x", "page_count": 1, "ext": "jpg"},
    )
    run_dir = audits_dir(workspace, slug) / "au_test0001"
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(run_dir / "report.json", {
        "run_id": "au_test0001",
        "created_at": "2026-06-11T00:00:00+00:00",
        "group": {fn: fn},
        "checks": [
            {"rule": "报价单甲方为环胜", "status": "pass", "reason": "ok",
             "level": "critical", "decided_by": "judge",
             "evidence": [{"doc": fn, "page": 1, "quote": "Acme Corporation"}]},
        ],
        "overall": "pass",
    })

    async def fake_textlayer(ws, pid, fname, *, page, skip_ocr=False):
        return {
            "page_w": 600.0, "page_h": 800.0, "image_w": 600, "image_h": 800,
            "scanned": False, "text_source": "textlayer",
            "spans": [{"bbox": [10.0, 20.0, 110.0, 32.0],
                       "text": "Acme Corporation", "font_size": 9.0}],
        }

    monkeypatch.setattr(locate_mod, "extract_textlayer", fake_textlayer)

    async def fake_page_count(ws, pid, fname):
        return 1

    monkeypatch.setattr(locate_mod, "_page_count", fake_page_count)
    return slug


@pytest.fixture
def reconciled_project(workspace: Path) -> str:
    """A project with one reconciled structured-doc review — doc + predictions/
    _draft, modeled on test_review_board_render.py's _pass_doc()/_write_pred."""
    slug = "审单dogfood"
    doc_id = "2981974"
    doc = {
        "结算总单ID": doc_id,
        "发票主信息": {"供应商名称(SUPPLYNAME)": "国药控股", "含税总金额(TOTAL_IN)": "2005.50"},
        "采购发票明细行": [
            {"发票货物或应税劳务名称": "阿瑞匹坦胶囊", "发票商品单位": "盒", "发票商品数量": 5.0,
             "发票含税金额": 2005.5, "采购发票细单ID": 41692959},
        ],
        "结算明细行": [
            {"商品名称(GOODSNAME)": "阿瑞匹坦胶囊", "单位(GOODSUNIT)": "盒", "数量(GOODSQTY)": "5.000000",
             "行金额(含税)(TOTAL_LINE)": "2005.50", "结算细单ID(SUSETDTLID)": "48103903"},
        ],
        "程序预计算": {
            "商品组配对明细(同一商品的结算多行已合并求和)": [
                {"商品": "阿瑞匹坦胶囊",
                 "发票侧": {"数量合计": 5, "细单ID": [41692959]},
                 "结算侧": {"数量合计": 5, "细单ID": ["48103903"]},
                 "金额一致": True, "数量合计一致": True},
            ],
        },
    }
    fn = f"审核数据_{doc_id}.json"
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(docs_dir(workspace, slug) / fn, doc)
    atomic_write_json(
        prediction_draft_path(workspace, slug, fn),
        {"entities": [{"pass": True, "reason": "各商品组数量合计一致", "issues": []}],
         "_run": {"model_label": "deepseek-v4-flash"}},
    )
    return slug


async def test_render_board_audit_returns_images(
    workspace: Path, stub_provider: AsyncMock, audited_project,
) -> None:
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "render_board", {"slug": audited_project, "kind": "audit"})
    content = res.root.content
    # asserts the content list contains an image block, as the old
    # render_audit_board test did (test_audit_board_render.py::
    # test_one_image_per_doc_and_png_decodes) — same PNG-decodes assertion.
    images = [b for b in content if getattr(b, "type", None) == "image"]
    assert len(images) == 1
    import base64

    raw = base64.standard_b64decode(images[0].data)
    with Image.open(io.BytesIO(raw)) as im:
        assert im.size == (600, 800)


async def test_render_board_review_returns_the_text_legend(
    workspace: Path, stub_provider: AsyncMock, reconciled_project,
) -> None:
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "render_board", {"slug": reconciled_project, "kind": "review"})
    text = res.root.content[0].text
    # copied from the old render_review_board test's shape (test_review_board_
    # render.py::test_verdict_and_tally) — header tally + per-doc verdict line.
    assert "审单核对白板：1 单" in text
    assert "通过 1" in text
    assert "结算总单 2981974 — 通过" in text
    assert "国药控股" in text


async def test_render_board_requires_kind(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    """No auto-dispatch on project type — that would change behaviour. `kind` is
    in the schema's `required`, so the rejection comes from the validation layer
    before the handler; assert that text, not a handler-side error envelope."""
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "render_board", {"slug": "whatever"})
    assert "Input validation error" in res.root.content[0].text


def test_old_board_names_are_gone() -> None:
    live = registered_tool_names(headless=True)
    assert "render_audit_board" not in live
    assert "render_review_board" not in live
    assert "render_board" in live
