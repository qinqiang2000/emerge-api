"""Field-level grounding audit — companion to backfill_grounding.py.

The backfill `grounded` counter only counts blobs whose `_evidence` was written
back; it does NOT prove the fields inside carry real page/source values. A scanned
or classification-only doc can ground to an all-null evidence array and still count
as "done". This audit opens every blob and classifies the actual evidence quality,
so "已处理" can be verified rather than trusted:

  none    — no `_evidence` key at all (truly unprocessed)
  zero    — has `_evidence` list but 0 fields carry page/source (grounded-to-empty;
            usually correct for docType-only / `docType:"other"` non-target docs)
  partial — some fields grounded, some null
  full    — every field carries page or source

Read-only, never writes. Prints global + per-project tallies and samples the
suspicious `zero`/`none` blobs. Run it after any backfill to confirm the real
field-level coverage.

    cd backend && uv run python scripts/verify_grounding.py
    cd backend && uv run python scripts/verify_grounding.py --root /path/to/workspace
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.config import get_settings  # noqa: E402

KIND_PATTERNS = {
    "_draft": "predictions/_draft/*.json",
    "_pending": "predictions/_pending/*.json",
    "reviewed": "reviewed/*.json",
    "experiment": "experiments/*/predictions/*.json",
}
SKIP_DIRS = {"_trash", ".cache", "_staging", ".git", "__pycache__"}


def field_stats(blob: dict) -> tuple[int, int, bool]:
    """(grounded_fields, total_fields, has_evidence_key). A field is grounded if
    its evidence dict carries a non-null page or a truthy source."""
    ev = blob.get("_evidence")
    if not isinstance(ev, list) or not ev:
        return 0, 0, isinstance(ev, list)
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
    return grounded, total, True


def classify(blob: dict) -> str:
    entities = blob.get("entities") or []
    if not entities:
        return "noent"  # nothing to ground — not a defect
    g, t, has_key = field_stats(blob)
    if not has_key or t == 0:
        return "none" if not has_key else "zero"
    if g == 0:
        return "zero"
    if g == t:
        return "full"
    return "partial"


def main() -> int:
    ap = argparse.ArgumentParser(description="Field-level grounding audit (read-only)")
    ap.add_argument("--root", type=Path, default=None,
                    help="workspace root (default: settings.workspace_root)")
    args = ap.parse_args()
    root = (args.root or get_settings().workspace_root).resolve()
    if not root.exists():
        print(f"workspace root not found: {root}", file=sys.stderr)
        return 2

    glob_tally: dict[str, int] = defaultdict(int)
    proj_tally: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    field_g = field_t = 0
    zero_samples: list[str] = []
    none_samples: list[str] = []

    for proj in root.glob("**/project.json"):
        pdir = proj.parent
        rel_parts = pdir.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        pname = "/".join(rel_parts)
        for kind, pat in KIND_PATTERNS.items():
            for p in pdir.glob(pat):
                try:
                    blob = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    glob_tally["unreadable"] += 1
                    continue
                cls = classify(blob)
                glob_tally[cls] += 1
                proj_tally[pname][cls] += 1
                if blob.get("entities"):
                    g, t, _ = field_stats(blob)
                    field_g += g
                    field_t += t
                if cls == "zero" and len(zero_samples) < 25:
                    zero_samples.append(str(p.relative_to(root)))
                if cls == "none" and len(none_samples) < 25:
                    none_samples.append(str(p.relative_to(root)))

    order = ["full", "partial", "zero", "none", "noent", "unreadable"]
    total = sum(glob_tally.values())
    print(f"=== GLOBAL (total blobs scanned: {total}) ===")
    for k in order:
        print(f"  {k:10s} {glob_tally.get(k, 0)}")
    real = glob_tally.get("full", 0) + glob_tally.get("partial", 0)
    print(f"  -> blobs with REAL evidence (full+partial): {real}")
    if field_t:
        print(f"  -> field-level grounded: {field_g}/{field_t} ({100*field_g/field_t:.1f}%)")

    print("\n=== PER PROJECT (full / partial / zero / none / noent) ===")
    for pname in sorted(proj_tally):
        t = proj_tally[pname]
        print(f"  {t.get('full',0):4d} {t.get('partial',0):4d} {t.get('zero',0):4d} "
              f"{t.get('none',0):4d} {t.get('noent',0):4d}  {pname}")

    if zero_samples:
        print(f"\n=== sample ZERO blobs (has _evidence but all-null) [{glob_tally.get('zero',0)} total] ===")
        for s in zero_samples:
            print("  -", s)
    if none_samples:
        print(f"\n=== sample NONE blobs (no _evidence key) [{glob_tally.get('none',0)} total] ===")
        for s in none_samples:
            print("  -", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
