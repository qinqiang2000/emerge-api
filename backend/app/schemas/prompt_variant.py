from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.schema_field import SchemaField


class PromptVariant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    prompt_id: str
    label: str
    schema: list[SchemaField]
    global_notes: str = ""
    derived_from: Optional[str] = None
    created_at: str
    updated_at: str
    # Monotonic content version. Bumped by `write_prompt` only when the content
    # (schema + global_notes) actually changes — a no-op save keeps the number.
    # Snapshots of every distinct version live at prompts/_versions/{id}/v{n}.json
    # so an experiment that pinned `prompt_version=N` can always be traced back
    # to the exact prompt it ran against (tune mutates the head in place; without
    # this, "Baseline" silently meant different content at different times).
    # Defaults to 1 for pre-versioning blobs read off disk.
    version: int = 1
    content_hash: Optional[str] = None
