"""Match-prompt versioning (app/tools/match_prompt.py)."""
from __future__ import annotations

import pytest

from app.tools.match_prompt import (
    MatchPromptNotFoundError,
    read_active_match_prompt,
    write_match_prompt,
)
from app.tools.match_project import create_match_project
from app.tools.projects import create_project
from app.workspace.paths import match_prompt_version_path


async def _match_project(workspace) -> str:
    anchor = (await create_project(workspace, name="invoices"))["slug"]
    src = (await create_project(workspace, name="payments"))["slug"]
    return (await create_match_project(workspace, name="对账", anchor=anchor, sources=[src]))["slug"]


_MAPS = {"payments": [{"anchor": "amount", "source": "amount", "tol": {"type": "number", "abs": 0.01}}]}


async def test_write_mints_v1_and_sets_active(workspace):
    slug = await _match_project(workspace)
    mpr_id = await write_match_prompt(workspace, slug, mappings=_MAPS, rules="r1")
    assert mpr_id.startswith("mpr_")
    pv = await read_active_match_prompt(workspace, slug)
    assert pv.version == 1 and pv.rules == "r1"
    assert "payments" in pv.mappings
    assert match_prompt_version_path(workspace, slug, mpr_id, 1).exists()


async def test_noop_rewrite_keeps_version(workspace):
    slug = await _match_project(workspace)
    mpr_id = await write_match_prompt(workspace, slug, mappings=_MAPS, rules="r1")
    again = await write_match_prompt(workspace, slug, mappings=_MAPS, rules="r1")
    assert again == mpr_id
    assert (await read_active_match_prompt(workspace, slug)).version == 1


async def test_content_change_bumps_version_and_snapshots(workspace):
    slug = await _match_project(workspace)
    mpr_id = await write_match_prompt(workspace, slug, mappings=_MAPS, rules="r1")
    await write_match_prompt(workspace, slug, mappings=_MAPS, rules="r2-changed")
    pv = await read_active_match_prompt(workspace, slug)
    assert pv.version == 2 and pv.rules == "r2-changed"
    # both versions snapshotted
    assert match_prompt_version_path(workspace, slug, mpr_id, 1).exists()
    assert match_prompt_version_path(workspace, slug, mpr_id, 2).exists()


async def test_read_active_without_prompt_raises(workspace):
    slug = await _match_project(workspace)
    with pytest.raises(MatchPromptNotFoundError):
        await read_active_match_prompt(workspace, slug)


async def test_audit_rules_bump_and_preserve_mappings(workspace):
    from app.tools.match_prompt import write_audit_rules
    slug = await _match_project(workspace)
    # set mappings first
    await write_match_prompt(workspace, slug, mappings=_MAPS, rules="r1")
    # adding audit rules bumps version + preserves mappings (partial update)
    await write_audit_rules(workspace, slug, audit_rules=["甲方为环胜", "盖红章"])
    pv = await read_active_match_prompt(workspace, slug)
    assert pv.version == 2
    assert [r.rule for r in pv.audit_rules] == ["甲方为环胜", "盖红章"]
    assert all(r.level == "critical" and r.check is None for r in pv.audit_rules)
    assert "payments" in pv.mappings and pv.rules == "r1"   # not clobbered
    # no-op rewrite keeps version
    await write_audit_rules(workspace, slug, audit_rules=["甲方为环胜", "盖红章"])
    assert (await read_active_match_prompt(workspace, slug)).version == 2


async def test_audit_rules_object_and_string_mix(workspace):
    """A3 — `audit_rules` accepts str/object mixed input; objects carry level +
    an optional L1 check spec; same content same hash regardless of spelling."""
    from app.tools.match_prompt import write_audit_rules
    slug = await _match_project(workspace)
    await write_audit_rules(workspace, slug, audit_rules=[
        "盖红章",
        {"rule": "附物料清单", "level": "warning"},
        {"rule": "金额一致",
         "check": {"type": "eq",
                   "left": {"doc": "报价单", "field": "total"},
                   "right": {"doc": "收货单", "field": "amount"},
                   "tol": 0.01}},
    ])
    pv = await read_active_match_prompt(workspace, slug)
    assert pv.version == 1
    assert [r.rule for r in pv.audit_rules] == ["盖红章", "附物料清单", "金额一致"]
    assert [r.level for r in pv.audit_rules] == ["critical", "warning", "critical"]
    assert pv.audit_rules[2].check is not None
    assert pv.audit_rules[2].check.type == "eq"
    assert pv.audit_rules[2].check.tol == 0.01

    # bare string vs explicit {rule, level:"critical"} = same content → no bump
    await write_audit_rules(workspace, slug, audit_rules=[
        {"rule": "盖红章", "level": "critical"},
        {"rule": "附物料清单", "level": "warning"},
        {"rule": "金额一致",
         "check": {"type": "eq",
                   "left": {"doc": "报价单", "field": "total"},
                   "right": {"doc": "收货单", "field": "amount"},
                   "tol": 0.01}},
    ])
    assert (await read_active_match_prompt(workspace, slug)).version == 1

    # changing only a level IS a content change → bump
    await write_audit_rules(workspace, slug, audit_rules=[
        {"rule": "盖红章", "level": "warning"},
        {"rule": "附物料清单", "level": "warning"},
        {"rule": "金额一致",
         "check": {"type": "eq",
                   "left": {"doc": "报价单", "field": "total"},
                   "right": {"doc": "收货单", "field": "amount"},
                   "tol": 0.01}},
    ])
    assert (await read_active_match_prompt(workspace, slug)).version == 2
