"""Re-decide the codec of already-cached page rasters.

`pdf_render_page(fmt='auto')` only decides on a cache MISS, so every page a
reviewer had already opened keeps whatever encoding it got under the old
PNG-only path — the docs most likely to be opened again are exactly the ones
that never benefit. Measured on prod 2026-08-11: one such page was a 12.4 MB
PNG that took 18.3 s to reach the browser.

This walks the existing `.cache/_render/{sha}/p{n}.png` files, re-encodes each
as the review JPEG, and when JPEG wins by `_AUTO_JPEG_MIN_GAIN` swaps the PNG
for `p{n}.r.jpg`. Only derived cache is touched — every file here regenerates
on demand, and a page whose PNG stays smaller is left completely alone.

    uv run python scripts/backfill_render_format.py                 # dry run
    uv run python scripts/backfill_render_format.py --apply
    uv run python scripts/backfill_render_format.py --apply --min-kb 300

`--min-kb` skips small pages: they are neither slow nor likely to convert, and
skipping them keeps a long run focused on the pages that hurt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools.docs import _AUTO_JPEG_MIN_GAIN, encode_review_jpeg  # noqa: E402
from app.workspace.atomic import atomic_write_bytes  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="workspace", type=Path)
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    ap.add_argument("--min-kb", type=int, default=200, help="skip PNGs below this size")
    args = ap.parse_args()

    from PIL import Image

    pngs = sorted(args.workspace.rglob(".cache/_render/*/p*.png"))
    print(f"{len(pngs)} cached page PNGs under {args.workspace}")

    converted = skipped_small = skipped_keep = failed = 0
    before = after = 0
    for png in pngs:
        size = png.stat().st_size
        if size < args.min_kb * 1024:
            skipped_small += 1
            continue
        try:
            # Re-encode from the cached raster itself rather than reopening the
            # PDF: no fitz open per page, and the input is by construction the
            # exact pixels being replaced.
            with Image.open(png) as im:
                jpg = encode_review_jpeg(im.convert("RGB"))
        except Exception as e:  # noqa: BLE001 — one bad page must not stop the sweep
            failed += 1
            print(f"  ! {png}: {type(e).__name__}: {e}")
            continue

        before += size
        if size < len(jpg) * _AUTO_JPEG_MIN_GAIN:
            skipped_keep += 1
            after += size
            continue

        converted += 1
        after += len(jpg)
        if args.apply:
            atomic_write_bytes(png.with_suffix(".r.jpg"), jpg)
            png.unlink()

    mb = 1024 * 1024
    verb = "converted" if args.apply else "would convert"
    print(f"{verb}: {converted}   kept as PNG: {skipped_keep}   "
          f"below --min-kb: {skipped_small}   failed: {failed}")
    if before:
        print(f"considered {before/mb:.1f} MB  ->  {after/mb:.1f} MB   "
              f"({before/max(after,1):.2f}x smaller)")
    if not args.apply:
        print("dry run — pass --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
