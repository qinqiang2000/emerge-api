"""`fmt='auto'` — the review path picks the smaller encoding per page.

Why this exists: the reviewer and the server are a continent apart, so the page
raster's *size* is the wait. Measured on prod (2026-08-11, 3089 docs): cached
page-1 PNGs run median 638 KB / p90 1.7 MB, while the render itself costs only
~150 ms. Re-encoding as JPEG q92 gives 2.5× overall — and the win tracks page
weight exactly (1.03–1.17× on PNG-sourced pages, 3.4–4.4× on scans). Every
sampled page above 400 KB carried JPEG-encoded embedded images, so on the pages
this actually switches, PNG was losslessly preserving JPEG artifacts.

The guard these tests hold: `auto` must never make a page BIGGER, must not
silently re-encode pages where lossless is nearly free, and must leave every
other caller's format untouched.
"""

from pathlib import Path

import pytest

from app.tools.docs import pdf_render_page, upload_doc
from app.tools.projects import create_project

pytestmark = pytest.mark.anyio

_PDF_FIXTURE = Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf"


async def _pdf_project(workspace: Path) -> tuple[str, str]:
    pid = (await create_project(workspace, name="x"))["slug"]
    meta = await upload_doc(workspace, pid, _PDF_FIXTURE.read_bytes(), "invoice.pdf")
    return pid, meta["filename"]


async def test_auto_never_serves_a_bigger_file_than_png(workspace: Path) -> None:
    """Whatever `auto` picks, it must not be larger than the lossless render —
    that's the entire justification for the extra encode pass."""
    pid, fn = await _pdf_project(workspace)
    png = await pdf_render_page(workspace, pid, fn, page=1, fmt="png")
    png_size = png.stat().st_size
    png.unlink()  # force auto to decide rather than reuse the warm lossless file

    chosen = await pdf_render_page(workspace, pid, fn, page=1, fmt="auto")
    assert chosen.stat().st_size <= png_size


async def test_auto_keeps_png_when_jpeg_barely_wins(workspace: Path) -> None:
    """The fixture is a text/vector invoice — exactly the page shape where PNG
    is already small and JPEG buys nothing. Losslessness is only given up for a
    real (≥1.5×) gain, so this page must stay PNG."""
    pid, fn = await _pdf_project(workspace)
    chosen = await pdf_render_page(workspace, pid, fn, page=1, fmt="auto")
    assert chosen.suffix == ".png"


async def test_auto_reuses_an_existing_lossless_render(workspace: Path) -> None:
    """No decision made yet + a warm lossless render → serve it. Re-deciding is
    the backfill's job, not a cost to charge the reader."""
    pid, fn = await _pdf_project(workspace)
    png = await pdf_render_page(workspace, pid, fn, page=1, fmt="png")
    stamp = png.stat().st_mtime_ns

    chosen = await pdf_render_page(workspace, pid, fn, page=1, fmt="auto")
    assert chosen == png
    assert chosen.stat().st_mtime_ns == stamp, "auto re-rendered a warm page"


async def test_auto_slot_outranks_a_rematerialized_png(workspace: Path) -> None:
    """Once `auto` has decided JPEG for a page, a PNG appearing beside it must
    not take the decision back.

    This is not hypothetical: every other in-tree caller renders at the `png`
    default, so one agent `read_doc_image` call re-creates `p{n}.png`. Probing
    PNG first let that silently undo the backfill and put a 12 MB page back on
    the reviewer's wire — measured on prod, 18.3 s for one page."""
    pid, fn = await _pdf_project(workspace)
    render_dir = (await pdf_render_page(workspace, pid, fn, page=1, fmt="png")).parent
    # Plant both slots, as a backfilled page + a later agent vision call leave them.
    (render_dir / "p1.r.jpg").write_bytes(b"\xff\xd8\xff\xdb decided-jpeg")

    chosen = await pdf_render_page(workspace, pid, fn, page=1, fmt="auto")
    assert chosen.name == "p1.r.jpg"


async def test_auto_jpeg_is_progressive(workspace: Path) -> None:
    """Progressive is the point, not a detail: it lets the browser paint a
    coarse full page after roughly the first tenth of the bytes instead of
    showing nothing until the last one lands. Encode the review JPEG directly
    (the invoice fixture legitimately stays PNG) and assert the marker."""
    import fitz
    from PIL import Image
    import io

    from app.tools.docs import encode_review_jpeg, pixmap_to_image

    with fitz.open(_PDF_FIXTURE) as pdf:
        pix = pdf[0].get_pixmap(dpi=150)
    data = encode_review_jpeg(pixmap_to_image(pix))
    with Image.open(io.BytesIO(data)) as im:
        assert im.format == "JPEG"
        assert im.info.get("progressive") or im.info.get("progression")


async def test_render_does_not_block_the_event_loop(workspace: Path) -> None:
    """Rasterising + encoding is 150-500 ms of pure CPU (and `auto` encodes
    twice). Left on the event loop it stalls every other request for that whole
    window — and opening a doc fans out ~10 parallel calls, so one cold page
    held up the fields the reviewer was waiting for.

    The margin here is ~30×, not marginal: a ticker on a 1 ms sleep racks up
    dozens of ticks across a threaded render and exactly 0-1 if the work is
    inline, so `>= 2` is a sharp assertion, not a timing gamble."""
    import asyncio

    pid, fn = await _pdf_project(workspace)

    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.001)
            ticks += 1

    beat = asyncio.create_task(ticker())
    try:
        await asyncio.sleep(0.005)  # let the ticker actually start
        ticks = 0
        await pdf_render_page(workspace, pid, fn, page=1, fmt="auto")
    finally:
        beat.cancel()

    assert ticks >= 2, "render held the event loop for its whole duration"


async def test_other_formats_are_untouched(workspace: Path) -> None:
    """`auto` is opt-in. The default and the board's explicit jpeg keep their
    own cache slots, so in-tree callers that assume a codec still get it."""
    pid, fn = await _pdf_project(workspace)
    default = await pdf_render_page(workspace, pid, fn, page=1)
    board = await pdf_render_page(workspace, pid, fn, page=1, fmt="jpeg")
    assert default.suffix == ".png"
    assert board.suffix == ".jpg"
    assert board.name == "p1.jpg", "board slot must not collide with auto's"
