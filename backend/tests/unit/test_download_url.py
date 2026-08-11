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
