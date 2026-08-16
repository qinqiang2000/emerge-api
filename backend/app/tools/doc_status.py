"""One derivation of "what state is every doc in" — the project's read model.

Before this module the same join lived twice, in different shapes, and only
one of them was reachable by the agent:

* ``GET /lab/projects/{slug}/docs`` (what the UI reads) joined docs against
  ``reviewed/`` + ``predictions/_draft/`` and returned ``has_reviewed`` /
  ``has_prediction`` per doc — the whole table in one call.
* the ``list_docs`` **tool** returned bare sidecars with none of it, and
  ``get_surface_state`` answered the same question for exactly **one** doc.

So the UI knew "which docs still have no prediction" and the agent didn't.
Asked that question on a 50-doc project (prod, 2026-08-14) the agent did the
only thing left to it — nine `Bash` invocations of ``ls | comm`` against
storage layout it has to guess at, racing a second client that was deleting
docs — and still got it wrong.

The rule this module encodes: **a per-item read model with no set projection
is an incomplete read model.** Every question of the form "which docs are
still X" is a projection of this one table, so they cost zero new tools.

Cheap by construction: three directory listings, no per-doc JSON loads. That
also un-does an accidental O(n) payload read on the UI's own listing route,
which used to load every reviewed blob just to learn its filename.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.docs import list_docs
from app.workspace.paths import (
    pending_reviewed_dir,
    predictions_draft_dir,
    reviewed_dir,
)


__all__ = [
    "REVIEW_STATUSES",
    "compact_row",
    "project_doc_status",
    "status_counts",
]


# The doc lifecycle, in order. `pending` here means "a prediction exists,
# nobody has verified it yet" — NOT the Pro-labeler draft (that's the separate
# `has_pending` flag, deliberately orthogonal; see surface_state.py).
REVIEW_STATUSES = ("unprocessed", "pending", "reviewed")

# Fields a compact row keeps. Everything else on the sidecar (`sha256`,
# `page_sizes`, `original_name`, …) is render/storage detail: `page_sizes`
# alone is one [w,h] pair per page, which on a 50-doc project is most of the
# tool result's tokens and none of its meaning.
_COMPACT_FIELDS = ("filename", "ext", "page_count", "uploaded_at")


def _json_stems(d: Path) -> set[str]:
    """Names of ``<doc filename>.json`` files in ``d``, minus the ``.json``.

    Existence is the truth for all three artifact dirs (same rule
    ``get_prediction`` / ``get_reviewed`` apply per doc), so we never open the
    payloads just to learn which docs have one.
    """
    if not d.exists():
        return set()
    return {p.name[: -len(".json")] for p in d.glob("*.json")}


def _review_status(*, has_prediction: bool, has_reviewed: bool) -> str:
    if has_reviewed:
        return "reviewed"
    if has_prediction:
        return "pending"
    return "unprocessed"


async def project_doc_status(
    workspace: Path, slug: str
) -> list[dict[str, Any]]:
    """Every doc in ``slug`` with its artifact flags, sidecar fields included.

    Row = the doc's sidecar plus ``has_prediction`` / ``has_reviewed`` /
    ``has_pending`` / ``review_status``. Doc order is ``list_docs`` order
    (name-sorted), which is also what the spine renders.
    """
    docs = await list_docs(workspace, slug)
    reviewed_names = _json_stems(reviewed_dir(workspace, slug))
    pred_names = _json_stems(predictions_draft_dir(workspace, slug))
    pending_names = _json_stems(pending_reviewed_dir(workspace, slug))

    out: list[dict[str, Any]] = []
    for d in docs:
        fn = d["filename"]
        has_prediction = fn in pred_names
        has_reviewed = fn in reviewed_names
        out.append({
            **d,
            "has_prediction": has_prediction,
            "has_reviewed": has_reviewed,
            "has_pending": fn in pending_names,
            "review_status": _review_status(
                has_prediction=has_prediction, has_reviewed=has_reviewed,
            ),
        })
    return out


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    """Trim a status row to what an agent reading it needs."""
    out = {k: row[k] for k in _COMPACT_FIELDS if k in row}
    out["review_status"] = row["review_status"]
    out["has_prediction"] = row["has_prediction"]
    out["has_reviewed"] = row["has_reviewed"]
    if row.get("has_pending"):
        # Only surfaced when true — it's the rare Pro-labeler draft state, and
        # a False on every row is pure noise.
        out["has_pending"] = True
    return out


def status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """``{total, unprocessed, pending, reviewed}`` over ``rows``.

    Always computed over the FULL set, never the filtered slice — "50 docs, 1
    unprocessed" is the answer to the question, and a caller that filtered to
    ``unprocessed`` still needs the denominator.
    """
    counts = {s: 0 for s in REVIEW_STATUSES}
    for r in rows:
        st = r.get("review_status")
        if st in counts:
            counts[st] += 1
    return {"total": len(rows), **counts}
