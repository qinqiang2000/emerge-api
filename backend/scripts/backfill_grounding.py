"""One-off backfill: stamp `_evidence` onto predictions that lack it.

Blobs migrated from label-studio carry only `entities` (the corrected values) —
no `_evidence`, so the review locate cascade degrades to value-only matching and
most fields fail to highlight (see app/tools/locate.py: without a page hint, only
distinctive long strings are searched). This script re-runs the existing
grounding pass (app/tools/ground.py::ground_entities) over each ungrounded blob,
recovering per-field {page, source} anchors and writing them back. The
human-corrected values are left untouched (only `_evidence` is added).

Covers EVERY blob the review viewer can locate against (ReviewOverlay reads
`_evidence` off whichever tab is shown):
  • predictions/_draft/*.json        — the baseline draft tab
  • predictions/_pending/*.json      — the pre-label tab
  • reviewed/*.json                  — human ground-truth (the 'active' tab)
  • experiments/*/predictions/*.json — experiment comparison tabs

Grounding uses the project's active model (read from project.json). It is
value→{page,source} location, model-agnostic enough that the active flash model
grounds an experiment run faithfully.

Resilient + resumable (built for a few-thousand-blob prod run where transient
provider errors are expected):
  • each blob is grounded + persisted independently → a crash loses at most the
    in-flight blob;
  • idempotent — a blob that already has evidence is skipped (no LLM call), so a
    re-run resumes where the last stopped and retries every failure;
  • per-blob retry with exponential backoff rides out rate limits / blips;
  • newest-doc-first by default; `--limit` batches ("慢慢做"); `--sleep` paces.

    cd backend && uv run python scripts/backfill_grounding.py --dry-run
    cd backend && uv run python scripts/backfill_grounding.py            # all kinds, newest first
    cd backend && uv run python scripts/backfill_grounding.py --kind reviewed experiment
    cd backend && uv run python scripts/backfill_grounding.py --exclude 勿动 --exclude 暂不处理 --sleep 0.5

Re-run after any run to retry whatever still failed — it only touches ungrounded
blobs. Provider keys come from backend/.env (loaded below, same as app/main.py)."""
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

from app.tools.ground import ground_entities, has_evidence  # noqa: E402
from app.tools.model import read_active_model  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.provider import get_provider_for_model  # noqa: E402
from app.workspace.atomic import atomic_write_json  # noqa: E402
from app.workspace.lock import project_lock  # noqa: E402
from app.workspace.paths import doc_path  # noqa: E402

# glob patterns (relative to a project dir) for every blob the review viewer can
# locate against, paired with a short kind label for --kind filtering / logging.
_KIND_PATTERNS = {
    "_draft": "predictions/_draft/*.json",
    "_pending": "predictions/_pending/*.json",
    "reviewed": "reviewed/*.json",
    "experiment": "experiments/*/predictions/*.json",
}
_SKIP_DIRS = {"_trash", ".cache", "_staging", ".git", "__pycache__"}


def _resolve(blob_path: Path) -> tuple[Path, str, str]:
    """(workspace, slug, filename) for a blob, by walking up to the project dir.

    The project dir is the nearest ancestor holding a `project.json` — robust to
    the differing blob depths (`<slug>/reviewed/x.json` vs
    `<slug>/experiments/<ex>/predictions/x.json`). workspace = its parent (the
    team dir or flat root); filename = the blob name minus `.json` (== doc name).
    """
    d = blob_path.parent
    while d != d.parent:
        if (d / "project.json").exists():
            return d.parent, d.name, blob_path.name[: -len(".json")]
        d = d.parent
    raise ValueError(f"no project.json above {blob_path}")


def _find_blobs(root: Path, kinds: list[str], exclude: list[str]) -> list[tuple[Path, str]]:
    """All (blob_path, kind) under root for the requested kinds, minus excludes."""
    out: list[tuple[Path, str]] = []
    for proj in root.glob("**/project.json"):
        pdir = proj.parent
        if any(part in _SKIP_DIRS for part in pdir.relative_to(root).parts):
            continue
        rel_proj = str(pdir.relative_to(root))
        if any(ex and ex in rel_proj for ex in exclude):
            continue
        for kind in kinds:
            for p in pdir.glob(_KIND_PATTERNS[kind]):
                if any(part in _SKIP_DIRS for part in p.parts):
                    continue
                out.append((p, kind))
    return out


def _sort_key_newest(item: tuple[Path, str]) -> float:
    """Recency = source doc mtime (fallback: blob mtime). Newest-first surfaces
    the docs users are most likely to reopen."""
    blob_path = item[0]
    try:
        ws, slug, fn = _resolve(blob_path)
        return doc_path(ws, slug, fn).stat().st_mtime
    except Exception:
        try:
            return blob_path.stat().st_mtime
        except Exception:
            return 0.0


# (workspace, slug) → (provider, provider_model_id), so we read each project's
# active-model config once, not once per blob.
_model_cache: dict[tuple[str, str], tuple[object, str]] = {}


async def _resolve_model(workspace: Path, slug: str):
    key = (str(workspace), slug)
    if key not in _model_cache:
        mc = await read_active_model(workspace, slug)
        mid = mc.provider_model_id
        provider = get_provider_for_model(mid, provider=mc.provider)
        _model_cache[key] = (provider, mid)
    return _model_cache[key]


