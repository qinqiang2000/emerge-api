"""B5b — MCP Apps board-view capability tokens + redemption routes.

Reuses test_audit_board_render's fixtures (real jpg docs + fabricated report
+ injected textlayer spans) — the payload path shares `_locate_with_warm`.
Routes are deliberately UNAUTHED (the HMAC token IS the auth) and
route-without-tool (rects ride them into the iframe only — red line).
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.board_view import (
    BoardViewTokenError,
    build_board_view,
    mint_board_view_token,
    mint_board_view_url,
    verify_board_view_token,
)
from app.tools.upload_url import mint_token as mint_upload_token
from tests.unit.test_audit_board_render import (
    _CHECKS,
    _DOCS,
    _PAGES,
    _install_locate,
    _make_docs,
    _write_report,
)

pytestmark = pytest.mark.anyio

_SLUG = "审核板"


@pytest.fixture
def client():
    return TestClient(app)


# ── token semantics ─────────────────────────────────────────────────────────

async def test_token_roundtrip(workspace) -> None:
    token = mint_board_view_token(workspace, _SLUG)
    claims = verify_board_view_token(token)
    assert claims["slug"] == _SLUG
    assert claims["p"] == "board-view"
    assert claims["ws"] == str(workspace.resolve())
    assert claims["exp"] > time.time()


async def test_token_tamper_rejected(workspace) -> None:
    token = mint_board_view_token(workspace, _SLUG)
    body, sig = token.split(".", 1)
    with pytest.raises(BoardViewTokenError):
        verify_board_view_token(f"{body}.{sig[:-2]}xx")
    with pytest.raises(BoardViewTokenError):
        verify_board_view_token("garbage")


async def test_upload_token_not_replayable_as_view(workspace) -> None:
    # purpose tag: an upload capability must never open the board view
    upload_tok = mint_upload_token(workspace, _SLUG, "a.jpg")
    with pytest.raises(BoardViewTokenError):
        verify_board_view_token(upload_tok)


async def test_mint_url_requires_public_base(workspace, monkeypatch) -> None:
    monkeypatch.delenv("EMERGE_PUBLIC_BASE_URL", raising=False)
    assert mint_board_view_url(workspace, _SLUG) is None
    monkeypatch.setenv("EMERGE_PUBLIC_BASE_URL", "https://x.example")
    url = mint_board_view_url(workspace, _SLUG)
    assert url and url.startswith("https://x.example/lab/board-view/")


# ── payload ─────────────────────────────────────────────────────────────────

async def test_build_board_view_payload(workspace, monkeypatch) -> None:
    _make_docs(workspace, _SLUG, _DOCS)
    _write_report(workspace, _SLUG, checks=_CHECKS, group_docs=_DOCS)
    _install_locate(monkeypatch, pages=_PAGES)

    out = await build_board_view(workspace, _SLUG)
    assert out["slug"] == _SLUG
    assert len(out["report"]["checks"]) == 2
    assert {d["doc"] for d in out["docs"]} == set(_DOCS)
    assert all(d["pages"] >= 1 and d["ext"] == "jpg" for d in out["docs"])
    # both checks' evidence locate against the injected spans;
    # keys are "{checkIdx}-{evIdx}" and rects stay numeric quads
    assert set(out["locations"]) == {"0-0", "1-0"}
    for loc in out["locations"].values():
        assert loc["rects"] and all(len(r) >= 4 for r in loc["rects"])
        assert loc["doc"] in _DOCS


# ── routes ──────────────────────────────────────────────────────────────────

def test_routes_redeem_and_reject(workspace, client, monkeypatch) -> None:
    _make_docs(workspace, _SLUG, _DOCS)
    _write_report(workspace, _SLUG, checks=_CHECKS, group_docs=_DOCS)
    _install_locate(monkeypatch, pages=_PAGES)
    token = mint_board_view_token(workspace, _SLUG)

    r = client.get(f"/lab/board-view/{token}")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == _SLUG and "locations" in body
    # CORS: the Apps iframe fetches cross-origin; without ACAO:* the browser
    # discards the response ("Failed to fetch" — Cowork dogfood 2026-06-11)
    assert r.headers["access-control-allow-origin"] == "*"

    # browser navigation (Accept: text/html) → the board app itself
    rh = client.get(f"/lab/board-view/{token}", headers={"accept": "text/html"})
    assert rh.status_code == 200
    assert rh.headers["content-type"].startswith("text/html")
    assert "audit board" in rh.text and "/lab/board-view/" in rh.text
    # G2: the browser branch serves the geometry-injected HTML (same
    # _board_app_html as the MCP resource) — never the raw placeholder
    assert "globalThis.BoardGeom" in rh.text
    assert "__BOARD_GEOMETRY_JS__" not in rh.text

    # page raster through the token (jpg doc → page 1 original bytes)
    doc = _DOCS[0]
    r2 = client.get(f"/lab/board-view/{token}/pages/{doc}/1")
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("image/")
    # out-of-range page on a raster doc
    assert client.get(f"/lab/board-view/{token}/pages/{doc}/2").status_code == 404

    # bad token → 401 on both routes
    assert client.get("/lab/board-view/bogus.token").status_code == 401
    assert client.get(f"/lab/board-view/bogus.token/pages/{doc}/1").status_code == 401


def test_view_route_no_report_404(workspace, client) -> None:
    token = mint_board_view_token(workspace, "未审核项目")
    r = client.get(f"/lab/board-view/{token}")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "audit_no_report"


# ── G2: geometry injection (single source: board_geometry.js) ───────────────

def test_board_app_html_injects_geometry() -> None:
    from app.mcp_server import _board_app_html

    html = _board_app_html()
    assert "__BOARD_GEOMETRY_JS__" not in html  # placeholder fully consumed
    assert "globalThis.BoardGeom" in html       # module body injected
    assert "GEOM-JSON-BEGIN" in html            # constants block rode along


def test_board_app_raw_has_no_hand_copied_geometry() -> None:
    """漂移闸门：board_app.html 原文（注入前）不得再手写几何常量/trim 公式
    （v9 commit 707e3b4 追的就是第三份手抄漏搬——手抄必须死透）。"""
    import re
    from pathlib import Path

    import app.mcp_server as mcp_server

    raw = (Path(mcp_server.__file__).parent / "skills" / "board_app.html"
           ).read_text(encoding="utf-8")
    assert "/*__BOARD_GEOMETRY_JS__*/" in raw  # injection point still present
    assert not re.search(
        r"const SCALE\s*=|const PX_PER_PT|1 / Math\.hypot\(dx /", raw)
