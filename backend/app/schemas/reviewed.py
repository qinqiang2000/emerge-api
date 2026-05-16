from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ReviewedSource(str, Enum):
    MANUAL = "manual"
    FEEDBACK = "feedback"


class NoteConsumption(BaseModel):
    """One audit-trail record for an inline `_notes[field]` entry that has been
    consumed by a schema-update lifecycle event. Stored under the sibling map
    `_notes_consumed[field]` on the reviewed file; the `_notes` text itself is
    intentionally NOT mutated (we keep the human-authored hint for posterity).

    `consumed_via`:
        - `"accept_candidate"` — user accepted an AutoResearch candidate whose
          rewording was driven by this note (proposer-declared `notes_hit`,
          server-side sanity filtered)
        - `"manual_edit"` — agent or user manually folded the note into the
          schema description / global_notes in chat

    `source_ref` is a free-form pointer (e.g. `"<job_id>.turn_<n>"` for
    AutoResearch, or a chat turn id for manual edits). `active_prompt_id` is
    the prompt the consumption was applied to — this is the correct version
    anchor since accept_candidate mutates the prompt, not the published
    version.
    """

    model_config = ConfigDict(extra="forbid")

    consumed_at: str
    consumed_via: Literal["accept_candidate", "manual_edit"]
    source_ref: str
    active_prompt_id: str


class Reviewed(BaseModel):
    """Ground-truth reviewed extraction for a doc.

    On the wire: `notes` is serialized as `_notes`. The leading underscore
    keeps it visually grouped with `_evidence` in the JSON file but the
    Python attribute uses a regular name.

    `notes_consumed` (wire alias `_notes_consumed`) records which inline
    `_notes[field]` entries have been folded into the schema description by
    an `accept_candidate` (or a manual chat edit). Missing key → all notes
    are unconsumed; this keeps old reviewed files (pre-Phase-B) parsing
    without migration.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entities: list[dict[str, Any]]
    source: ReviewedSource = ReviewedSource.MANUAL
    notes: Optional[dict[str, str]] = Field(default=None, alias="_notes")
    notes_consumed: Optional[dict[str, NoteConsumption]] = Field(
        default=None, alias="_notes_consumed"
    )
    evidence: Optional[list[dict[str, Optional[int]]]] = Field(default=None, alias="_evidence")
