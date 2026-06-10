"""Audit review + scoring — the ground-truth + eval half of the audit loop (A2).

`save_reviewed_audit` records the human-confirmed verdict for audit rules: for
each rule (keyed by its exact text), whether the document group TRULY passes or
fails it. That ground truth lands in the single-file `{slug}/reviewed_audit.json`
(one project = one document group, so one truth file).

`score_audit` re-runs the audit with the CURRENT rules, then compares predicted
verdicts against the reviewed truth — accuracy + precision/recall with `fail` as
the positive class (auditing exists to catch violations). Structurally the twin
of `match_review.py::score_match`, with two deliberate differences:

1. **Truth is keyed by rule TEXT, not index.** Rules are a versioned prompt —
   they get added, removed, reworded, reordered. Index alignment would silently
   re-attach old truths to the wrong rules. Text keys mean an edited rule
   automatically sheds its stale truth (its meaning may have changed — it
   SHOULD be re-reviewed) while untouched rules keep theirs across versions.
2. **Truth is only pass|fail — never `unclear`.** `unclear` is a judge
   limitation, not a compliance state; a human reviewer knows the answer. At
   scoring time a judge `unclear` simply isn't correct: on a true `fail` it
   counts as a miss (fn), on a true `pass` it is NOT a false alarm (no fp) —
   it is reported separately via the `unclear` counter.

Ground-truth shape (`{slug}/reviewed_audit.json` — user data, never rmtree'd):
    {
      "expected": {"<rule text>": "pass" | "fail", ...},
      "match_prompt_version": 3,
      "reviewed_at": "..."
    }
Upsert-merge: each save overlays new verdicts onto the existing file, so partial
confirmation is fine — score only counts rules that have a truth.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.tools.audit_run import AuditError, run_audit
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import reviewed_audit_path

_TRUTH_STATUSES = ("pass", "fail")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _current_rules(workspace: Path, slug: str) -> tuple[list[str], int]:
    """(audit_rules, prompt_version) from the active match prompt; AuditError
    when the project has no rules yet (same code as `run_audit`)."""
    from app.tools.match_prompt import MatchPromptNotFoundError, read_active_match_prompt

    try:
        mpv = await read_active_match_prompt(workspace, slug)
        rules = list(mpv.audit_rules)
        version = mpv.version
    except MatchPromptNotFoundError:
        rules, version = [], 0
    if not rules:
        raise AuditError(
            "audit_no_rules", "no audit rules set — call write_audit_rules first",
        )
    return rules, version


def _load_truth(workspace: Path, slug: str) -> dict[str, str]:
    """The persisted {rule text: pass|fail} map, {} when never reviewed."""
    p = reviewed_audit_path(workspace, slug)
    if not p.exists():
        return {}
    try:
        exp = json.loads(p.read_text(encoding="utf-8")).get("expected")
    except (OSError, json.JSONDecodeError):
        return {}
    return exp if isinstance(exp, dict) else {}


async def save_reviewed_audit(
    workspace: Path,
    slug: str,
    *,
    expected: dict[str, str],
    reason: str = "",  # accepted for tool symmetry / audit; not persisted
) -> dict[str, Any]:
    """Record human-confirmed verdicts for audit rules (ground truth).

    `expected` maps a rule's EXACT current text → "pass" | "fail". Keys must
    belong to the active rule set (guards against typos and against verdicts
    written for an outdated rule wording); values must be pass|fail — `unclear`
    is a judge verdict, never a truth. Upsert-merges into the existing
    `reviewed_audit.json`, so confirming only some rules is fine.
    """
    rules, version = await _current_rules(workspace, slug)
    rule_set = set(rules)
    unknown = [k for k in expected if k not in rule_set]
    if unknown:
        raise AuditError(
            "audit_unknown_rule",
            "expected references rule(s) not in the current rule set: "
            + "; ".join(unknown)
            + " — keys must match the active rules' text exactly",
        )
    bad = [k for k, v in expected.items() if v not in _TRUTH_STATUSES]
    if bad:
        raise AuditError(
            "audit_bad_status",
            "truth must be 'pass' or 'fail' (a human review settles 'unclear'); "
            "bad value for rule(s): " + "; ".join(bad),
        )

    merged = _load_truth(workspace, slug)
    merged.update(expected)
    blob = {
        "expected": merged,
        "match_prompt_version": version,
        "reviewed_at": _now_iso(),
    }
    atomic_write_json(reviewed_audit_path(workspace, slug), blob)

    unreviewed = [r for r in rules if r not in merged]
    return {
        "rules_confirmed": sum(1 for r in rules if r in merged),
        "total_rules": len(rules),
        "unreviewed_rules": unreviewed,
    }


async def score_audit(
    workspace: Path,
    slug: str,
    *,
    provider=None,
    model_id: Optional[str] = None,
) -> dict[str, Any]:
    """Re-run the audit with the current rules, then score the verdicts against
    `reviewed_audit.json`.

    `fail` is the positive class: tp = true fail judged fail; fp = true pass
    judged fail; fn = true fail judged pass OR unclear. A judge `unclear` is
    never an fp (it didn't raise a false alarm) but it is never correct either —
    counted separately in `unclear`. Only rules with a confirmed truth in the
    CURRENT rule set participate; the rest land in `unreviewed_rules`. With no
    usable truth at all, returns the 0-metrics envelope WITHOUT calling the
    judge (no wasted provider trip).
    """
    rules, _version = await _current_rules(workspace, slug)
    truth_all = _load_truth(workspace, slug)
    truth = {r: truth_all[r] for r in rules if r in truth_all}
    unreviewed = [r for r in rules if r not in truth]

    if not truth:  # never reviewed, or every truth detached by rule edits
        return {
            "run_id": None,
            "reviewed": 0,
            "accuracy": 0.0,
            "precision": 0.0,
            "recall": 0.0,
            "tp": 0, "fp": 0, "fn": 0,
            "unclear": 0,
            "per_rule": [],
            "unreviewed_rules": unreviewed,
        }

    report = await run_audit(workspace, slug, provider=provider, model_id=model_id)
    predicted = {
        c.get("rule"): c.get("status") for c in report.get("checks", [])
        if isinstance(c, dict)
    }

    tp = fp = fn = 0
    unclear = 0
    correct_n = 0
    per_rule: list[dict[str, Any]] = []
    for rule in rules:
        if rule not in truth:
            continue
        t = truth[rule]
        pred = predicted.get(rule, "unclear")
        correct = pred == t
        if correct:
            correct_n += 1
        if pred == "unclear":
            unclear += 1
        if t == "fail":
            if pred == "fail":
                tp += 1
            else:  # pass or unclear — the violation slipped through
                fn += 1
        elif pred == "fail":  # t == "pass" judged fail — false alarm
            fp += 1
        per_rule.append({"rule": rule, "truth": t, "predicted": pred, "correct": correct})

    reviewed_n = len(truth)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "run_id": report["run_id"],
        "reviewed": reviewed_n,
        "accuracy": round(correct_n / reviewed_n, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "tp": tp, "fp": fp, "fn": fn,
        "unclear": unclear,
        "per_rule": per_rule,
        "unreviewed_rules": unreviewed,
    }
