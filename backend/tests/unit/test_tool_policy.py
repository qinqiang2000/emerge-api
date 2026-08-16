"""Policy invariants for merged (multi-op) tools.

The briefing assumed policy would have to become expressible per ``(noun, op)``.
It must not: MCP tool annotations are per tool NAME, and that is the only thing
a client's auto-approve / destructive-gate can key on. A server-side
``(noun, op)`` table cannot be transmitted, so ``project(op='delete')`` would
leave Cowork able only to allow or block the whole tool. `always_allow`
(chat/permissions.py, keyed by tool_name) has the same shape.

So the rule is stronger and simpler than a matrix: every op of a merged tool
shares one policy bucket, and a merged tool never swallows a destructive op.
"""
import pytest

from app.tools import (
    _DESTRUCTIVE,
    _IDEMPOTENT,
    _READ_ONLY,
    _TOUCHES_PROVIDER,
    registered_tool_names,
)
from app.tools._merged import MERGED_POLICY, MERGED_TOOLS, legacy_alias

_BUCKETS = {
    "read_only": _READ_ONLY,
    "destructive": _DESTRUCTIVE,
    "idempotent": _IDEMPOTENT,
    "touches_provider": _TOUCHES_PROVIDER,
}

# The five irreversible / outward-facing verbs. Each must keep a standalone
# name: an MCP client's destructive-gate keys on the tool name, so any of these
# folded into a multi-op tool becomes un-gateable from the client side.
_MUST_STAY_STANDALONE = frozenset({
    "delete_project", "delete_doc",
    "freeze_version", "issue_api_key", "promote_experiment",
})


def _profile(name: str) -> frozenset[str]:
    return frozenset(b for b, s in _BUCKETS.items() if name in s)


def test_destructive_tools_stay_standalone() -> None:
    """A client gates on the tool NAME. Folding delete_* into a multi-op tool
    silently un-gates it — a safety regression, not a refactoring detail."""
    assert _MUST_STAY_STANDALONE <= _DESTRUCTIVE, (
        "a verb left _DESTRUCTIVE without this list being revisited: "
        f"{sorted(_MUST_STAY_STANDALONE - _DESTRUCTIVE)}"
    )
    live = registered_tool_names(headless=True)
    assert _MUST_STAY_STANDALONE <= live, (
        f"destructive verb missing from the surface: "
        f"{sorted(_MUST_STAY_STANDALONE - live)}"
    )
    swallowed = sorted(
        old for olds in MERGED_TOOLS.values() for old in olds
        if old in _MUST_STAY_STANDALONE
    )
    assert not swallowed, (
        f"destructive op(s) folded into a multi-op tool: {swallowed}"
    )


def test_no_merged_tool_is_destructive() -> None:
    for new in MERGED_TOOLS:
        assert new not in _DESTRUCTIVE, (
            f"{new!r} is a merged multi-op tool and must not be destructive: a "
            f"client can only allow or block the whole name."
        )
        assert "destructive" not in MERGED_POLICY.get(new, frozenset())


def test_merged_tool_matches_its_declared_policy_profile() -> None:
    """'Same policy' is one of the four merge criteria. Declared, not derived:
    after a merge the old names are gone from the four frozensets, so deriving
    "did the members agree?" would be a vacuous check over empty sets."""
    assert set(MERGED_POLICY) == set(MERGED_TOOLS), (
        f"MERGED_POLICY and MERGED_TOOLS disagree on which tools are merged: "
        f"only in MERGED_TOOLS {sorted(set(MERGED_TOOLS) - set(MERGED_POLICY))}, "
        f"only in MERGED_POLICY {sorted(set(MERGED_POLICY) - set(MERGED_TOOLS))}"
    )
    for new, declared in MERGED_POLICY.items():
        unknown = declared - set(_BUCKETS)
        assert not unknown, f"{new!r} declares unknown bucket(s) {sorted(unknown)}"
        assert _profile(new) == declared, (
            f"{new!r} is annotated {sorted(_profile(new))} but its family's "
            f"declared shared profile is {sorted(declared)}."
        )


def test_old_names_are_gone_from_the_server() -> None:
    """No deprecated alias on the wire (same posture as `pre_label`). The alias
    lives only in the frontend's history renderer."""
    live = registered_tool_names(headless=True)
    lingering = sorted(set(legacy_alias()) & live)
    assert not lingering, (
        f"Old tool names still registered: {lingering}. Remove the old @tool "
        f"definitions; history rendering is handled in legacyToolName.ts."
    )


def test_merged_targets_are_registered() -> None:
    live = registered_tool_names(headless=True)
    missing = sorted(set(MERGED_TOOLS) - live)
    assert not missing, f"MERGED_TOOLS names a tool nobody registered: {missing}"
