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

INDEX_NAME = "MEMORY.md"
MEMORY_DIRNAME = "_memory"

# The index is injected into every single turn's system prompt, so it is a
# recurring token cost on every message the user sends. One line per note keeps
# it cheap; the note bodies are pulled with Read only when a line looks
# relevant. If an index ever exceeds this, that is the signal that notes need
# consolidating, not that the cap needs raising.
_MAX_INDEX_BYTES = 6 * 1024


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
        "index if they do not exist. Update an existing note rather than "
        "adding a near-duplicate; delete notes that turn out to be wrong.",
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
    ]
    return "\n".join(lines)
