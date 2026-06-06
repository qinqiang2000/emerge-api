"""Per-doc pipeline audit — why a doc shows "完全没定位" / "还要实时翻译".

`verify_grounding.py` only audits `_evidence` (the grounding TEXT). But a doc can
have full evidence and STILL highlight nothing: locate aligns the model's source
quote against the **text-layer spans**, and for a scanned doc those spans come
from Gemini OCR (`app/tools/textlayer.py`). No OCR spans → nothing to align → every
field resolves to `none` → "完全没定位". The same OCR/translate warm gap also leaves
the translation sidecar empty → the viewer re-runs translation live every open
("还要实时翻译"). This script adds those two missing dimensions, per doc:

  textlayer  — for each page, is there a `.cache/_textlayer/{sha}/p{n}.json`
               sidecar, what `text_source` (fitz / ocr / fitz+ocr / none), how many
               spans. A scanned doc with 0 spans is UNLOCATABLE.
  translate  — is there any `.cache/_translate/{sha}/` sidecar (warmed) or not.
  evidence   — classify the reviewed (else _draft) blob: full / partial / zero / none.

Per-doc verdict:
  OK            — has spans AND real evidence → locate should work.
  NO-TEXTLAYER  — no textlayer sidecar at all (OCR warm never ran for this doc).
  EMPTY-OCR     — sidecars exist but 0 spans on every page (OCR ran, returned nothing
                  / failed → cached empty). UNLOCATABLE until re-OCR'd.
  UNGROUNDED    — has spans but no/zero evidence (grounding backfill missed it).
  NO-REVIEWED   — no reviewed blob (only draft / pending), reported for context.

Read-only. Never writes. Self-contained — no app imports, so it runs with a bare
`python3` on the prod host without `uv`/venv.

    python3 scripts/diagnose_doc_pipeline.py --project 海信日本
    python3 scripts/diagnose_doc_pipeline.py --project 海信日本 --doc 000003384581
    python3 scripts/diagnose_doc_pipeline.py --root /root/emerge/backend/workspace --project 海信日本 --verbose
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Default to the prod layout; override with --root for local runs.
_DEFAULT_ROOT = Path("/root/emerge/backend/workspace")
_SKIP_DIRS = {"_trash", ".cache", "_staging", ".git", "__pycache__", "_auth", "_published"}


def _classify_evidence(blob: dict) -> str:
    """full / partial / zero / none — mirrors verify_grounding.field_stats."""
    ev = blob.get("_evidence")
    if not isinstance(ev, list) or not ev:
        return "none" if not isinstance(ev, list) else "zero"
    grounded = total = 0
    for entry in ev:
        if not isinstance(entry, dict):
            continue
        for v in entry.values():
            if isinstance(v, dict):
                total += 1
                if v.get("page") is not None or v.get("source"):
                    grounded += 1
            elif isinstance(v, int) and not isinstance(v, bool):
                total += 1
                grounded += 1
    if total == 0:
        return "zero"
    if grounded == 0:
        return "zero"
    return "full" if grounded == total else "partial"


def _doc_meta(pdir: Path, doc_filename: str) -> dict | None:
    meta_p = pdir / "docs" / ".meta" / f"{doc_filename}.json"
    if not meta_p.exists():
        return None
    try:
        return json.loads(meta_p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _textlayer_stats(cache_root: Path, sha: str, page_count: int) -> dict:
    """Per-doc textlayer survey across all pages."""
    tdir = cache_root / "_textlayer" / sha
    pages_present = 0
    total_spans = 0
    sources: dict[str, int] = {}
    scanned_any = False
    for p in range(1, max(page_count, 1) + 1):
        side = tdir / f"p{p}.json"
        if not side.exists():
            continue
        try:
            d = json.loads(side.read_text(encoding="utf-8"))
        except Exception:
            continue
        pages_present += 1
        n = len(d.get("spans", []) or [])
        total_spans += n
        src = str(d.get("text_source", "?"))
        sources[src] = sources.get(src, 0) + 1
        if d.get("scanned"):
            scanned_any = True
    return {
        "pages_present": pages_present,
        "total_spans": total_spans,
        "sources": sources,
        "scanned_any": scanned_any,
        "dir_exists": tdir.exists(),
    }


def _translate_present(cache_root: Path, sha: str) -> int:
    tdir = cache_root / "_translate" / sha
    if not tdir.exists():
        return 0
    return sum(1 for _ in tdir.glob("*.json"))


def _verdict(tl: dict, ev: str, page_count: int) -> str:
    if not tl["dir_exists"] or tl["pages_present"] == 0:
        return "NO-TEXTLAYER"
    if tl["total_spans"] == 0:
        return "EMPTY-OCR"
    if ev in ("none", "zero"):
        return "UNGROUNDED"
    return "OK"


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-doc pipeline audit (read-only)")
    ap.add_argument("--root", type=Path, default=_DEFAULT_ROOT,
                    help=f"workspace root (default: {_DEFAULT_ROOT})")
    ap.add_argument("--project", default="", metavar="SUBSTR",
                    help="only projects whose path contains SUBSTR")
    ap.add_argument("--doc", default="", metavar="SUBSTR",
                    help="only docs whose filename contains SUBSTR")
    ap.add_argument("--verbose", action="store_true",
                    help="print every doc (default: only non-OK docs + summary)")
    ap.add_argument("--limit", type=int, default=0, help="cap docs printed per project (0=all)")
    args = ap.parse_args()

    root = args.root.resolve()
    if not root.exists():
        print(f"workspace root not found: {root}", file=sys.stderr)
        return 2

    projects = []
    for proj in root.glob("**/project.json"):
        pdir = proj.parent
        rel = pdir.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if args.project and args.project not in str(rel):
            continue
        projects.append(pdir)
    projects.sort()

    if not projects:
        print(f"no project matched --project {args.project!r} under {root}")
        return 1

    for pdir in projects:
        cache_root = pdir.parent / ".cache"
        rel = pdir.relative_to(root)
        meta_dir = pdir / "docs" / ".meta"
        doc_metas = sorted(meta_dir.glob("*.pdf.json")) + sorted(meta_dir.glob("*.png.json")) \
            + sorted(meta_dir.glob("*.jpg.json")) + sorted(meta_dir.glob("*.jpeg.json"))

        tally: dict[str, int] = {}
        rows: list[tuple] = []
        printed = 0
        for mp in doc_metas:
            doc_filename = mp.name[: -len(".json")]
            if args.doc and args.doc not in doc_filename:
                continue
            meta = _doc_meta(pdir, doc_filename)
            if not meta:
                continue
            sha = str(meta.get("sha256", ""))
            page_count = int(meta.get("page_count", 1) or 1)
            if not sha:
                continue

            tl = _textlayer_stats(cache_root, sha, page_count)
            n_tr = _translate_present(cache_root, sha)

            rv = pdir / "reviewed" / f"{doc_filename}.json"
            dr = pdir / "predictions" / "_draft" / f"{doc_filename}.json"
            blob_p = rv if rv.exists() else (dr if dr.exists() else None)
            if blob_p is None:
                ev = "no-blob"
                verdict = "NO-REVIEWED"
            else:
                try:
                    blob = json.loads(blob_p.read_text(encoding="utf-8"))
                    ev = _classify_evidence(blob)
                except Exception:
                    ev = "unreadable"
                    blob = {}
                verdict = _verdict(tl, ev, page_count)

            tally[verdict] = tally.get(verdict, 0) + 1
            rows.append((verdict, doc_filename, page_count, tl, ev, n_tr))

        print(f"\n=== {rel}  ({len(rows)} docs) ===")
        order = ["NO-TEXTLAYER", "EMPTY-OCR", "UNGROUNDED", "NO-REVIEWED", "OK"]
        print("  verdict     " + "  ".join(f"{k}={tally.get(k,0)}" for k in order if tally.get(k)))

        for verdict, fn, pc, tl, ev, n_tr in rows:
            if not args.verbose and verdict == "OK":
                continue
            if args.limit and printed >= args.limit:
                print(f"  … (--limit {args.limit} reached)")
                break
            printed += 1
            src = ",".join(f"{k}:{v}" for k, v in tl["sources"].items()) or "-"
            print(f"  [{verdict:12s}] {fn}  pages={pc} "
                  f"tl_pages={tl['pages_present']}/{pc} spans={tl['total_spans']} "
                  f"src=({src}) scanned={tl['scanned_any']} ev={ev} translate_sidecars={n_tr}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