async def _ground_and_write(blob_path: Path, entities: list[dict], *, retries: int) -> list[dict]:
    """Ground `entities` and write `_evidence` back into this exact blob.

    Generic over blob kind (unlike ground.ground_prediction, which only knows the
    _draft/_pending tabs). Retries with exponential backoff; re-reads under the
    project lock before writing so it never clobbers a concurrent save and only
    stamps when the on-disk entity count still matches what we grounded."""
    workspace, slug, filename = _resolve(blob_path)
    provider, mid = await _resolve_model(workspace, slug)

    delay = 1.0
    last: Exception | None = None
    ev: list[dict] | None = None
    for attempt in range(retries + 1):
        try:
            ev = await ground_entities(workspace, slug, filename, entities, provider=provider, model_id=mid)
            break
        except Exception as e:  # noqa: BLE001 - best-effort; every error retried
            last = e
            if attempt < retries:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
    if ev is None:
        raise last if last else RuntimeError("grounding failed with no exception")

    async with project_lock(workspace, slug):
        cur = json.loads(blob_path.read_text(encoding="utf-8"))
        if len(cur.get("entities") or []) == len(entities):
            cur["_evidence"] = ev
            atomic_write_json(blob_path, cur)
    return ev


async def _backfill_one(
    blob_path: Path, kind: str, root: Path, *, dry_run: bool, retries: int
) -> tuple[str, str]:
    """status ∈ skip|done|empty|fail ; plus the rel path for the failure list."""
    rel = f"[{kind}] {blob_path.relative_to(root)}"
    try:
        blob = json.loads(blob_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  FAIL  {rel}  (unreadable: {e})", flush=True)
        return "fail", rel

    entities = blob.get("entities") or []
    if not entities:
        print(f"  empty {rel}  (no entities)", flush=True)
        return "empty", rel
    if has_evidence(blob):
        print(f"  skip  {rel}  (already grounded)", flush=True)
        return "skip", rel

    if dry_run:
        print(f"  WOULD {rel}  ({len(entities)} entit{'y' if len(entities) == 1 else 'ies'})", flush=True)
        return "done", rel

    try:
        ev = await _ground_and_write(blob_path, entities, retries=retries)
        grounded = sum(
            1
            for entry in (ev or [])
            if isinstance(entry, dict)
            and any(
                isinstance(v, dict) and (v.get("page") is not None or v.get("source"))
                for v in entry.values()
            )
        )
        print(f"  ok    {rel}  ({grounded}/{len(ev or [])} entities grounded)", flush=True)
        return "done", rel
    except Exception as e:
        print(f"  FAIL  {rel}  ({type(e).__name__}: {e})", flush=True)
        return "fail", rel


async def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill _evidence onto ungrounded blobs")
    ap.add_argument("--root", type=Path, default=None, help="workspace root (default: settings.workspace_root)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be grounded; no LLM calls")
    ap.add_argument("--kind", nargs="+", choices=list(_KIND_PATTERNS), default=list(_KIND_PATTERNS),
                    help="which blob kinds to backfill (default: all)")
    ap.add_argument("--exclude", action="append", default=[], metavar="SUBSTR",
                    help="skip projects whose path contains SUBSTR (repeatable)")
    ap.add_argument("--order", choices=["newest", "oldest", "path"], default="newest",
                    help="processing order by source-doc mtime (default: newest first)")
    ap.add_argument("--limit", type=int, default=0, help="ground at most N blobs this run (0 = all)")
    ap.add_argument("--concurrency", type=int, default=1, help="parallel grounding calls (default 1; prod: 6-8)")
    ap.add_argument("--retries", type=int, default=4, help="per-blob retry attempts on transient errors")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds to pause after each grounded blob (pacing)")
    args = ap.parse_args()

    root = (args.root or get_settings().workspace_root).resolve()
    if not root.exists():
        print(f"workspace root not found: {root}", file=sys.stderr)
        return 2

    blobs = _find_blobs(root, args.kind, args.exclude)
    if args.order == "path":
        blobs.sort(key=lambda it: str(it[0]))
    else:
        blobs.sort(key=_sort_key_newest, reverse=(args.order == "newest"))

    print(f"workspace: {root}")
    print(f"found {len(blobs)} blob(s) across kinds={args.kind}; order={args.order} "
          f"conc={args.concurrency} limit={args.limit or 'all'} retries={args.retries} sleep={args.sleep}s")
    if args.exclude:
        print(f"excluding: {args.exclude}")
    print(flush=True)

    # Grounding is independent per-blob provider I/O (each call ships the whole
    # doc, ~5-20s), so a bounded semaphore overlaps them — the dominant speedup on
    # a few-thousand-blob run. The slow grounding happens OUTSIDE the project lock
    # (only the tiny write-back takes it), so same-project concurrency is safe.
    tally = {"skip": 0, "done": 0, "empty": 0, "fail": 0}
    failures: list[str] = []
    sem = asyncio.Semaphore(max(1, args.concurrency))
    bookkeep = asyncio.Lock()
    state = {"processed": 0, "stop": False}

    async def _run_one(bp: Path, kind: str) -> None:
        async with sem:
            if state["stop"]:  # --limit budget spent → skip remaining grounding
                return
            status, rel = await _backfill_one(bp, kind, root, dry_run=args.dry_run, retries=args.retries)
            if args.sleep:
                await asyncio.sleep(args.sleep)
        async with bookkeep:
            tally[status] += 1
            if status == "fail":
                failures.append(rel)
            if status == "done" and not args.dry_run:
                state["processed"] += 1
                if args.limit and state["processed"] >= args.limit:
                    state["stop"] = True

    await asyncio.gather(*(_run_one(bp, kind) for bp, kind in blobs))
    if state["stop"]:
        print(f"\n[limit] reached --limit {args.limit}; stopped (re-run to continue)", flush=True)

    print(
        f"\ndone: grounded={tally['done']} skipped={tally['skip']} "
        f"empty={tally['empty']} failed={tally['fail']}"
    )
    if failures:
        print(f"\n{len(failures)} failed (re-run the script to retry just these):")
        for f in failures:
            print(f"  - {f}")
    return 1 if tally["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
