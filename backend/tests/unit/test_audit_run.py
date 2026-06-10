"""run_audit — audit ONE project's own document group (app/tools/audit_run.py)."""
from __future__ import annotations

import pytest

from app.provider.base import ProviderResult
from app.tools.audit_run import AuditError, run_audit
from app.tools.match_prompt import write_audit_rules
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import docs_dir, docs_meta_dir, prediction_draft_path


class _MockProvider:
    def __init__(self, checks):
        self._checks = checks

    async def extract(self, *, model_id, system_prompt, user_content, response_schema, params=None):
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
