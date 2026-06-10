"""Audit review + scoring (app/tools/audit_review.py — A2)."""
from __future__ import annotations

import json

import pytest

from app.provider.base import ProviderResult
from app.tools.audit_review import save_reviewed_audit, score_audit
from app.tools.audit_run import AuditError
from app.tools.match_prompt import write_audit_rules
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import docs_dir, docs_meta_dir, reviewed_audit_path


class _MockProvider:
    """Counts calls so tests can assert the judge was (not) invoked."""

    def __init__(self, checks):
        self._checks = checks
        self.calls = 0

    async def extract(self, *, model_id, system_prompt, user_content, response_schema, params=None):
        self.calls += 1
        return ProviderResult(raw_json={"checks": self._checks}, model_id=model_id)


_RULES = ["报价单甲方为环胜", "报价单金额与收货单一致", "报价单盖红章"]
_DOCS = ("报价单.jpg", "收货单.jpg")


async def _audit_project(workspace, *, rules=_RULES):
    """One audit project: a group of docs in its own docs/, + audit rules."""
    slug = (await create_project(workspace, name="审核"))["slug"]
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    docs_meta_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    for fn in _DOCS:
        (docs_dir(workspace, slug) / fn).write_bytes(b"stub")
        atomic_write_json(
            docs_meta_dir(workspace, slug) / f"{fn}.json",
            {"filename": fn, "sha256": "x", "page_count": 1, "ext": "jpg"},
        )
    if rules:
        await write_audit_rules(workspace, slug, audit_rules=list(rules))
    return slug


def _checks(*statuses):
    return [
        {"index": i, "status": s, "reason": "r"} for i, s in enumerate(statuses)
    ]


# --- save_reviewed_audit -----------------------------------------------------


async def test_save_reviewed_audit_upsert_merge(workspace):
    slug = await _audit_project(workspace)
    out = await save_reviewed_audit(
        workspace, slug, expected={_RULES[0]: "pass", _RULES[2]: "fail"},
    )
    assert out["rules_confirmed"] == 2
    assert out["total_rules"] == 3
    assert out["unreviewed_rules"] == [_RULES[1]]

    # second save merges (and may overwrite a prior verdict)
    out = await save_reviewed_audit(
        workspace, slug, expected={_RULES[1]: "pass", _RULES[2]: "pass"},
    )
    assert out["rules_confirmed"] == 3
    assert out["unreviewed_rules"] == []
    blob = json.loads(reviewed_audit_path(workspace, slug).read_text(encoding="utf-8"))
    assert blob["expected"] == {
        _RULES[0]: "pass", _RULES[1]: "pass", _RULES[2]: "pass",
    }
    assert blob["match_prompt_version"] == 1
    assert blob["reviewed_at"]


async def test_save_rejects_unknown_rule_and_names_it(workspace):
    slug = await _audit_project(workspace)
    with pytest.raises(AuditError) as ei:
        await save_reviewed_audit(
            workspace, slug, expected={"幽灵规则": "pass", _RULES[0]: "pass"},
        )
    assert ei.value.error_code == "audit_unknown_rule"
    assert "幽灵规则" in ei.value.error_message_en
    # nothing persisted on rejection
    assert not reviewed_audit_path(workspace, slug).exists()


async def test_save_rejects_bad_status(workspace):
    slug = await _audit_project(workspace)
    with pytest.raises(AuditError) as ei:
        await save_reviewed_audit(workspace, slug, expected={_RULES[0]: "unclear"})
    assert ei.value.error_code == "audit_bad_status"


async def test_save_partial_confirmation(workspace):
    slug = await _audit_project(workspace)
    out = await save_reviewed_audit(workspace, slug, expected={_RULES[1]: "fail"})
    assert out["rules_confirmed"] == 1
    assert set(out["unreviewed_rules"]) == {_RULES[0], _RULES[2]}


async def test_save_without_rules_errors(workspace):
    slug = await _audit_project(workspace, rules=None)
    with pytest.raises(AuditError) as ei:
        await save_reviewed_audit(workspace, slug, expected={_RULES[0]: "pass"})
    assert ei.value.error_code == "audit_no_rules"


# --- score_audit -------------------------------------------------------------


