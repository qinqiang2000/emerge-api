"""Pydantic models for extraction tool I/O.

`ExtractionOutput` is the wire format for extract_one tool output. Field name
`evidence` serializes as `_evidence` on the wire (LLM contract).

Evidence shape (field-source-grounding, 2026-05-29): each per-field evidence
entry is now ``{page, source}`` — ``page`` is the 1-based page where the value
was seen (``None`` for derived fields), ``source`` is an optional *verbatim*
quote (plain text, never coordinates) the model read the value from. The wire
form also accepts the legacy ``{field: page_int|null}`` shape; the validator
normalizes both into the internal ``{page, source}`` form so old reviewed /
prediction blobs on disk read without migration.

Hard rule: ``source`` is plain text only. No bbox / coordinates ever enter this
model (see CLAUDE.md hard rules + INSIGHTS #7).
"""

from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FieldEvidence(BaseModel):
    """Per-field grounding signal: page hint + optional verbatim source quote.

    ``page``: 1-based page number where the value was seen, ``None`` when the
    field is derived/inferred/absent. ``source``: the exact text fragment the
    model read the value from (≤120 chars, original language, no rewriting),
    ``None`` for derived fields. Never holds coordinates.
    """

    model_config = ConfigDict(populate_by_name=True)

    page: Optional[int] = None
    source: Optional[str] = None


def _coerce_entry(entry: dict) -> dict[str, FieldEvidence]:
    """Normalize one entity's raw evidence map into ``{field: FieldEvidence}``.

    Tolerates both the legacy ``{field: int|null}`` shape and the current
    ``{field: {page, source}}`` shape.
    """
    out: dict[str, FieldEvidence] = {}
    for field, raw in (entry or {}).items():
        if raw is None:
            out[field] = FieldEvidence(page=None, source=None)
        elif isinstance(raw, bool):
            # guard: bool is an int subclass; treat as absent
            out[field] = FieldEvidence(page=None, source=None)
        elif isinstance(raw, int):
            out[field] = FieldEvidence(page=raw, source=None)
        elif isinstance(raw, dict):
            out[field] = FieldEvidence(page=raw.get("page"), source=raw.get("source"))
        else:
            out[field] = FieldEvidence(page=None, source=None)
    return out


class ExtractionOutput(BaseModel):
    """Wire format for extract_one tool output.

    ``entities`` is the list of extracted records. ``evidence`` is an optional
    parallel list: for each entity, a map from field path → :class:`FieldEvidence`.
    Page is the only *positional* signal allowed; ``source`` is verbatim text
    (never bbox / coordinates).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entities: list[dict[str, Any]]
    # Internal normalized form: list[{field: FieldEvidence}].
    evidence: Optional[list[dict[str, FieldEvidence]]] = Field(
        default=None, alias="_evidence"
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_evidence(cls, data: Any) -> Any:
        """Coerce wire evidence (legacy int form OR {page, source}) → internal."""
        if not isinstance(data, dict):
            return data
        raw = data.get("_evidence", data.get("evidence"))
        if not isinstance(raw, list):
            return data
        normalized = [_coerce_entry(e if isinstance(e, dict) else {}) for e in raw]
        data = dict(data)
        data["_evidence"] = normalized
        data.pop("evidence", None)
        return data

    @model_validator(mode="after")
    def evidence_length_matches(self) -> "ExtractionOutput":
        if self.evidence is not None and len(self.evidence) != len(self.entities):
            raise ValueError("_evidence length must equal entities length")
        return self

    @property
    def evidence_entries(self) -> list[dict[str, FieldEvidence]]:
        """Evidence as field→FieldEvidence map per entity, empty list when absent."""
        return self.evidence or []

    @property
    def evidence_pages(self) -> list[dict[str, Optional[int]]]:
        """Backward-compatible page-only view: field→page map per entity.

        Existing call sites (extract click-to-page, surface, score round-trip)
        consume page ints; this keeps them working after the shape evolution.
        """
        return [
            {field: ev.page for field, ev in entry.items()}
            for entry in self.evidence_entries
        ]


def evidence_page(
    entry: Union[dict[str, FieldEvidence], dict[str, Any], None],
    field: str,
) -> Optional[int]:
    """Read a field's page hint, tolerant of both internal and raw shapes.

    Accepts a normalized ``{field: FieldEvidence}`` entry, or a raw on-disk
    entry (``{field: int|null}`` or ``{field: {page, source}}``). Returns the
    1-based page or ``None``.
    """
    if not entry:
        return None
    val = entry.get(field)
    if val is None:
        return None
    if isinstance(val, FieldEvidence):
        return val.page
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, dict):
        return val.get("page")
    return None


def evidence_source(
    entry: Union[dict[str, FieldEvidence], dict[str, Any], None],
    field: str,
) -> Optional[str]:
    """Read a field's verbatim source quote, tolerant of both shapes.

    Legacy int-only evidence has no source → returns ``None``.
    """
    if not entry:
        return None
    val = entry.get(field)
    if val is None:
        return None
    if isinstance(val, FieldEvidence):
        return val.source
    if isinstance(val, dict):
        return val.get("source")
    return None
