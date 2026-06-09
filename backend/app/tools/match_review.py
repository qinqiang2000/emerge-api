"""Match review + scoring — the ground-truth + eval half of the match loop.

`save_reviewed_match` records a human-confirmed reconcile card for one anchor
doc: which source doc (or none) is the TRUE pair in each source. That ground
truth lands in `reviewed_matches/{anchor_doc}.json`.

`score_match` re-runs the match, then compares the predicted pairs against the
reviewed truth to produce **per-source precision/recall** + **doc completeness**
(fraction of reviewed anchors whose full pairing the engine got exactly right).
Structurally the twin of `app/eval` — judged pairs aggregated into metrics — but
the unit is a (anchor, source_doc) relation rather than a field value.

Ground-truth shape (`reviewed_matches/{anchor_doc}.json`):
    {
      "anchor_doc": "inv_001.jpg",
      "expected": {"payment_x": "pay_A.jpg", "po_x": null},  # null = correctly unpaired
      "reviewed_at": "..."
    }
Only anchors with a reviewed file participate in scoring; precision is measured
over reviewed anchors only so unreviewed docs never count as false positives.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.tools.match_project import read_match_project
from app.tools.match_run import run_match
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    match_result_path,
    reviewed_match_path,
    reviewed_matches_dir,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def save_reviewed_match(
    workspace: Path,
    slug: str,
    *,
    anchor_doc: str,
    expected: dict[str, Optional[str]],
    reason: str = "",  # accepted for tool symmetry / audit; not persisted
) -> dict[str, Any]:
    """Record the human-verified pairing for one anchor doc.

    `expected` maps each source project slug → the source filename that truly
    pairs with this anchor, or `null` when the anchor correctly has no match in
    that source (e.g. an unpaid invoice). Validates the project is a match
    project; tolerates `expected` keys being a subset of the source projects
    (un-listed sources are treated as `null` at score time).
    """
    project = await read_match_project(workspace, slug)  # raises if not a match project
    valid_sources = set(project["source_projects"])
    bad = [s for s in expected if s not in valid_sources]
    if bad:
        from app.tools.match_project import MatchProjectError

        raise MatchProjectError(
            "match_unknown_source",
            f"expected references unknown source project(s): {', '.join(bad)}",
        )

    reviewed_matches_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    blob = {
        "anchor_doc": anchor_doc,
        "expected": {k: v for k, v in expected.items()},
        "reviewed_at": _now_iso(),
    }
    atomic_write_json(reviewed_match_path(workspace, slug, anchor_doc), blob)
    return {"anchor_doc": anchor_doc, "sources_confirmed": len(expected)}


def _load_reviewed(workspace: Path, slug: str) -> dict[str, dict[str, Optional[str]]]:
    """Return {anchor_doc: {source_slug: expected_doc_or_None}} from disk."""
    out: dict[str, dict[str, Optional[str]]] = {}
    rd = reviewed_matches_dir(workspace, slug)
    if not rd.exists():
        return out
    for p in sorted(rd.glob("*.json")):
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        anchor = blob.get("anchor_doc")
        exp = blob.get("expected")
        if isinstance(anchor, str) and isinstance(exp, dict):
            out[anchor] = exp
    return out


def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4),
            "tp": tp, "fp": fp, "fn": fn}


async def score_match(
    workspace: Path,
    slug: str,
    *,
    provider=None,
    model_id: Optional[str] = None,
) -> dict[str, Any]:
    """Run the match, then score predicted pairs against `reviewed_matches/`.

    Per source: TP/FP/FN over (anchor, source_doc) relations, restricted to
    reviewed anchors so unreviewed docs are never false positives. `precision`
    and `recall` per source; `doc_completeness` = fraction of reviewed anchors
    whose entire pairing (across all sources) the engine got exactly right.
    Returns 0-metrics with `reviewed=0` when no ground truth exists yet.
    """
    project = await read_match_project(workspace, slug)
    sources: list[str] = project["source_projects"]
    reviewed = _load_reviewed(workspace, slug)

    summary = await run_match(workspace, slug, provider=provider, model_id=model_id)
    result = json.loads(
        match_result_path(workspace, slug, summary["run_id"]).read_text(encoding="utf-8")
    )
    # predicted[anchor_doc][source_slug] = matched source filename (or None)
    predicted: dict[str, dict[str, Optional[str]]] = {}
    for card in result.get("cards", []):
        a = card.get("anchor_doc")
        pm: dict[str, Optional[str]] = {}
        for pair in card.get("pairs", []):
            src = pair.get("source")
            pm[src] = pair.get("doc") if pair.get("status") == "match" else None
        predicted[a] = pm

    if not reviewed:
        return {
            "run_id": summary["run_id"],
            "reviewed": 0,
            "per_source": {s: _prf(0, 0, 0) for s in sources},
            "doc_completeness": 0.0,
        }

    per_source: dict[str, dict[str, float]] = {}
    for src in sources:
        tp = fp = fn = 0
        for anchor, exp in reviewed.items():
            truth = exp.get(src)  # None if unpaired / unlisted
            pred = predicted.get(anchor, {}).get(src)
            if truth is not None and pred == truth:
                tp += 1
            elif truth is not None and pred != truth:
                fn += 1  # missed (or mismatched) the true pair
                if pred is not None:
                    fp += 1  # …and asserted a wrong one
            elif truth is None and pred is not None:
                fp += 1  # asserted a pair where truth says none
        per_source[src] = _prf(tp, fp, fn)

    exact = 0
    for anchor, exp in reviewed.items():
        pm = predicted.get(anchor, {})
        if all(pm.get(src) == exp.get(src) for src in sources):
            exact += 1
    doc_completeness = round(exact / len(reviewed), 4) if reviewed else 0.0

    return {
        "run_id": summary["run_id"],
        "reviewed": len(reviewed),
        "per_source": per_source,
        "doc_completeness": doc_completeness,
    }
