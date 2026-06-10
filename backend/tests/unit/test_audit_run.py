"""run_audit — audit ONE project's own document group (app/tools/audit_run.py)."""
from __future__ import annotations

import json

import pytest

from app.provider.base import ProviderResult, TextBlock
from app.tools.audit_run import AuditError, read_audit_report, run_audit
from app.tools.match_prompt import read_active_match_prompt, write_audit_rules
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    docs_dir,
    docs_meta_dir,
    match_prompt_path,
    prediction_draft_path,
    project_json_path,
)


class _MockProvider:
    """Counts calls + captures the rules text the judge actually received."""

    def __init__(self, checks):
        self._checks = checks
        self.calls = 0
        self.last_text = ""

    async def extract(self, *, model_id, system_prompt, user_content, response_schema, params=None):
        self.calls += 1
        self.last_text = "".join(
            b.text for b in user_content if isinstance(b, TextBlock)
        )
        return ProviderResult(raw_json={"checks": self._checks}, model_id=model_id)


async def _audit_project(workspace, *, docs, rules=True, with_draft=False):
    """One audit project: a single business's docs in its own docs/, + rules."""
    slug = (await create_project(workspace, name="审核"))["slug"]
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    docs_meta_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    for fn, rec in docs.items():
        (docs_dir(workspace, slug) / fn).write_bytes(b"stub")
        atomic_write_json(
            docs_meta_dir(workspace, slug) / f"{fn}.json",
            {"filename": fn, "sha256": "x", "page_count": 1, "ext": "jpg"},
        )
        if with_draft:
            pd = prediction_draft_path(workspace, slug, fn)
            pd.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(pd, {"entities": [rec]})
    if rules:
        await write_audit_rules(workspace, slug, audit_rules=[
            "报价单甲方为环胜", "报价单金额与收货单一致", "报价单盖红章",
        ])
    return slug


_DOCS = {"报价单.jpg": {"甲方": "环胜"}, "收货单.jpg": {"金额": "100"}, "订单.jpg": {}}


async def test_audit_pass(workspace):
    slug = await _audit_project(workspace, docs=_DOCS)
    p = _MockProvider([
        {"index": 0, "status": "pass", "reason": "甲方=环胜"},
        {"index": 1, "status": "pass", "reason": "金额一致"},
        {"index": 2, "status": "pass", "reason": "见红章"},
    ])
    report = await run_audit(workspace, slug, provider=p, model_id="m")
    assert report["overall"] == "pass"
    assert [c["status"] for c in report["checks"]] == ["pass", "pass", "pass"]
    # all three docs in the project participated
    assert set(report["group"]) == {"报价单.jpg", "收货单.jpg", "订单.jpg"}


async def test_audit_fail(workspace):
    slug = await _audit_project(workspace, docs=_DOCS)
    p = _MockProvider([
        {"index": 0, "status": "pass", "reason": "ok"},
        {"index": 1, "status": "pass", "reason": "ok"},
        {"index": 2, "status": "fail", "reason": "未盖章"},
    ])
    report = await run_audit(workspace, slug, provider=p, model_id="m")
    assert report["overall"] == "fail"


async def test_audit_unclear_does_not_fail(workspace):
    slug = await _audit_project(workspace, docs=_DOCS)
    p = _MockProvider([
        {"index": 0, "status": "pass", "reason": "ok"},
        {"index": 1, "status": "pass", "reason": "ok"},
        {"index": 2, "status": "unclear", "reason": "图不清"},
    ])
    report = await run_audit(workspace, slug, provider=p, model_id="m")
    assert report["overall"] == "pass"


async def test_audit_without_extraction(workspace):
    # docs never extracted — images are the source of truth
    slug = await _audit_project(workspace, docs=_DOCS, with_draft=False)
    p = _MockProvider([
        {"index": 0, "status": "pass", "reason": "ok"},
        {"index": 1, "status": "pass", "reason": "ok"},
        {"index": 2, "status": "pass", "reason": "见红章"},
    ])
    report = await run_audit(workspace, slug, provider=p, model_id="m")
    assert report["overall"] == "pass"


async def test_audit_no_rules(workspace):
    slug = await _audit_project(workspace, docs=_DOCS, rules=False)
    with pytest.raises(AuditError) as ei:
        await run_audit(workspace, slug, provider=_MockProvider([]))
    assert ei.value.error_code == "audit_no_rules"


