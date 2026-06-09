"""run_audit — single-group audit end-to-end (app/tools/audit_run.py)."""
from __future__ import annotations

import pytest

from app.provider.base import ProviderResult
from app.tools.audit_run import run_audit
from app.tools.match_project import MatchProjectError, create_match_project
from app.tools.match_prompt import write_audit_rules
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import docs_dir, docs_meta_dir, prediction_draft_path


class _MockProvider:
    def __init__(self, checks):
        self._checks = checks

    async def extract(self, *, model_id, system_prompt, user_content, response_schema, params=None):
        return ProviderResult(raw_json={"checks": self._checks}, model_id=model_id)


async def _seed_extract(workspace, name, docs):
    slug = (await create_project(workspace, name=name))["slug"]
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    docs_meta_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    for fn, rec in docs.items():
        (docs_dir(workspace, slug) / fn).write_bytes(b"stub")
        atomic_write_json(
            docs_meta_dir(workspace, slug) / f"{fn}.json",
            {"filename": fn, "sha256": "x", "page_count": 1, "ext": "jpg"},
        )
        pd = prediction_draft_path(workspace, slug, fn)
        pd.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(pd, {"entities": [rec]})
    return slug


async def _build(workspace, with_rules=True):
    quote = await _seed_extract(workspace, "quote", {"q1.jpg": {"甲方": "环胜", "金额": "100"}})
    receipt = await _seed_extract(workspace, "receipt", {"r1.jpg": {"金额": "100"}})
    slug = (await create_match_project(
        workspace, name="审核", anchor=quote, sources=[receipt]))["slug"]
    if with_rules:
        await write_audit_rules(workspace, slug, audit_rules=[
            "报价单甲方为环胜", "金额与收货单一致", "乙方盖红章",
        ])
    return slug, quote, receipt


async def test_run_audit_pass(workspace):
    slug, quote, receipt = await _build(workspace)
    p = _MockProvider([
        {"index": 0, "status": "pass", "reason": "甲方=环胜"},
        {"index": 1, "status": "pass", "reason": "金额一致"},
        {"index": 2, "status": "pass", "reason": "见红章"},
    ])
    report = await run_audit(
        workspace, slug, anchor_doc="q1.jpg", source_docs={receipt: "r1.jpg"},
        provider=p, model_id="m",
    )
    assert report["overall"] == "pass"
    assert [c["status"] for c in report["checks"]] == ["pass", "pass", "pass"]
    assert report["group"][quote] == "q1.jpg" and report["group"][receipt] == "r1.jpg"


async def test_run_audit_fail(workspace):
    slug, quote, receipt = await _build(workspace)
    p = _MockProvider([
        {"index": 0, "status": "pass", "reason": "ok"},
        {"index": 1, "status": "pass", "reason": "ok"},
        {"index": 2, "status": "fail", "reason": "未盖章"},
    ])
    report = await run_audit(
        workspace, slug, anchor_doc="q1.jpg", source_docs={receipt: "r1.jpg"},
        provider=p, model_id="m",
    )
    assert report["overall"] == "fail"   # one fail → overall fail


async def test_run_audit_unclear_does_not_fail(workspace):
    slug, quote, receipt = await _build(workspace)
    p = _MockProvider([
        {"index": 0, "status": "pass", "reason": "ok"},
        {"index": 1, "status": "pass", "reason": "ok"},
        {"index": 2, "status": "unclear", "reason": "图不清"},
    ])
    report = await run_audit(
        workspace, slug, anchor_doc="q1.jpg", source_docs={receipt: "r1.jpg"},
        provider=p, model_id="m",
    )
    assert report["overall"] == "pass"   # unclear is surfaced but doesn't fail


async def test_run_audit_unknown_source(workspace):
    slug, quote, receipt = await _build(workspace)
    with pytest.raises(MatchProjectError) as ei:
        await run_audit(workspace, slug, anchor_doc="q1.jpg",
                        source_docs={"ghost": "x.jpg"}, provider=_MockProvider([]))
    assert ei.value.error_code == "audit_unknown_source"


async def test_run_audit_no_rules(workspace):
    slug, quote, receipt = await _build(workspace, with_rules=False)
    with pytest.raises(MatchProjectError) as ei:
        await run_audit(workspace, slug, anchor_doc="q1.jpg",
                        source_docs={receipt: "r1.jpg"}, provider=_MockProvider([]))
    assert ei.value.error_code == "audit_no_rules"


async def test_run_audit_doc_not_extracted(workspace):
    slug, quote, receipt = await _build(workspace)
    with pytest.raises(MatchProjectError) as ei:
        await run_audit(workspace, slug, anchor_doc="nonexist.jpg",
                        source_docs={receipt: "r1.jpg"}, provider=_MockProvider([]))
    assert ei.value.error_code == "audit_doc_not_extracted"
