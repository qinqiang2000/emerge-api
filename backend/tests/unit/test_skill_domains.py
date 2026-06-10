"""Progressive disclosure (2026-06-10) — slim always-on core + on-demand
domain playbooks. These lock the size budget (the whole point of the split)
and the content-preservation invariants."""
from __future__ import annotations

import pytest

from app.skills import SKILL_DOMAINS, load_domain_skill, load_skill

CORE_LINE_BUDGET = 350


def test_core_skill_stays_slim() -> None:
    """The core is always-on context tax on EVERY turn. If this fails, move
    the new content into a domain file instead of growing the core."""
    core = load_skill("emerge_extractor")
    n = len(core.splitlines())
    assert n <= CORE_LINE_BUDGET, (
        f"emerge_extractor.md is {n} lines (> {CORE_LINE_BUDGET}) — "
        "move domain detail into app/skills/domains/*.md"
    )


def test_every_domain_loads_and_is_substantial() -> None:
    for d in SKILL_DOMAINS:
        text = load_domain_skill(d)
        assert len(text.splitlines()) > 20, f"domain {d} suspiciously small"


def test_unknown_domain_rejected() -> None:
    for bad in ("nope", "../emerge_extractor", "audit/../../.env", ""):
        with pytest.raises(KeyError):
            load_domain_skill(bad)


def test_core_routes_to_every_domain() -> None:
    """The router table must mention each domain — a domain nobody routes to
    is dead context."""
    core = load_skill("emerge_extractor")
    for d in SKILL_DOMAINS:
        assert f'read_skill("{d}")' in core, f"core never routes to {d}"


def test_moved_contracts_live_in_domains_not_core() -> None:
    """Spot-check the heaviest moved sections: present in their domain file,
    absent from the core (no double-pay)."""
    core = load_skill("emerge_extractor")
    assert "corrections_since_tune" in load_domain_skill("review")
    assert "corrections_since_tune" not in core
    assert "save_reviewed_audit" in load_domain_skill("match_audit")
    assert "组不变" in load_domain_skill("match_audit")
    assert "summary_ts" in load_domain_skill("experiments")
    assert "import_schema_from_yaml" in load_domain_skill("attachments")
    assert "agent_brain" in load_domain_skill("self")


def test_red_lines_stay_in_core() -> None:
    """Red lines must never move out of the always-on core."""
    core = load_skill("emerge_extractor")
    for marker in ("write_schema", "image few-shot", "bbox",
                   "run_audit", "freeze_version", "_published/"):
        assert marker in core, f"red-line marker {marker!r} missing from core"
