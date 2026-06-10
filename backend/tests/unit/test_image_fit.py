"""`fit_image_for_agent` — SDK-boundary image budget (2026-06-10 plan).

Large base64 images accumulating in the agent session blow the
claude_agent_sdk control-protocol buffer (`agent_failure: JSON exceeded
maximum buffer size`). The fix downsizes images at the SDK boundary only:

* `fit_image_for_agent` itself (pure function, these tests);
* the `t_read_doc_image` MCP wrapper (integration test below);
* `read_doc_image` the *function* must stay full-resolution — audit /
  translate / textlayer call it directly (regression anchor below).
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest.mock import MagicMock

import fitz  # PyMuPDF
from mcp.types import CallToolRequest, CallToolRequestParams

from app.tools import build_emerge_mcp
from app.tools.docs import (
    _FIT_MAX_BYTES,
    _FIT_MAX_EDGE_PX,
    fit_image_for_agent,
    read_doc_image,
    upload_doc,
)
from app.tools.projects import create_project


def _flat_png(w: int, h: int, value: int = 220) -> bytes:
    """Uniform-gray RGB PNG of the given pixel dimensions."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
    pix.clear_with(value)
    return pix.tobytes("png")


def _noise_png(w: int, h: int) -> bytes:
    """Incompressible RGB PNG — bytes scale ~w*h*3 (PNG can't squeeze noise)."""
    samples = os.urandom(w * h * 3)
    pix = fitz.Pixmap(fitz.csRGB, w, h, samples, False)
    return pix.tobytes("png")


def _alpha_png(w: int, h: int) -> bytes:
    """RGBA PNG: top half fully transparent, bottom half opaque red."""
    transparent_row = bytes(4) * w
    red_row = bytes((255, 0, 0, 255)) * w
    samples = transparent_row * (h // 2) + red_row * (h - h // 2)
    pix = fitz.Pixmap(fitz.csRGB, w, h, samples, True)
    return pix.tobytes("png")


def _dims(data: bytes) -> tuple[int, int]:
    pix = fitz.Pixmap(data)
    return pix.width, pix.height


# --- pure function -----------------------------------------------------------


def test_big_png_resized_to_budget() -> None:
    """2400×3400 (the 150dpi-A4-render shape) → long edge ≤1568, JPEG, and
    bytes inside the 400KB budget."""
    src = _flat_png(2400, 3400)
    fitted, mime = fit_image_for_agent(src, "image/png")
    assert mime == "image/jpeg"
    assert fitted[:3] == b"\xff\xd8\xff"  # real JPEG magic
    w, h = _dims(fitted)
    assert max(w, h) <= _FIT_MAX_EDGE_PX
    assert len(fitted) <= _FIT_MAX_BYTES
    # Aspect ratio preserved (proportional resize).
    assert abs(w / h - 2400 / 3400) < 0.01


def test_small_image_returned_unchanged() -> None:
    """800×600 uniform PNG is both dimension- and byte-compliant → identity."""
    src = _flat_png(800, 600)
    assert len(src) <= _FIT_MAX_BYTES
    fitted, mime = fit_image_for_agent(src, "image/png")
    assert fitted is src
    assert mime == "image/png"


def test_heavy_bytes_small_dims_reencoded() -> None:
    """Dims within 1568 but bytes over 400KB (noise PNG) → JPEG re-encode at
    original size."""
    src = _noise_png(800, 600)  # ~1.4MB, PNG can't compress noise
    assert len(src) > _FIT_MAX_BYTES
    fitted, mime = fit_image_for_agent(src, "image/png")
    assert mime == "image/jpeg"
    assert len(fitted) < len(src)
    # No resize on this branch — dims were already compliant.
    assert _dims(fitted) == (800, 600)


def test_alpha_png_flattened_onto_white() -> None:
    """Transparent regions must come out white (JPEG has no alpha), opaque
    regions keep their color."""
    src = _alpha_png(2000, 3000)
    fitted, mime = fit_image_for_agent(src, "image/png")
    assert mime == "image/jpeg"
    out = fitz.Pixmap(fitted)
    assert max(out.width, out.height) <= _FIT_MAX_EDGE_PX
    # top half was fully transparent → white (allow JPEG artifacts)
    r, g, b = out.pixel(out.width // 2, 5)
    assert min(r, g, b) >= 240, (r, g, b)
    # bottom half was opaque red → still red
    r, g, b = out.pixel(out.width // 2, out.height - 5)
    assert r >= 200 and g <= 60 and b <= 60, (r, g, b)


def test_garbage_bytes_passthrough() -> None:
    """Undecodable payload → returned unchanged, no raise (can't-compress ≠
    can't-see)."""
    junk = b"definitely not an image" * 10
    fitted, mime = fit_image_for_agent(junk, "image/png")
    assert fitted is junk
    assert mime == "image/png"


# --- SDK boundary: t_read_doc_image wrapper ----------------------------------


async def _call_tool(server, name: str, args: dict):
    handler = server["instance"].request_handlers[CallToolRequest]
    return await handler(CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=args),
    ))


async def test_tool_wrapper_fits_image_but_function_stays_raw(
    workspace: Path, stub_provider,
) -> None:
    """The MCP wrapper applies `fit_image_for_agent`; `read_doc_image` the
    function still returns the original bytes (regression anchor: the
    provider-direct paths — audit / translate / textlayer — must keep full
    resolution)."""
    pid = (await create_project(workspace, name="x"))["slug"]
    big = _flat_png(2400, 3400)
    meta = await upload_doc(workspace, pid, big, "scan.png")

    # Direct function call → raw on-disk bytes, untouched.
    raw = await read_doc_image(workspace, pid, meta["filename"])
    assert base64.b64decode(raw["data"]) == big
    assert raw["mime"] == "image/png"

    # MCP wrapper → fitted JPEG within budget.
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    result = await _call_tool(
        server, "read_doc_image", {"slug": pid, "filename": meta["filename"]},
    )
    blocks = result.root.content
    img = next(b for b in blocks if b.type == "image")
    fitted = base64.b64decode(img.data)
    assert img.mimeType == "image/jpeg"
    assert len(fitted) <= _FIT_MAX_BYTES
    assert max(_dims(fitted)) <= _FIT_MAX_EDGE_PX


async def test_tool_wrapper_passes_small_image_through(
    workspace: Path, stub_provider,
) -> None:
    """A budget-compliant image flows through the wrapper byte-identical —
    fitting is conditional, not a blanket re-encode."""
    pid = (await create_project(workspace, name="x"))["slug"]
    small = _flat_png(800, 600)
    meta = await upload_doc(workspace, pid, small, "thumb.png")

    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    result = await _call_tool(
        server, "read_doc_image", {"slug": pid, "filename": meta["filename"]},
    )
    img = next(b for b in result.root.content if b.type == "image")
    assert base64.b64decode(img.data) == small
    assert img.mimeType == "image/png"
