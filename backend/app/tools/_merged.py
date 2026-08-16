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

MERGED_TOOLS: dict[str, tuple[str, ...]] = {}

# The policy profile the whole family shared, declared per merged tool.
# Declared rather than derived: once a merge lands, the old names are gone from
# the four frozensets, so deriving "did the members agree?" from them would be a
# vacuously-true check over empty sets. Keys must match MERGED_TOOLS exactly.
MERGED_POLICY: dict[str, frozenset[str]] = {}


def legacy_alias() -> dict[str, str]:
    """``{old_name: new_name}`` — the flattened inverse of ``MERGED_TOOLS``."""
    return {
        old: new for new, olds in MERGED_TOOLS.items() for old in olds
    }