async def test_score_all_correct(workspace):
    slug = await _audit_project(workspace)
    await save_reviewed_audit(workspace, slug, expected={
        _RULES[0]: "pass", _RULES[1]: "pass", _RULES[2]: "fail",
    })
    p = _MockProvider(_checks("pass", "pass", "fail"))
    res = await score_audit(workspace, slug, provider=p, model_id="m")
    assert res["reviewed"] == 3
    assert res["accuracy"] == 1.0
    assert res["tp"] == 1 and res["fp"] == 0 and res["fn"] == 0
    assert res["precision"] == 1.0 and res["recall"] == 1.0
    assert res["unclear"] == 0
    assert res["unreviewed_rules"] == []
    assert all(r["correct"] for r in res["per_rule"])
    assert res["run_id"].startswith("au_")


async def test_score_true_fail_judged_pass_is_fn(workspace):
    slug = await _audit_project(workspace)
    await save_reviewed_audit(workspace, slug, expected={
        _RULES[0]: "pass", _RULES[1]: "pass", _RULES[2]: "fail",
    })
    p = _MockProvider(_checks("pass", "pass", "pass"))  # missed the violation
    res = await score_audit(workspace, slug, provider=p, model_id="m")
    assert res["fn"] == 1 and res["tp"] == 0 and res["fp"] == 0
    assert res["recall"] == 0.0
    assert res["accuracy"] == round(2 / 3, 4)
    wrong = [r for r in res["per_rule"] if not r["correct"]]
    assert wrong == [{"rule": _RULES[2], "truth": "fail",
                      "predicted": "pass", "correct": False}]


async def test_score_true_pass_judged_fail_is_fp(workspace):
    slug = await _audit_project(workspace)
    await save_reviewed_audit(workspace, slug, expected={
        _RULES[0]: "pass", _RULES[1]: "pass", _RULES[2]: "fail",
    })
    p = _MockProvider(_checks("fail", "pass", "fail"))  # false alarm on rule 0
    res = await score_audit(workspace, slug, provider=p, model_id="m")
    assert res["fp"] == 1 and res["tp"] == 1 and res["fn"] == 0
    assert res["precision"] == 0.5 and res["recall"] == 1.0
    assert res["accuracy"] == round(2 / 3, 4)


async def test_score_unclear_is_fn_on_true_fail_never_fp_on_true_pass(workspace):
    slug = await _audit_project(workspace)
    await save_reviewed_audit(workspace, slug, expected={
        _RULES[0]: "pass", _RULES[1]: "pass", _RULES[2]: "fail",
    })
    # unclear on a true pass (rule 0) AND on a true fail (rule 2)
    p = _MockProvider(_checks("unclear", "pass", "unclear"))
    res = await score_audit(workspace, slug, provider=p, model_id="m")
    assert res["unclear"] == 2
    assert res["fn"] == 1   # the true fail slipped through
    assert res["fp"] == 0   # unclear never raises a false alarm
    assert res["accuracy"] == round(1 / 3, 4)


async def test_score_reworded_rule_detaches_truth(workspace):
    slug = await _audit_project(workspace)
    await save_reviewed_audit(workspace, slug, expected={
        _RULES[0]: "pass", _RULES[1]: "pass", _RULES[2]: "fail",
    })
    # rule 1 gets reworded — its old truth must NOT score against the new text
    reworded = "报价单费用总计与收货单折扣后金额一致"
    await write_audit_rules(
        workspace, slug, audit_rules=[_RULES[0], reworded, _RULES[2]],
    )
    p = _MockProvider(_checks("pass", "fail", "fail"))
    res = await score_audit(workspace, slug, provider=p, model_id="m")
    assert res["reviewed"] == 2
    assert res["unreviewed_rules"] == [reworded]
    assert {r["rule"] for r in res["per_rule"]} == {_RULES[0], _RULES[2]}
    assert res["accuracy"] == 1.0  # the reworded rule's verdict didn't count


async def test_score_no_truth_zero_envelope_and_no_judge_call(workspace):
    slug = await _audit_project(workspace)
    p = _MockProvider(_checks("pass", "pass", "pass"))
    res = await score_audit(workspace, slug, provider=p, model_id="m")
    assert res == {
        "run_id": None,
        "reviewed": 0,
        "accuracy": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "tp": 0, "fp": 0, "fn": 0,
        "unclear": 0,
        "per_rule": [],
        "unreviewed_rules": _RULES,
    }
    assert p.calls == 0  # zero truth → judge never invoked


async def test_score_without_rules_errors(workspace):
    slug = await _audit_project(workspace, rules=None)
    p = _MockProvider([])
    with pytest.raises(AuditError) as ei:
        await score_audit(workspace, slug, provider=p, model_id="m")
    assert ei.value.error_code == "audit_no_rules"
    assert p.calls == 0
