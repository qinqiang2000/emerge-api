"""Operational memory for the Agent brain — so it stops re-deriving.

Why this exists (dogfood 2026-08-10): a chat turn burned its entire tool budget
re-discovering how emerge delivers a file to a browser user, and the turn was
discarded. Next turn it would have started from zero again. The same user, over
in Claude Code CLI, is efficient on this repo precisely because the CLI keeps a
per-project auto-memory (65 notes and counting) — established facts get written
down once and never re-derived.

emerge gets none of that for free: `chat/service.py` passes a hand-built string
system prompt, and Claude Code's auto-memory is a *dynamic section of the
`claude_code` preset* (see the SDK's `SystemPromptPreset.exclude_dynamic_sections`
docstring, which lists working-directory / auto-memory / git-status as the three
stripped sections). Adopting the preset to inherit memory would drag the whole
coding-agent persona into a document colleague — wrong trade. So: same shape,
emerge's own storage, which is filesystem anyway (no DB — a project IS a folder).

## Two scopes

- `{project}/_memory/`  — facts about THIS project.
- `{workspace}/_memory/` — facts about this team across projects.

Both are `_`-prefixed, so `orphans._sweep_dir` already exempts them (it skips
`_`/`.` children) and `workspace_fs` already hides them from listings. No new
sentinel-directory exemption is needed — see the CLAUDE.md note about the
2026-06-04 `teams/` incident for why that matters.

## What is NOT stored here (red line)

Memory feeds the **Agent brain only**. It must never reach the Extract /
Labeler / Proposer / Translator LLMs — those read `schema.json`, `global_notes`
and field `description`s, and nothing else. The five-layer separation in
CLAUDE.md is the whole reason extraction stays reproducible between lab and
prod; a note that leaks into an extract prompt would make a published API behave
differently from the lab that validated it.

The practical corollary, which the skill text has to teach: an extraction *rule*
("dates are DD/MM/YYYY on this vendor") belongs in `global_notes`, NOT here.
What belongs here is how to WORK here: where this project's deliverables go,
which model the user settled on and why, what turned out to be a dead end.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

INDEX_NAME = "MEMORY.md"
MEMORY_DIRNAME = "_memory"

# The index is injected into every single turn's system prompt, so it is a
# recurring token cost on every message the user sends. One line per note keeps
# it cheap; the note bodies are pulled with Read only when a line looks
# relevant. If an index ever exceeds this, that is the signal that notes need
# consolidating, not that the cap needs raising.
_MAX_INDEX_BYTES = 6 * 1024

# Nudge the agent to tidy BEFORE the cap truncates, because truncation is the
# one failure here that actually loses information — everything past the cut is
# invisible to every future turn. At real measured line length (~111 bytes for
# a CJK hook) 6 KB holds ~54 notes, so this fires around 40.
_PRESSURE_RATIO = 0.75


def team_memory_dir(workspace: Path) -> Path:
    return workspace / MEMORY_DIRNAME


def project_memory_dir(workspace: Path, slug: str) -> Path:
    return workspace / slug / MEMORY_DIRNAME


def _read_index(directory: Path) -> str:
    try:
        text = (directory / INDEX_NAME).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
    if len(text.encode("utf-8")) > _MAX_INDEX_BYTES:
        text = text.encode("utf-8")[:_MAX_INDEX_BYTES].decode("utf-8", "ignore")
        text += "\n… (index truncated — consolidate notes)"
    return text


def _index_pressure(*indexes: str) -> float:
    """Largest single index's share of the cap, 0.0–1.0+.

    Per-index rather than summed: each scope truncates against its own cap, so
    a full project index is urgent even when the team index is empty.
    """
    if not indexes:
        return 0.0
    return max(len(i.encode("utf-8")) for i in indexes) / _MAX_INDEX_BYTES


class MemoryNoteError(ValueError):
    """Bad note name, or no such note in the requested scope."""


def _resolve_dir(workspace: Path, slug: str | None) -> Path:
    return project_memory_dir(workspace, slug) if slug else team_memory_dir(workspace)


def forget_note(workspace: Path, slug: str | None, note: str) -> dict[str, Any]:
    """Retire one note: trash the body, then drop its line from the index.

    Deleting a memory note is a *supersede* — the agent decided a fact is
    outdated or duplicated. That judgement must be reversible, which is exactly
    what `Bash rm` is not, so this exists for the same reason `delete_doc` does:
    it looks like an `rm` wrapper and is not.

    Two invariants an `rm` cannot hold:
      * The note body goes to `_trash/` (recoverable for the retention window),
        never to nothing. Consolidation is only safe to encourage because the
        worst case is undoable.
      * The body and its `MEMORY.md` pointer move together. A file with no
        index line is invisible to every future turn — the index IS the agent's
        view of what it knows.

    Order is deliberate: trash first, de-index second. If the second step
    fails, what is left is a dangling index line — the LOUD failure (the agent
    Reads it, gets an error, retries). The reverse order leaves an unindexed
    file, which is the silent one.

    Returns `{forgotten, note, scope, trashed_to, deindexed, restore_hint}`.
    """
    from app.workspace.trash import trash

    name = (note or "").strip()
    if not name.endswith(".md"):
        name += ".md"
    if "/" in name or "\\" in name or name.startswith("."):
        raise MemoryNoteError(f"invalid note name: {note!r}")
    if name == INDEX_NAME:
        raise MemoryNoteError(
            f"{INDEX_NAME} is the index, not a note — retire notes one at a time"
        )

    directory = _resolve_dir(workspace, slug)
    target = directory / name
    if not target.is_file():
        raise MemoryNoteError(f"no such note in this scope: {name}")

    trashed_to = trash(workspace, target)

    deindexed = False
    index_path = directory / INDEX_NAME
    if index_path.is_file():
        try:
            lines = index_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            lines = []
        # Match on the link target `](name)`, not on the hook text — the hook is
        # free prose the agent chose and may not contain the slug at all.
        kept = [ln for ln in lines if f"]({name})" not in ln]
        if len(kept) != len(lines):
            index_path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
            deindexed = True

    return {
        "forgotten": True,
        "note": name,
        "scope": slug or "team",
        "trashed_to": str(trashed_to) if trashed_to else None,
        "deindexed": deindexed,
        # Restoring from the bin returns the FILE; the index line is not
        # replayed (it was an edit, not a move). Said out loud because a
        # silently-unindexed note is invisible, which is the failure this whole
        # function exists to avoid.
        "restore_hint": (
            f"restoring this from the bin also needs its line added back to "
            f"{INDEX_NAME}"
        ),
    }


def render_memory_block(workspace: Path, slug: str | None) -> str:
    """The `## Memory` section spliced into the system prompt each turn.

    Always returns a block, even when both indexes are empty: the instructions
    for *writing* memory are the point on turn one. An agent that is never told
    it has a notebook will never open one.
    """
    team_dir = team_memory_dir(workspace)
    team_index = _read_index(team_dir)
    proj_dir = project_memory_dir(workspace, slug) if slug else None
    proj_index = _read_index(proj_dir) if proj_dir else ""

    lines = ["## Memory", ""]
    if proj_index or team_index:
        lines += [
            "What you already learned. Each line is one note; Read the file "
            "only when the line looks relevant to the current request.",
            "",
        ]
        if proj_index:
            lines += [f"**This project** (`{proj_dir}`):", "", proj_index, ""]
        if team_index:
            lines += [f"**This team, all projects** (`{team_dir}`):", "",
                      team_index, ""]
    else:
        lines += ["No notes yet.", ""]

    lines += [
        "### Writing it down",
        "",
        "When you work something out that you would otherwise have to work out "
        "again next time, write it down before you finish the turn. Use Write "
        "to add `<dir>/<short-kebab-slug>.md` (one fact per file, a few lines, "
        "state the *why*), then Edit `<dir>/" + INDEX_NAME + "` to add one "
        "`- [slug](slug.md) — one-line hook` pointer. Create the directory and "
        "index if they do not exist.",
        "",
        "Begin every note with a `学到于 YYYY-MM-DD` line. Without a date, two "
        "notes on one subject are undecidable — nothing distinguishes a "
        "duplicate from a fact that has since changed, and those two need "
        "opposite treatment.",
        "",
        "Worth a note: where this project's outputs go and how they get "
        "delivered, which model/prompt the user settled on and why, a "
        "reconciliation quirk specific to this customer, an approach that "
        "looked right and was not.",
        "",
        "**Not** worth a note: anything already visible in the filesystem "
        "(file lists, schema contents, what a tool does), or anything that "
        "only matters inside this one conversation.",
        "",
        "**Red line — extraction rules do NOT go here.** \"这个供应商日期是 "
        "DD/MM/YYYY\" / \"税号在右上角\" / \"金额含税\" are instructions for the "
        "extract model: they belong in `global_notes` or a field "
        "`description`, written with `write_schema`. Memory is read only by "
        "you, never by the extract / labeler / proposer models — a rule filed "
        "here would silently stop applying the moment the project is "
        "published, because the published API never sees it. If a fact would "
        "change what gets extracted from a document, it is not a memory.",
        "",
        "Project-scoped by default; put it in the team directory only when it "
        "will still be true in a different project for this customer.",
        "",
        "### Keeping it tidy",
        "",
        "Two notes on the same subject are resolved by **supersede, never by "
        "merge**. Keep the newer one and retire the older with "
        "`forget_memory` — but only when the older one says nothing the newer "
        "one does not. Never write a third note combining them: a combined "
        "note asserts something neither original said, and nobody will ever "
        "catch it.",
        "",
        "If two notes **contradict** each other, that is not a duplicate — it "
        "is a fact that changed, and guessing which side is current is how a "
        "wrong fact gets locked in. Check the filesystem, or ask the user, "
        "then retire the one that is actually stale.",
        "",
        "Retire only on positive evidence: a newer note that covers it, "
        "something in the workspace that contradicts it, or the user saying "
        "so. \"Looks redundant\" is not evidence. Use `forget_memory` rather "
        "than `Bash rm` — it moves the note to the recycle bin and drops its "
        "index line in one step, so a wrong call is reversible.",
    ]

    pressure = _index_pressure(proj_index, team_index)
    if pressure >= _PRESSURE_RATIO:
        # In-band, at the moment the agent is already reading about memory —
        # not a scheduled "go consolidate" job. The agent that just learned
        # something knows which of its notes that supersedes; an agent woken up
        # a week later to tidy has strictly less context and will invent work.
        lines += [
            "",
            f"**The index is {pressure:.0%} of its cap.** Past 100% it is "
            "truncated and everything below the cut becomes invisible to every "
            "future turn. Next time you write a note, retire a stale one in "
            "the same turn.",
        ]
    return "\n".join(lines)