async def test_audit_no_docs(workspace):
    slug = (await create_project(workspace, name="空审核"))["slug"]
    await write_audit_rules(workspace, slug, audit_rules=["甲方为环胜"])
    with pytest.raises(AuditError) as ei:
        await run_audit(workspace, slug, provider=_MockProvider([]))
    assert ei.value.error_code == "audit_no_docs"


# --- A3: levels + tri-state overall -------------------------------------------


async def test_overall_warn_when_only_warning_rules_fail(workspace):
    slug = await _audit_project(workspace, docs=_DOCS, rules=False)
    await write_audit_rules(workspace, slug, audit_rules=[
        "报价单甲方为环胜",
        {"rule": "报价单附物料清单", "level": "warning"},
    ])
    p = _MockProvider([
        {"index": 0, "status": "pass", "reason": "ok"},
        {"index": 1, "status": "fail", "reason": "未附"},
    ])
    report = await run_audit(workspace, slug, provider=p, model_id="m")
    assert report["overall"] == "warn"
    assert report["checks"][1]["level"] == "warning"
    assert report["checks"][1]["decided_by"] == "judge"


async def test_overall_fail_when_critical_fails_even_with_warning_fail(workspace):
    slug = await _audit_project(workspace, docs=_DOCS, rules=False)
    await write_audit_rules(workspace, slug, audit_rules=[
        "报价单甲方为环胜",
        {"rule": "报价单附物料清单", "level": "warning"},
    ])
    p = _MockProvider([
        {"index": 0, "status": "fail", "reason": "甲方不符"},
        {"index": 1, "status": "fail", "reason": "未附"},
    ])
    report = await run_audit(workspace, slug, provider=p, model_id="m")
    assert report["overall"] == "fail"


async def test_overall_pass_unclear_never_downgrades(workspace):
    slug = await _audit_project(workspace, docs=_DOCS, rules=False)
    await write_audit_rules(workspace, slug, audit_rules=[
        "报价单甲方为环胜", {"rule": "报价单附物料清单", "level": "warning"},
    ])
    p = _MockProvider([
        {"index": 0, "status": "pass", "reason": "ok"},
        {"index": 1, "status": "unclear", "reason": "图不清"},
    ])
    report = await run_audit(workspace, slug, provider=p, model_id="m")
    assert report["overall"] == "pass"


# --- A3: L1 fast path wired into run_audit -------------------------------------


_L1_DOCS = {
    "报价单.jpg": {"total": "¥370,815.56", "甲方": "环胜"},
    "收货单.jpg": {"amount": "370815.56"},
}


async def _l1_project(workspace, audit_rules):
    slug = await _audit_project(workspace, docs=_L1_DOCS, rules=False, with_draft=True)
    await write_audit_rules(workspace, slug, audit_rules=audit_rules)
    return slug


async def test_l1_decided_rules_skip_the_judge(workspace):
    slug = await _l1_project(workspace, [
        {"rule": "报价单金额与收货单一致",
         "check": {"type": "eq",
                   "left": {"doc": "报价单", "field": "total"},
                   "right": {"doc": "收货单", "field": "amount"},
                   "tol": 0.01}},
        "报价单盖红章",          # visual → judge
        "订单完成日期在周期内",   # no spec → judge
    ])
    # The judge sees a 2-rule subset numbered 0/1; verdicts map back by order.
    p = _MockProvider([
        {"index": 0, "status": "fail", "reason": "未见红章"},
        {"index": 1, "status": "pass", "reason": "在周期内"},
    ])
    report = await run_audit(workspace, slug, provider=p, model_id="m")
    assert p.calls == 1
    # L1-decided rule never reached the judge prompt
    assert "报价单金额与收货单一致" not in p.last_text
    assert "报价单盖红章" in p.last_text and "订单完成日期在周期内" in p.last_text
    # report keeps the ORIGINAL rule order with verdicts correctly aligned
    assert [c["rule"] for c in report["checks"]] == [
        "报价单金额与收货单一致", "报价单盖红章", "订单完成日期在周期内",
    ]
    assert [c["status"] for c in report["checks"]] == ["pass", "fail", "pass"]
    assert [c["decided_by"] for c in report["checks"]] == ["l1", "judge", "judge"]
    assert report["checks"][0]["reason"].startswith("L1:")
    assert report["overall"] == "fail"


