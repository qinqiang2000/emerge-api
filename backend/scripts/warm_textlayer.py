"""Backfill the text-layer (locate/translate input) the migration never warmed.

The migration recovered `_evidence` (grounding TEXT) via backfill_grounding.py, but
grounding sends the whole page image to the LLM — it does NOT build the text layer.
The text layer (fitz spans for electronic pages, Gemini OCR spans for scanned ones)
is what `app/tools/locate.py` aligns the source quote against to recover highlight
rects, and what translate reads. It is normally built lazily the first time the
viewer opens a doc — so a migrated corpus nobody clicked through has NO text layer:
every field resolves to `none` ("完全没定位") and translation re-runs live every open
("还要实时翻译"). See INSIGHTS "locate ... Still open: warm textlayer at upload/extract".

This is that missing warm step, run over existing data. Per page it does the cheap
thing first:

  1. extract_textlayer(skip_ocr=True) — fitz only, local, free, no LLM. An ELECTRONIC
     page gets accurate spans here and is DONE (no OCR call, no egress).
  2. only a SCANNED page (fitz empty) falls through to extract_textlayer(skip_ocr=False),
     which spends one Gemini OCR call. So OCR cost == scanned-page count, not total pages.

Idempotent + resumable (built for a bandwidth-capped prod host — see MEMORY: prod
egress ~1.5Mbps, OCR uploads page images, multiple keys don't help):
  • a page that already has spans is skipped (no LLM call) — re-run resumes + retries;
  • per-page retry with exponential backoff rides out rate limits / blips;
  • hard per-OCR timeout breaks a dead-socket hang (same trap as backfill_grounding);
  • LOW default concurrency + `--sleep` pacing so the batch doesn't saturate egress
    and tank the live UI. `--skip-ocr` does a zero-egress first pass (electronic docs
    only) so the 202 fitz docs light up instantly while OCR is scheduled separately.

    # zero-cost first pass: fix every electronic doc instantly, no OCR
    python3 scripts/warm_textlayer.py --project 海信日本 --skip-ocr
    # then the scanned pages (paced; run off-peak)
    python3 scripts/warm_textlayer.py --project 海信日本 --concurrency 3 --sleep 0.3
    python3 scripts/warm_textlayer.py --project 海信日本 --dry-run   # plan only

Provider keys come from backend/.env (loaded below, same as backfill_grounding.py).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

_BACKEND = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND / ".env")
sys.path.insert(0, str(_BACKEND))

from app.config import get_settings  # noqa: E402
from app.tools.textlayer import extract_textlayer  # noqa: E402
from app.workspace.paths import doc_meta_path, doc_textlayer_path  # noqa: E402

_SKIP_DIRS = {"_trash", ".cache", "_staging", ".git", "__pycache__", "_auth", "_published"}
# Per-OCR hard ceiling (seconds). Generous vs the normal round-trip; its job is to
# break a dead socket, not cap healthy slow calls (mirrors backfill_grounding).
_OCR_TIMEOUT = 150.0


def _find_projects(root: Path, project: str) -> list[tuple[Path, str]]:
    """(workspace, slug) per project matching `project` substring. workspace =
    the project dir's parent (team dir in tenant mode, flat root otherwise) —
    same convention as backfill_grounding._resolve."""
    out: list[tuple[Path, str]] = []
    for proj in root.glob("**/project.json"):
        pdir = proj.parent
        rel = pdir.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if project and project not in str(rel):
            continue
        out.append((pdir.parent, pdir.name))
    out.sort(key=lambda it: it[1])
    return out


def _docs_of(workspace: Path, slug: str, doc_filter: str) -> list[tuple[str, int]]:
    """(filename, page_count) for every doc of a project, from its meta sidecars."""
    meta_dir = doc_meta_path(workspace, slug, "x").parent  # docs/.meta
    out: list[tuple[str, int]] = []
    if not meta_dir.exists():
        return out
    for mp in sorted(meta_dir.glob("*.json")):
        filename = mp.name[: -len(".json")]
        if "." not in filename:  # skip non-doc sidecars
            continue
        if doc_filter and doc_filter not in filename:
            continue
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append((filename, int(meta.get("page_count", 1) or 1)))
    return out


async def _warm_page(
    workspace: Path, slug: str, filename: str, page: int, *,
    skip_ocr_only: bool, retries: int, ocr_model: str | None, force: bool,
) -> str:
    """Warm one page. Returns status ∈ cached|fitz|ocr|ocr_empty|deferred|fail."""
    side = doc_textlayer_path(workspace, slug, filename, page)
    side_existed = side.exists()
    # Cheap pass: fitz (+ cached). Electronic pages get real spans here for free.
    try:
        cur = await extract_textlayer(workspace, slug, filename, page=page, skip_ocr=True)
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL  {slug}/{filename} p{page} (fitz: {type(e).__name__}: {e})", flush=True)
        return "fail"
    if cur.get("spans"):
        return "cached" if side_existed else "fitz"
    # No spans → scanned page; needs OCR.
    if skip_ocr_only:
        return "deferred"
    # --force: a page that already OCR-attempted-and-got-nothing (flash-lite's
    # malformed JSON → empty, ocr_attempted=True) is short-circuited to the cached
    # empty by extract_textlayer's cache guard and can never re-OCR. Drop the empty
    # sidecar so the OCR below runs fresh with the (stronger) ocr_model. Only ever
    # touches a page with NO spans — good electronic / OCR'd pages returned above.
    if force:
        side.unlink(missing_ok=True)
    delay = 1.0
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            res = await asyncio.wait_for(
                extract_textlayer(workspace, slug, filename, page=page, skip_ocr=False, ocr_model=ocr_model),
                timeout=_OCR_TIMEOUT,
            )
            return "ocr" if res.get("spans") else "ocr_empty"
        except Exception as e:  # noqa: BLE001 — best-effort; every error retried
            last = e
            if attempt < retries:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
    print(f"  FAIL  {slug}/{filename} p{page} (ocr: {type(last).__name__}: {last})", flush=True)
    return "fail"


async def main() -> int:
    global _OCR_TIMEOUT
    ap = argparse.ArgumentParser(description="Warm the text-layer (locate/translate input)")
    ap.add_argument("--root", type=Path, default=None, help="workspace root (default: settings.workspace_root)")
    ap.add_argument("--project", default="", metavar="SUBSTR", help="only projects whose path contains SUBSTR")
    ap.add_argument("--doc", default="", metavar="SUBSTR", help="only docs whose filename contains SUBSTR")
    ap.add_argument("--skip-ocr", action="store_true",
                    help="fitz-only zero-egress pass: warm electronic pages, DEFER scanned (no OCR)")
    ap.add_argument("--model", default=None, metavar="PROVIDER_MODEL_ID",
                    help="OCR model override (e.g. gemini-flash-latest). Default flash-lite "
                         "truncates JSON on dense pages → 0 spans; a stronger model fixes it.")
    ap.add_argument("--force", action="store_true",
                    help="re-OCR pages that previously attempted-and-got-nothing (drops the empty "
                         "sidecar first; needed to upgrade flash-lite's empty pages to --model)")
    ap.add_argument("--dry-run", action="store_true", help="list page counts; no extraction")
    ap.add_argument("--concurrency", type=int, default=4, help="parallel warms (default 4; lower if egress saturates)")
    ap.add_argument("--retries", type=int, default=4, help="per-OCR retry attempts on transient errors")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds to pause after each OCR'd page (pacing)")
    ap.add_argument("--call-timeout", type=float, default=_OCR_TIMEOUT, metavar="SECS",
                    help=f"hard per-OCR timeout (default {_OCR_TIMEOUT:g}s)")
    ap.add_argument("--limit", type=int, default=0, help="OCR at most N scanned pages this run (0=all)")
    args = ap.parse_args()
    _OCR_TIMEOUT = args.call_timeout

    root = (args.root or get_settings().workspace_root).resolve()
    if not root.exists():
        print(f"workspace root not found: {root}", file=sys.stderr)
        return 2

    projects = _find_projects(root, args.project)
    if not projects:
        print(f"no project matched --project {args.project!r} under {root}")
        return 1

    # (workspace, slug, filename, page) work list.
    pages: list[tuple[Path, str, str, int]] = []
    for workspace, slug in projects:
        for filename, pc in _docs_of(workspace, slug, args.doc):
            for p in range(1, max(pc, 1) + 1):
                pages.append((workspace, slug, filename, p))

    print(f"workspace: {root}")
    print(f"projects={len(projects)} pages={len(pages)} "
          f"mode={'fitz-only' if args.skip_ocr else 'fitz+ocr'} conc={args.concurrency} "
          f"limit={args.limit or 'all'} sleep={args.sleep}s "
          f"ocr_model={args.model or '(default flash-lite)'}")
    for _ws, slug in projects:
        print(f"  - {slug}")
    print(flush=True)
    if args.dry_run:
        return 0

    tally: dict[str, int] = {}
    sem = asyncio.Semaphore(max(1, args.concurrency))
    bookkeep = asyncio.Lock()
    state = {"ocred": 0, "stop": False}

    async def _run(ws: Path, slug: str, fn: str, page: int) -> None:
        async with sem:
            if state["stop"]:
                return
            status = await _warm_page(
                ws, slug, fn, page, skip_ocr_only=args.skip_ocr, retries=args.retries,
                ocr_model=args.model, force=args.force,
            )
            if status in ("ocr", "ocr_empty") and args.sleep:
                await asyncio.sleep(args.sleep)
        async with bookkeep:
            tally[status] = tally.get(status, 0) + 1
            done = sum(tally.values())
            if done % 50 == 0:
                print(f"  … {done}/{len(pages)}  " + " ".join(f"{k}={v}" for k, v in sorted(tally.items())), flush=True)
            if status in ("ocr", "ocr_empty"):
                state["ocred"] += 1
                if args.limit and state["ocred"] >= args.limit:
                    state["stop"] = True

    await asyncio.gather(*(_run(ws, slug, fn, p) for ws, slug, fn, p in pages))
    if state["stop"]:
        print(f"\n[limit] reached --limit {args.limit} OCR'd pages; stopped (re-run to continue)", flush=True)

    print("\ndone: " + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    print("  (fitz=electronic warmed · ocr=scanned OCR'd · cached=already had spans · "
          "deferred=scanned skipped in --skip-ocr · ocr_empty/fail=needs another pass)")
    return 1 if tally.get("fail") else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
