"""Outbound data plane: capability minting + redemption.

The security-relevant cases here are not incidental — in open mode the team
workspace IS the real workspace root, so `_auth/`, `_keys.json` and `.env` sit
inside the range check. `mint_download_url` leaning on `_safe_ws_path` is what
stops "帮我下载配置文件" from minting a link to the keystore.
"""
from __future__ import annotations

import time
import zipfile

import pytest

from app.tools.download_url import (
    DownloadTokenError,
    content_disposition,
    mint_download_url,
    mint_token,
    verify_token,
)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("EMERGE_PUBLIC_BASE_URL", "https://emerge.example")
    root = tmp_path / "workspace"
    (root / "proj" / "_export").mkdir(parents=True)
    (root / "proj" / "_export" / "bundle.zip").write_bytes(b"PK\x03\x04stub")
    return root


def test_mint_returns_absolute_url_and_size(ws):
    out = mint_download_url(ws, "proj/_export/bundle.zip")
    assert out["filename"] == "bundle.zip"
    assert out["size_bytes"] == 8
    assert out["download_url"].startswith("https://emerge.example/lab/download/")
    assert out["server_path"].endswith("proj/_export/bundle.zip")
    assert "note" not in out


def test_unset_base_url_degrades_to_a_relative_link(ws, monkeypatch):
    """Dogfood 2026-08-10: local dev has no EMERGE_PUBLIC_BASE_URL, and a hard
    failure there would make the feature dead on arrival. A browser already on
    this origin resolves the relative path fine (vite proxies /lab)."""
    monkeypatch.delenv("EMERGE_PUBLIC_BASE_URL", raising=False)
    out = mint_download_url(ws, "proj/_export/bundle.zip")
    assert "error_code" not in out
    assert out["download_url"].startswith("/lab/download/")
    assert "EMERGE_PUBLIC_BASE_URL" in out["note"]


def test_round_trip_token_resolves_to_the_file(ws):
    out = mint_download_url(ws, "proj/_export/bundle.zip")
    token = out["download_url"].rsplit("/", 1)[-1]
    assert verify_token(token)["p"].endswith("proj/_export/bundle.zip")


def test_traversal_is_refused(ws):
    out = mint_download_url(ws, "../../../etc/passwd")
    assert out["error_code"] == "path_not_allowed"


@pytest.mark.parametrize(
    "secret",
    ["proj/.env", "_keys.json", "_auth/users.json", "proj/provider.key"],
)
def test_secret_shaped_paths_never_mint(ws, secret):
    """Red line. These must fail on the denylist, so the check has to hold even
    when the file genuinely exists and sits inside the workspace."""
    target = ws / secret
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("sk-real-looking-credential")
    out = mint_download_url(ws, secret)
    assert out["error_code"] == "path_not_allowed", out


def test_directory_is_refused_with_a_hint(ws):
    out = mint_download_url(ws, "proj/_export")
    assert out["error_code"] == "is_a_directory"
    assert "zip" in out["error_message_en"]


def test_missing_file_is_refused(ws):
    assert mint_download_url(ws, "proj/nope.zip")["error_code"] == "not_found"


def test_tampered_token_rejected(ws):
    out = mint_download_url(ws, "proj/_export/bundle.zip")
    token = out["download_url"].rsplit("/", 1)[-1]
    body, sig = token.split(".", 1)
    with pytest.raises(DownloadTokenError):
        verify_token(f"{body}.{'A' * len(sig)}")


def test_expired_token_rejected(ws, monkeypatch):
    token = mint_token(ws / "proj" / "_export" / "bundle.zip")
    later = time.time() + 25 * 3600  # bind now; the lambda must not re-enter time.time
    monkeypatch.setattr(time, "time", lambda: later)
    with pytest.raises(DownloadTokenError):
        verify_token(token)


def test_upload_token_cannot_be_replayed_as_download(ws):
    """Same secret signs both halves of the data plane; the kind claim is what
    keeps an inbound capability from becoming an outbound one."""
    from app.tools.upload_url import mint_token as mint_upload

    with pytest.raises(DownloadTokenError):
        verify_token(mint_upload(ws, "proj", "x.pdf"))


def test_disposition_survives_non_ascii_names():
    header = content_disposition("海信日本-627人工标注_导出.zip")
    assert "filename*=UTF-8''" in header
    assert "%E6%B5%B7" in header