async def test_all_l1_zero_judge_calls(workspace):
    slug = await _l1_project(workspace, [
        {"rule": "金额一致",
         "check": {"type": "eq",
                   "left": {"doc": "报价单", "field": "total"},
                   "right": {"doc": "收货单", "field": "amount"},
                   "tol": 0.01}},
        {"rule": "甲方为环胜",
         "check": {"type": "eq",
                   "left": {"doc": "报价单", "field": "甲方"},
                   "right": "环胜"}},
    ])
    p = _MockProvider([])
    report = await run_audit(workspace, slug, provider=p, model_id="m")
    assert p.calls == 0   # all rules L1-decided → zero judge trips
    assert report["overall"] == "pass"
    assert all(c["decided_by"] == "l1" for c in report["checks"])


async def test_check_with_missing_fields_silently_goes_to_judge(workspace):
    # docs never extracted → no fields in hand → spec'd rule still judged,
    # never an "extract first" error.
    slug = await _audit_project(workspace, docs=_DOCS, rules=False, with_draft=False)
    await write_audit_rules(workspace, slug, audit_rules=[
        {"rule": "金额一致",
         "check": {"type": "eq",
                   "left": {"doc": "报价单", "field": "total"},
                   "right": {"doc": "收货单", "field": "amount"}}},
    ])
    p = _MockProvider([{"index": 0, "status": "pass", "reason": "ok"}])
    report = await run_audit(workspace, slug, provider=p, model_id="m")
    assert p.calls == 1
    assert report["checks"][0]["decided_by"] == "judge"
    assert report["overall"] == "pass"


# --- A3: legacy prompt JSON compatibility ---------------------------------------


async def test_legacy_list_str_prompt_json_loads(workspace):
    """Pre-A3 prod match prompts persist `audit_rules: list[str]` — they must
    read back coerced (critical, no check) with run_audit working unchanged."""
    slug = await _audit_project(workspace, docs=_DOCS)
    # Rewrite the active prompt blob to the legacy shape on disk.
    project = json.loads(project_json_path(workspace, slug).read_text(encoding="utf-8"))
    mp = match_prompt_path(workspace, slug, project["active_match_prompt_id"])
    blob = json.loads(mp.read_text(encoding="utf-8"))
    blob["audit_rules"] = ["报价单甲方为环胜", "报价单盖红章"]
    atomic_write_json(mp, blob)

    mpv = await read_active_match_prompt(workspace, slug)
    assert [r.rule for r in mpv.audit_rules] == ["报价单甲方为环胜", "报价单盖红章"]
    assert all(r.level == "critical" and r.check is None for r in mpv.audit_rules)

    p = _MockProvider([
        {"index": 0, "status": "pass", "reason": "ok"},
        {"index": 1, "status": "fail", "reason": "未盖章"},
    ])
    report = await run_audit(workspace, slug, provider=p, model_id="m")
    assert report["overall"] == "fail"


# --- A3: read_audit_report ------------------------------------------------------


async def test_read_audit_report_returns_latest(workspace):
    slug = await _audit_project(workspace, docs=_DOCS)
    p1 = _MockProvider([
        {"index": 0, "status": "pass", "reason": "ok"},
        {"index": 1, "status": "pass", "reason": "ok"},
        {"index": 2, "status": "fail", "reason": "未盖章"},
    ])
    first = await run_audit(workspace, slug, provider=p1, model_id="m")
    p2 = _MockProvider([
        {"index": 0, "status": "pass", "reason": "ok"},
        {"index": 1, "status": "pass", "reason": "ok"},
        {"index": 2, "status": "pass", "reason": "补盖了"},
    ])
    second = await run_audit(workspace, slug, provider=p2, model_id="m")
    assert first["run_id"] != second["run_id"]

    latest = await read_audit_report(workspace, slug)
    assert latest["run_id"] == second["run_id"]
    assert latest["overall"] == "pass"


async def test_read_audit_report_without_runs_errors(workspace):
    slug = (await create_project(workspace, name="未审核"))["slug"]
    with pytest.raises(AuditError) as ei:
        await read_audit_report(workspace, slug)
    assert ei.value.error_code == "audit_no_report"
