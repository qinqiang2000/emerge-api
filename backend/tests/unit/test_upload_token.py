"""Presigned upload (binary data plane) — token integrity + redemption
invariants. See app/tools/upload_url.py for the design."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.tools import upload_url as uu
from app.tools.upload_url import (
    UploadTokenError,
    mint_token,
    mint_upload_urls,
    verify_token,
)

PDF = b"%PDF-1.4 fake but magic-valid body"


@pytest.fixture
def team_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "teams" / "acme"
    proj = ws / "audit1"
    proj.mkdir(parents=True)
    (proj / "project.json").write_text('{"slug":"audit1"}')
    return ws


# --- token -------------------------------------------------------------------

def test_token_roundtrip(team_ws: Path) -> None:
    tok = mint_token(team_ws, "audit1", "订单.pdf")
    claims = verify_token(tok)
    assert claims["slug"] == "audit1" and claims["fn"] == "订单.pdf"
    assert claims["ws"] == str(team_ws)


def test_token_tamper_rejected(team_ws: Path) -> None:
    tok = mint_token(team_ws, "audit1", "a.pdf")
    body, sig = tok.split(".")
    with pytest.raises(UploadTokenError):
        verify_token(body + "x." + sig)
    with pytest.raises(UploadTokenError):
        verify_token(body + "." + sig[:-2] + "zz")
    with pytest.raises(UploadTokenError):
        verify_token("garbage")


def test_token_expiry(team_ws: Path, monkeypatch) -> None:
    tok = mint_token(team_ws, "audit1", "a.pdf")
    monkeypatch.setattr(time, "time", lambda: time.gmtime and 9e9)
    with pytest.raises(UploadTokenError):
        verify_token(tok)


# --- mint --------------------------------------------------------------------

def test_mint_requires_public_base_url(team_ws: Path, monkeypatch) -> None:
    from app.config import get_settings

    s = get_settings().model_copy(update={"public_base_url": ""})
    monkeypatch.setattr(uu, "get_settings", lambda: s)
    out = mint_upload_urls(team_ws, "audit1", ["a.pdf"])
    assert out["error_code"] == "public_base_url_not_configured"


def test_mint_unknown_project(team_ws: Path, monkeypatch) -> None:
    _with_base(monkeypatch)
    out = mint_upload_urls(team_ws, "nope", ["a.pdf"])
    assert out["error_code"] == "project_not_found"


def _with_base(monkeypatch) -> None:
    from app.config import get_settings

    s = get_settings().model_copy(update={"public_base_url": "https://x.test"})
    monkeypatch.setattr(uu, "get_settings", lambda: s)


def test_mint_urls_carry_curl(team_ws: Path, monkeypatch) -> None:
    _with_base(monkeypatch)
    out = mint_upload_urls(team_ws, "audit1", ["订单.pdf", "b.pdf"])
    assert len(out["uploads"]) == 2
    u = out["uploads"][0]
    assert u["upload_url"].startswith("https://x.test/lab/upload/")
    assert "--data-binary" in u["curl"] and u["upload_url"] in u["curl"]


# --- redemption route ---------------------------------------------------------

async def test_redeem_writes_doc_with_invariants(team_ws: Path) -> None:
    from app.api.routes.upload_token import redeem_upload

    class _Req:
        async def body(self) -> bytes:
            return PDF

    tok = mint_token(team_ws, "audit1", "订单.pdf")
    out = await redeem_upload(tok, _Req())  # type: ignore[arg-type]
    assert out["filename"].endswith(".pdf")
    saved = team_ws / "audit1" / "docs" / out["filename"]
    assert saved.read_bytes() == PDF  # bytes land verbatim
    # sidecar invariant (same as browser upload path)
    assert (team_ws / "audit1" / "docs" / ".meta").is_dir()


async def test_redeem_bad_token_403_and_oversize_413(team_ws: Path) -> None:
    from fastapi import HTTPException

    from app.api.routes.upload_token import redeem_upload

    class _Req:
        def __init__(self, data: bytes) -> None:
            self._d = data

        async def body(self) -> bytes:
            return self._d

    with pytest.raises(HTTPException) as ei:
        await redeem_upload("bad.token", _Req(PDF))  # type: ignore[arg-type]
    assert ei.value.status_code == 403

    tok = mint_token(team_ws, "audit1", "big.pdf")
    big = b"%PDF" + b"0" * uu.MAX_UPLOAD_BYTES
    with pytest.raises(HTTPException) as ei:
        await redeem_upload(tok, _Req(big))  # type: ignore[arg-type]
    assert ei.value.status_code == 413


async def test_redeem_non_doc_bytes_rejected(team_ws: Path) -> None:
    from fastapi import HTTPException

    from app.api.routes.upload_token import redeem_upload

    class _Req:
        async def body(self) -> bytes:
            return b"#!/bin/sh\nrm -rf /\n"  # not pdf/png/jpg magic

    tok = mint_token(team_ws, "audit1", "evil.pdf")
    with pytest.raises(HTTPException) as ei:
        await redeem_upload(tok, _Req())  # type: ignore[arg-type]
    assert ei.value.status_code == 400
