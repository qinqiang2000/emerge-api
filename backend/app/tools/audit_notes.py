"""Board doodle → agent-readable text (D2, 2026-06-12 doodle plan).

The user circles / scribbles / writes on the audit board; the frontend saves
each user element with an anchor `{doc, page, rect}` in SOURCE page units to
`audits/{run}/board_notes.json` (render-layer persistence, see
routes/audit_board.py). `digest_board_annotations` turns those anchors into
pure text so the agent colleague can act on the feedback.

RED LINE (no bbox into prompts / tool results): rects live only inside this
function's memory — anchored regions are resolved against the warm textlayer
sidecar (span bbox CENTER ∈ rect) and exit as `region_text`. The returned
entries are `{doc, page, kind, user_text?, region_text?}` — never a rect,
never a coordinate.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.tools.textlayer import extract_textlayer
from app.workspace.paths import audits_dir

# region_text budget per annotation — the digest is a pointer ("the user
# circled THIS"), not a transcript; 200 chars is plenty to identify the spot.
_MAX_REGION_CHARS = 200


async def digest_board_annotations(
    workspace: Path, slug: str, run_id: str,
) -> list[dict]:
    """Pure-text digest of the user's board annotations for one audit run.

    Reads `audits/{run_id}/board_notes.json`; missing file / pre-D1 format
    (no `annotations` key) / empty list → `[]`, never an error. Each entry:

    - anchored (doc+page+rect all present) → the warm sidecar's spans whose
      bbox center falls inside the rect are joined in reading order as
      `region_text` (≤200 chars, truncated with `…`). Cold sidecar / no span
      hit → `region_text` simply omitted, never a hard failure (skip_ocr —
      the digest never spends OCR budget, same stance as locate).
    - `kind == "text"` elements carry the user's words as `user_text`.
    - anchorless (drawn on blank board space) → `{doc: None, page: None,
      kind, …}`; kept even when bare — N strokes on the board IS a signal.
    """
    notes_path = audits_dir(workspace, slug) / run_id / "board_notes.json"
    if not notes_path.is_file():
        return []
    try:
        blob = json.loads(notes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = blob.get("annotations") if isinstance(blob, dict) else None
    if not isinstance(raw, list):
        return []

    out: list[dict] = []
    # (doc, page) → spans; one sidecar read per page however many circles hit it.
    span_cache: dict[tuple[str, int], list[dict]] = {}
    for ann in raw:
        if not isinstance(ann, dict):
            continue
        kind = str(ann.get("kind") or "draw")
        doc = ann.get("doc")
        page = ann.get("page")
        rect = ann.get("rect")
        anchored = (
            isinstance(doc, str) and doc
            and isinstance(page, int) and page >= 1
            and isinstance(rect, list) and len(rect) == 4
        )
        entry: dict = {
            "doc": doc if anchored else None,
            "page": page if anchored else None,
            "kind": kind,
        }
        text = ann.get("text")
        if kind == "text" and isinstance(text, str) and text.strip():
            entry["user_text"] = text.strip()
        if anchored:
            region = _region_text(
                await _spans_cached(workspace, slug, doc, page, span_cache),
                [float(v) for v in rect],
            )
            if region:
                entry["region_text"] = region
        out.append(entry)
    return out


async def _spans_cached(
    workspace: Path,
    slug: str,
    doc: str,
    page: int,
    cache: dict[tuple[str, int], list[dict]],
) -> list[dict]:
    """Warm-sidecar spans for one page, memoized; any failure → [] (the
    annotation still surfaces, just without region_text)."""
    key = (doc, page)
    if key not in cache:
        try:
            tl = await extract_textlayer(workspace, slug, doc, page=page, skip_ocr=True)
            cache[key] = tl.get("spans", []) or []
        except Exception:
            cache[key] = []
    return cache[key]


def _region_text(spans: list[dict], rect: list[float]) -> str:
    """Join (in reading order) the spans whose bbox CENTER lies inside rect.

    Center-containment matches how a human circles things — a stroke that
    clips a span's edge doesn't claim it. Output is text only; the rect dies
    here.
    """
    x0, y0, x1, y1 = (
        min(rect[0], rect[2]), min(rect[1], rect[3]),
        max(rect[0], rect[2]), max(rect[1], rect[3]),
    )
    hits: list[tuple[float, float, str]] = []
    for sp in spans:
        bbox = sp.get("bbox")
        text = sp.get("text", "")
        if not (isinstance(bbox, list) and len(bbox) == 4 and isinstance(text, str)):
            continue
        if not text.strip():
            continue
        cx = (float(bbox[0]) + float(bbox[2])) / 2.0
        cy = (float(bbox[1]) + float(bbox[3])) / 2.0
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            hits.append((cy, cx, text.strip()))
    hits.sort(key=lambda t: (t[0], t[1]))
    joined = " ".join(t[2] for t in hits)
    if len(joined) > _MAX_REGION_CHARS:
        joined = joined[:_MAX_REGION_CHARS] + "…"
    return joined
