"""One-off: fix migrated experiment labels that use ` · ` where the review tab
strip expects ` × `.

migrate.py wrote experiment meta `label` as `{prompt} · {model}`. The review tab
strip (ExperimentTabStrip.tsx) treats label as `{prompt} × {model}` and strips
the ` × {model}` suffix to recover the prompt line; with ` · ` it can't, so the
model id leaks into the prompt line AND the tooltip — the model shows up twice
(see the 曹燕 project tab). emerge-native experiments already use ` × `
(experiment.py). This rewrites the trailing ` · {provider_model_id}` to
` × {provider_model_id}`, preserving all information (only the separator changes).

Idempotent: a label already containing ` × ` is left untouched. Pure local file
rewrite, no LLM / provider I/O.

    cd backend && uv run python scripts/fix_migrated_experiment_label.py --dry-run
    cd backend && uv run python scripts/fix_migrated_experiment_label.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

_BACKEND = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND / ".env")
sys.path.insert(0, str(_BACKEND))

from app.config import get_settings  # noqa: E402
from app.workspace.atomic import atomic_write_json  # noqa: E402

_SKIP_DIRS = {"_trash", ".cache", "_staging", ".git", "__pycache__"}


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _fixed_label(label: str, model_short: str | None) -> str | None:
    """New label if it needs the ` · `→` × ` rewrite, else None (leave as-is).

    Prefer an exact ` · {model_short}` suffix match (precise); fall back to
    rewriting the last ` · ` so a label whose model config is missing still gets
    fixed. Returns None when already ` × ` (native/fixed) or has no ` · `.
    """
    if " × " in label:
        return None
    if model_short and label.endswith(" · " + model_short):
        return label[: -len(" · " + model_short)] + " × " + model_short
    if " · " in label:
        head, _, tail = label.rpartition(" · ")
        return head + " × " + tail
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Fix migrated experiment labels (` · `→` × `)")
    ap.add_argument("--root", type=Path, default=None, help="workspace root (default: settings.workspace_root)")
    ap.add_argument("--dry-run", action="store_true", help="report what would change; no writes")
    args = ap.parse_args()

    root = (args.root or get_settings().workspace_root).resolve()
    if not root.exists():
        print(f"workspace root not found: {root}", file=sys.stderr)
        return 2

    metas = [
        m for m in root.glob("**/experiments/*/meta.json")
        if not any(part in _SKIP_DIRS for part in m.relative_to(root).parts)
    ]
    metas.sort(key=lambda p: str(p))

    print(f"workspace: {root}")
    print(f"found {len(metas)} experiment meta(s){' [DRY RUN]' if args.dry_run else ''}\n", flush=True)

    fixed = skipped = failed = 0
    for meta_path in metas:
        meta = _read_json(meta_path)
        if meta is None:
            failed += 1
            print(f"  FAIL  {meta_path.relative_to(root)} (unreadable)", flush=True)
            continue
        label = meta.get("label") or ""
        # model_short for a precise suffix match: read this experiment's model config.
        model_short = None
        mid = meta.get("model_id")
        if mid:
            pdir = meta_path.parent.parent.parent  # experiments/<ex>/meta.json → project dir
            mc = _read_json(pdir / "models" / f"{mid}.json") or {}
            model_short = mc.get("provider_model_id")
        new_label = _fixed_label(label, model_short)
        if new_label is None:
            skipped += 1
            continue
        rel = meta_path.relative_to(root)
        print(f"  {'WOULD' if args.dry_run else 'fix  '} {rel}\n        {label!r}\n     →  {new_label!r}", flush=True)
        if not args.dry_run:
            meta["label"] = new_label
            atomic_write_json(meta_path, meta)
        fixed += 1

    verb = "would fix" if args.dry_run else "fixed"
    print(f"\ndone: {verb}={fixed} skipped(already ` × `/no separator)={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