def test_inline_is_signed_into_the_token_not_a_query_param(ws):
    """Disposition decides whether agent-written markup EXECUTES, so a link
    recipient must not be able to flip it."""
    (ws / "proj" / "_export" / "report.html").write_text("<h1>hi</h1>")
    out = mint_download_url(ws, "proj/_export/report.html", inline=True)
    assert out["opens_in_browser"] is True
    token = out["download_url"].rsplit("/", 1)[-1]
    assert verify_token(token).get("i") == 1


def test_inline_downgrades_for_non_previewable_types(ws):
    """"preview this zip" must degrade to a download, not error out."""
    out = mint_download_url(ws, "proj/_export/bundle.zip", inline=True)
    assert "error_code" not in out
    assert out["opens_in_browser"] is False
    assert "not a previewable type" in out["note"]


def test_svg_is_never_inline(ws):
    """Active content dressed as an image — the one type a reader would assume
    is inert."""
    (ws / "proj" / "_export" / "x.svg").write_text("<svg onload='alert(1)'/>")
    out = mint_download_url(ws, "proj/_export/x.svg", inline=True)
    assert out["opens_in_browser"] is False


def test_both_warnings_survive_together(ws, monkeypatch):
    """Local dev previewing a zip trips two notes; an assign would drop one."""
    monkeypatch.delenv("EMERGE_PUBLIC_BASE_URL", raising=False)
    out = mint_download_url(ws, "proj/_export/bundle.zip", inline=True)
    assert "not a previewable type" in out["note"]
    assert "EMERGE_PUBLIC_BASE_URL" in out["note"]


def test_inline_html_is_served_into_an_opaque_origin(ws):
    """The whole reason inline is allowed. `sandbox` without `allow-same-origin`
    means the page cannot read document.cookie or make credentialed calls to
    /lab/* — without this header, agent-written HTML on our origin is account
    takeover via any document that talks the agent into emitting a fetch()."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes import download as route

    (ws / "proj" / "_export" / "report.html").write_text("<h1>report</h1>")
    app = FastAPI()
    app.include_router(route.redeem_router)
    client = TestClient(app)

    url = mint_download_url(ws, "proj/_export/report.html", inline=True)["download_url"]
    resp = client.get(f"/lab/download/{url.rsplit('/', 1)[-1]}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers["content-disposition"].startswith("inline")
    csp = resp.headers["content-security-policy"]
    assert "sandbox" in csp
    assert "allow-same-origin" not in csp  # would let a script drop the sandbox
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"


def test_attachment_path_carries_no_sandbox_headers(ws):
    """A zip download needs none of it — keep the security header surface
    exactly where it belongs."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes import download as route

    app = FastAPI()
    app.include_router(route.redeem_router)
    client = TestClient(app)
    url = mint_download_url(ws, "proj/_export/bundle.zip")["download_url"]
    resp = client.get(f"/lab/download/{url.rsplit('/', 1)[-1]}")
    assert resp.headers["content-disposition"].startswith("attachment")
    assert "content-security-policy" not in resp.headers


def test_stale_inline_token_cannot_resurrect_a_delisted_type(ws, monkeypatch):
    """A token minted while `.svg` was previewable must not still render inline
    after it leaves the allow-list — the route re-derives safety, it does not
    trust the claim alone."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes import download as route
    from app.tools import download_url as du

    target = ws / "proj" / "_export" / "x.svg"
    target.write_text("<svg/>")
    monkeypatch.setitem(du._INLINE_TYPES, "svg", "image/svg+xml")
    token = du.mint_token(target, inline=True)
    monkeypatch.delitem(du._INLINE_TYPES, "svg")

    app = FastAPI()
    app.include_router(route.redeem_router)
    resp = TestClient(app).get(f"/lab/download/{token}")
    assert resp.headers["content-disposition"].startswith("attachment")


def test_redeem_streams_bytes(ws, monkeypatch):
    """End-to-end through the unauthed redemption route — a browser following
    the link carries no session, which is the whole point."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes import download as route

    real_zip = ws / "proj" / "_export" / "real.zip"
    with zipfile.ZipFile(real_zip, "w") as zf:
        zf.writestr("a.txt", "hello")

    app = FastAPI()
    app.include_router(route.redeem_router)
    client = TestClient(app)

    token = mint_download_url(ws, "proj/_export/real.zip")["download_url"].rsplit("/", 1)[-1]
    resp = client.get(f"/lab/download/{token}")
    assert resp.status_code == 200
    assert resp.content == real_zip.read_bytes()
    assert "real.zip" in resp.headers["content-disposition"]

    assert client.get("/lab/download/garbage").status_code == 403

    real_zip.unlink()
    assert client.get(f"/lab/download/{token}").status_code == 404
