"""Single source of truth for P4 tool consolidation: which old tool names were
folded into which new one.

Three consumers read this and MUST NOT keep their own copies:
- ``tests/unit/test_tool_policy.py`` — every op of a merged tool shares one
  policy bucket, and no merged tool may swallow a destructive op.
- ``tests/unit/test_symmetry_invariant.py`` — a merged tool maps
  ``(tool, op) -> route``, because REST already expresses ops as resource+verb
  and the HTTP side deliberately does NOT merge.
- ``frontend/src/lib/legacyToolName.ts`` — 764 historical tool_call records in
  chats/*.jsonl store the OLD names; they still have to render.

The server does NOT accept old names (no deprecated alias — same posture as
`pre_label`). Aliasing here is a RENDERING concern only.
"""
from __future__ import annotations

MERGED_TOOLS: dict[str, tuple[str, ...]] = {
    # Byte-identical `(slug, model_id)` schemas, all idempotent, zero calls
    # across 764 chat tool_calls + 145 remote MCP calls.
    "set_model": (
        "set_labeler_model", "set_proposer_model",
        "set_translate_model", "switch_active_model",
    ),
    # get_project_config already returned a superset per role; the merge adds
    # the one field it lacked (env_default).
    "get_project_config": ("get_labeler_config",),
    # Both read-only halves of schema version history. history_restore mutates
    # and stays out: same noun, different policy. Only reachable since P4
    # Task 1 (2026-08-16) and never appeared in a chat tool_call before this
    # merge landed, so no frontend alias is needed for either old name.
    "history": ("history_log", "history_diff"),
}

# The policy profile the whole family shared, declared per merged tool.
# Declared rather than derived: once a merge lands, the old names are gone from
# the four frozensets, so deriving "did the members agree?" from them would be a
# vacuously-true check over empty sets. Keys must match MERGED_TOOLS exactly.
MERGED_POLICY: dict[str, frozenset[str]] = {
    "set_model": frozenset({"idempotent"}),
    "get_project_config": frozenset({"read_only"}),
    "history": frozenset({"read_only"}),
}


def legacy_alias() -> dict[str, str]:
    """``{old_name: new_name}`` — the flattened inverse of ``MERGED_TOOLS``."""
    return {
        old: new for new, olds in MERGED_TOOLS.items() for old in olds
    }
