"""Surface-size and stale-name invariants for the consolidated tool surface
(P4, 2026-08-16).

Two things this milestone learned the hard way, pinned here so neither can
silently regress:

1. **A tool name that survives in agent-facing prose is worse than a missing
   one.** The agent reads the prose, confidently calls a name nothing answers
   to, and the failure surfaces as a confused turn rather than an error a test
   can see. 182 tool-name mentions live across two skill trees.
2. **Surface sizes are load-bearing.** The remote `minimal` listing is a
   teammate's context tax on every single turn, and drift there is invisible
   until a dogfood fails. These numbers are measured, not aspirational — update
   them deliberately when a tool is genuinely added or removed, never to make a
   red test green.
"""
import re
from pathlib import Path

import app.skills as skills_pkg
from app.mcp_server import _HEADLESS_EXCLUDE, _MINIMAL_SURFACE
from app.tools import registered_tool_names
from app.tools._merged import legacy_alias

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Agent-facing prose lives in TWO trees. `plugin/` was missed by this
# milestone's own plan and found only by an implementer's grep — a plugin
# bundle ships the same skill text to Cowork/Desktop users, so a stale name
# there reaches exactly the audience least able to diagnose it.
_PROSE_DIRS = (
    Path(skills_pkg.__file__).resolve().parent,
    _REPO_ROOT / "plugin",
)


def _prose_files() -> list[Path]:
    files: list[Path] = []
    for d in _PROSE_DIRS:
        if d.exists():
            files.extend(sorted(d.rglob("*.md")))
    return files


def test_agent_facing_prose_names_no_folded_away_tool() -> None:
    """No skill or plugin doc may name a tool that was folded into another."""
    stale = legacy_alias()
    assert stale, "sanity: the alias table should not be empty by now"

    offenders: list[str] = []
    for md in _prose_files():
        text = md.read_text(encoding="utf-8")
        for old, new in stale.items():
            if re.search(rf"\b{re.escape(old)}\b", text):
                rel = md.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}: {old} → {new}")
    assert not offenders, (
        "agent-facing prose still names folded-away tools:\n  "
        + "\n  ".join(offenders)
    )


def test_agent_facing_prose_uses_no_stale_tool_globs() -> None:
    """Exact-name greps miss shorthand like `score_*`, which still reads to an
    agent as a live family while naming nothing after the merges.

    Scoped deliberately to globs this milestone's renames could have broken —
    a stem that used to prefix a folded-away tool. A blanket "does any tool
    start with this stem" check flags `m_*` (a model-id pattern) and
    `mcp__emerge_tools__*` (a tool-name prefix), neither of which is a tool
    glob at all; a test that cries wolf gets its assertion deleted by the
    third person who hits it."""
    stale_names = set(legacy_alias())
    live = registered_tool_names()

    offenders: list[str] = []
    for md in _prose_files():
        for n, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            for glob in re.findall(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)*)_\*", line):
                stem = f"{glob}_"
                if not any(old.startswith(stem) for old in stale_names):
                    continue  # not a family this milestone touched
                if not any(t.startswith(stem) for t in live):
                    rel = md.relative_to(_REPO_ROOT)
                    offenders.append(f"{rel}:{n}: `{glob}_*` matches no tool")
    assert not offenders, (
        "agent-facing prose uses tool globs that match nothing:\n  "
        + "\n  ".join(offenders)
    )


def test_surface_sizes_are_what_the_milestone_measured() -> None:
    """P4 end state. Chain of custody for these numbers: 78 `@tool` decorators
    in source, of which only 69 were ever registered (Task 1 fixed that: the
    other 9 had HTTP routes, unit tests and skill prose, but no agent could
    call them), then eight families merged −14 → 64. Then +1 (`diff_predictions`,
    2026-08-20 compare-for-pm T9 — the no-ground-truth branch of /compare; a new
    noun, not a new phrasing of an existing one) → 65."""
    headless = registered_tool_names(headless=True)
    chat = registered_tool_names(headless=False)
    listed = headless - _HEADLESS_EXCLUDE

    assert len(headless) == 65, sorted(headless)
    assert len(chat) == 55, sorted(chat)
    assert len(listed) == 62, sorted(listed)
    # Net-unchanged from the 41 measured before this milestone, and that is the
    # milestone's own thesis in one number: merging cost the minimal listing 3
    # slots (only 3 of the 8 families had BOTH members listed here), and Task
    # 1's three revived red-line tools added 3 back. The remote context tax was
    # already being paid by the listing filter, not by the tool count.
    assert len(listed & _MINIMAL_SURFACE) == 41, sorted(listed & _MINIMAL_SURFACE)


def test_minimal_surface_names_only_live_tools() -> None:
    """A `_MINIMAL_SURFACE` entry for a tool that no longer exists is a silent
    no-op: the filter just never matches it, so the tool is missing from the
    remote listing with nothing to say so."""
    stale = _MINIMAL_SURFACE - registered_tool_names(headless=True)
    assert not stale, f"_MINIMAL_SURFACE names tools that don't exist: {sorted(stale)}"


def test_headless_exclude_names_only_live_tools() -> None:
    stale = _HEADLESS_EXCLUDE - registered_tool_names(headless=True)
    assert not stale, f"_HEADLESS_EXCLUDE names tools that don't exist: {sorted(stale)}"
