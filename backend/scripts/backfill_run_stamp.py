"""One-off backfill: stamp `_run` onto migrated prediction blobs that lack it.

Blobs migrated from label-studio carry only `entities` — no `_run` envelope
(M14, see app/schemas/run.py). The review tab strip gates each prediction tab on
`_run` (it's where model · prompt identity comes from), AND the whole strip
renders only when at least one baseline / experiment / pending tab exists
(ReviewBar.tsx). Net effect: a migrated project shows NO baseline tab ever, and
docs with no experiment coverage show NO tabs at all — not even the ✏ annotation
tab — though reviewed + draft + experiment blobs are all on disk. Users read
that as "the data is gone". It isn't; the tab strip just has nothing to anchor
on. Reconstructing `_run` brings every tab back.

This rebuilds `_run` purely from already-on-disk config:
  • predictions/_draft/*.json          → baseline   stamp (project active model+prompt)
  • experiments/<ex>/predictions/*.json → experiment stamp (that experiment's model+prompt)
  • predictions/_pending/*.json        → migration never produced these; skipped if absent

It reads the model/prompt JSON as raw dicts and only pulls the identity fields
(`model_id` / `provider_model_id` / `label`, `prompt_id` / `label`) — deliberately
NOT through `read_model` (which full-validates `ModelConfig`). Migrated configs
can carry schema-drifted junk like `provider: "unknown"` or a `model_version`
("0.1") masquerading as a model name; a tab stamp must not choke on that. The
only validation is `RunStamp` itself, which is permissive (everything but
run_id/ts/kind is optional).

No LLM, no provider I/O. Idempotent: a blob that already has `_run` is skipped.
`ts` is derived from the blob's source created_at (project.json / experiment
meta), not wall-clock, so re-runs and cross-machine runs mint identical run_ids
(same spirit as the migration's deterministic ids).

    cd backend && uv run python scripts/backfill_run_stamp.py --dry-run
    cd backend && uv run python scripts/backfill_run_stamp.py            # all projects
    cd backend && uv run python scripts/backfill_run_stamp.py --exclude 勿动

Re-run any time — it only touches blobs still missing `_run`."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_BACKEND = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND / ".env")
sys.path.insert(0, str(_BACKEND))

from app.config import get_settings  # noqa: E402
from app.eval.run_stamp import mint_run_id  # noqa: E402
from app.schemas.run import RunStamp  # noqa: E402
from app.workspace.atomic import atomic_write_json  # noqa: E402

_SKIP_DIRS = {"_trash", ".cache", "_staging", ".git", "__pycache__"}


def _iso_to_runts(iso: str | None) -> str:
    """ISO timestamp → RunStamp.ts format (`%Y-%m-%dT%H-%M-%SZ`).

    Deterministic so repeated/cross-machine backfills mint the same run_id.
    Falls back to now() only when the source created_at is missing/garbage.
    """
    if iso:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _stamp(kind: str, model: dict, prompt: dict, mid: str | None, pid: str | None, ts: str) -> dict:
    """Build a `_run` dict from raw model/prompt config dicts (no ModelConfig
    validation). Falls back to the referencing id when a field is absent so a
    drifted/missing config still yields a usable, identifiable tab."""
    extract_model = model.get("provider_model_id")
    prompt_id = prompt.get("prompt_id") or pid
    return RunStamp(
        run_id=mint_run_id(ts, extract_model, prompt_id),
        ts=ts,
        kind=kind,  # type: ignore[arg-type]
        model_id=model.get("model_id") or mid,
        extract_model=extract_model,
        model_label=model.get("label"),
        prompt_id=prompt_id,
        prompt_label=prompt.get("label"),
    ).model_dump(mode="json", exclude_none=False)


def _apply(blob_path: Path, stamp: dict, *, dry_run: bool) -> str:
    """status ∈ skip|done|fail for one blob (already-stamped → skip)."""
    blob = _read_json(blob_path)
    if blob is None:
        return "fail"
    if blob.get("_run"):
        return "skip"
    if not dry_run:
        blob["_run"] = stamp
        atomic_write_json(blob_path, blob)
    return "done"


def _backfill_project(pdir: Path, *, dry_run: bool, tally: dict, fails: list[str]) -> None:
    """Stamp every draft + experiment-prediction blob in one project dir."""
    slug = pdir.name
    proj = _read_json(pdir / "project.json") or {}

    def bump(status: str, rel: str) -> None:
        tally[status] += 1
        if status == "fail":
            fails.append(rel)

    def load_cfg(kind_dir: str, cfg_id: str | None) -> dict:
        if not cfg_id:
            return {}
        return _read_json(pdir / kind_dir / f"{cfg_id}.json") or {}

    # ── drafts → baseline stamp (project's active model + prompt) ──
    draft_dir = pdir / "predictions" / "_draft"
    drafts = sorted(draft_dir.glob("*.json")) if draft_dir.is_dir() else []
    if drafts:
        mid, pid = proj.get("active_model_id"), proj.get("active_prompt_id")
        stamp = _stamp("baseline", load_cfg("models", mid), load_cfg("prompts", pid),
                       mid, pid, _iso_to_runts(proj.get("created_at")))
        for b in drafts:
            bump(_apply(b, stamp, dry_run=dry_run), f"[_draft] {slug}/{b.name}")

    # ── experiment predictions → experiment stamp (per-experiment model + prompt) ──
    exp_root = pdir / "experiments"
    if exp_root.is_dir():
        for exp_dir in sorted(p for p in exp_root.iterdir() if p.is_dir()):
            pred_dir = exp_dir / "predictions"
            preds = sorted(pred_dir.glob("*.json")) if pred_dir.is_dir() else []
            if not preds:
                continue
            meta = _read_json(exp_dir / "meta.json") or {}
            mid, pid = meta.get("model_id"), meta.get("prompt_id")
            stamp = _stamp("experiment", load_cfg("models", mid), load_cfg("prompts", pid),
                           mid, pid, _iso_to_runts(meta.get("created_at")))
            for b in preds:
                bump(_apply(b, stamp, dry_run=dry_run), f"[exp:{exp_dir.name}] {slug}/{b.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill _run onto migrated prediction blobs")
    ap.add_argument("--root", type=Path, default=None, help="workspace root (default: settings.workspace_root)")
    ap.add_argument("--dry-run", action="store_true", help="report what would be stamped; no writes")
    ap.add_argument("--exclude", action="append", default=[], metavar="SUBSTR",
                    help="skip projects whose path contains SUBSTR (repeatable)")
    args = ap.parse_args()

    root = (args.root or get_settings().workspace_root).resolve()
    if not root.exists():
        print(f"workspace root not found: {root}", file=sys.stderr)
        return 2

    projects = []
    for proj_json in root.glob("**/project.json"):
        pdir = proj_json.parent
        rel = pdir.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if any(ex and ex in str(rel) for ex in args.exclude):
            continue
        projects.append(pdir)
    projects.sort(key=lambda p: str(p))

    print(f"workspace: {root}")
    print(f"found {len(projects)} project(s){' [DRY RUN]' if args.dry_run else ''}")
    if args.exclude:
        print(f"excluding: {args.exclude}")
    print(flush=True)

    tally = {"skip": 0, "done": 0, "fail": 0}
    fails: list[str] = []
    for pdir in projects:
        _backfill_project(pdir, dry_run=args.dry_run, tally=tally, fails=fails)

    verb = "would stamp" if args.dry_run else "stamped"
    print(f"\ndone: {verb}={tally['done']} skipped(already had _run)={tally['skip']} failed={tally['fail']}")
    if fails:
        print(f"\n{len(fails)} blob(s) failed:")
        for f in fails[:50]:
            print(f"  - {f}")
        if len(fails) > 50:
            print(f"  … and {len(fails) - 50} more")
    return 1 if tally["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
