"""Pydantic models for the document-matching (一锚多源核对) layer.

A *match project* references one **anchor** extract project (the primary
document — e.g. the invoice) and a set of **source** extract projects (the
corroborating documents — payment / PO / GRN …). The match prompt declares,
per source, which anchor field maps to which source field and with what
tolerance. `run_match` pairs each anchor doc against the best candidate in
every source and emits a per-anchor "reconcile card".

P0 implements anchor + 1 source; the data model already supports N sources
(`mappings` is keyed by source slug, a card holds a list of pairs).

Hard rules honoured here: these are pure data shapes — no bbox, no document
body, only field values flow through. The `MatchPromptVariant` mirrors
`PromptVariant`'s version-on-change discipline (it cannot reuse the class —
`PromptVariant` is `extra="forbid"` and welds in a `schema` field).
"""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, model_validator


class Tol(BaseModel):
    """Per-key-pair tolerance. `type` picks the comparison primitive:
    - `exact`   — unicode-canonical + id/code casefold equality (no extra args)
    - `number`  — numeric equality within `abs` (default 0.0 = exact number)
    - `date_days` — date equality within `days` calendar days (default 0)
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["exact", "number", "date_days"]
    abs: Optional[float] = None
    days: Optional[int] = None


class KeyMapping(BaseModel):
    """One anchor-field ↔ source-field correspondence with its tolerance."""

    model_config = ConfigDict(extra="forbid")

    anchor: str
    source: str
    tol: Tol


class L1FieldRef(BaseModel):
    """A reference to one extracted field of one document in the audited group.

    `doc` matches the document by exact filename or by UNIQUE substring
    ("报价单" matches `报价单.pdf`); `field` is the extracted field name. A ref
    that fails to resolve (0/many doc hits, field absent) silently sends the
    whole rule to the judge — never an error, never a "extract first" demand.
    """

    model_config = ConfigDict(extra="forbid")

    doc: str
    field: str


# A side of an L1 comparison: a field reference or a literal constant.
L1Operand = Union[L1FieldRef, str, int, float]


class L1Check(BaseModel):
    """Optional deterministic spec attached to an audit rule (the L1 fast path).

    Two shapes, discriminated by `type`:
    - `eq`    — `left` == `right` (each a field ref or constant); numbers are
      normalized (currency symbols / thousands separators stripped) and compared
      within `tol`; dates compared by calendar day; otherwise unicode-canonical
      string equality.
    - `range` — `low` <= `value` <= `high` (each a field ref or constant);
      holds for numbers and dates.

    When the spec can't be evaluated (doc/field unresolvable, values unparsable
    for `range`), the rule falls through to the LLM judge unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["eq", "range"]
    # eq operands
    left: Optional[L1Operand] = None
    right: Optional[L1Operand] = None
    tol: Optional[float] = None
    # range operands
    value: Optional[L1Operand] = None
    low: Optional[L1Operand] = None
    high: Optional[L1Operand] = None

    @model_validator(mode="after")
    def _required_operands(self) -> "L1Check":
        if self.type == "eq":
            if self.left is None or self.right is None:
                raise ValueError("eq check requires `left` and `right`")
        else:  # range
            if self.value is None or self.low is None or self.high is None:
                raise ValueError("range check requires `value`, `low` and `high`")
        return self


class AuditRule(BaseModel):
    """One audit rule. The NL `rule` TEXT is the rule's identity (A2 ground
    truth is keyed by it — changing `level`/`check` never detaches a truth;
    rewording `rule` does). A bare string coerces to a critical rule with no
    check, so legacy `audit_rules: list[str]` JSON loads unchanged."""

    model_config = ConfigDict(extra="forbid")

    rule: str
    level: Literal["critical", "warning"] = "critical"
    check: Optional[L1Check] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_str(cls, v):
        if isinstance(v, str):
            return {"rule": v}
        return v


class MatchPromptVariant(BaseModel):
    """Versioned match-rule carrier — the match twin of `PromptVariant`.

    `mappings` is keyed by source-project slug; each value is the list of
    key correspondences for that source. `rules` is free-form NL (the L2
    judge tie-breaker context + human-readable doc), the match analogue of a
    prompt's `global_notes`. `version` + `content_hash` follow the same
    bump-on-content-change discipline `write_prompt` uses.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    prompt_id: str
    label: str = ""
    mappings: dict[str, list[KeyMapping]] = {}
    rules: str = ""
    # Audit layer (A0/A3): compliance rules judged over a grouped set of docs.
    # Each entry is one rule — NL text + optional level/L1 check (a bare string
    # coerces via AuditRule). Distinct from `rules` (which is the pairing
    # tie-break context). Empty = pure matching, no audit.
    audit_rules: list[AuditRule] = []
    derived_from: Optional[str] = None
    created_at: str
    updated_at: str
    version: int = 1
    content_hash: Optional[str] = None


class PairVerdict(BaseModel):
    """The judgement for one anchor-doc ↔ one source's chosen doc.

    `doc` is the matched source filename (None when no candidate cleared the
    threshold → `status="missing"`). `score` is matched_keys / total_keys.
    """

    model_config = ConfigDict(extra="forbid")

    source: str
    doc: Optional[str] = None
    status: Literal["match", "mismatch", "missing"]
    mismatched_fields: list[str] = []
    reason: Optional[str] = None
    score: float = 0.0


class MatchCard(BaseModel):
    """One anchor document's whole reconcile picture — a pair per source.

    `overall`: all sources matched → `complete`; some matched / some missing
    or mismatched → `partial`; nothing matched at all → `unmatched`.
    """

    model_config = ConfigDict(extra="forbid")

    anchor_doc: str
    pairs: list[PairVerdict] = []
    overall: Literal["complete", "partial", "unmatched"]


class MatchResult(BaseModel):
    """The full output of one `run_match` — a card per anchor doc plus the
    per-source orphans (source docs no anchor claimed)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: str
    anchor_project: str
    source_projects: list[str] = []
    cards: list[MatchCard] = []
    orphans: dict[str, list[str]] = {}


# --- audit layer (A0) -------------------------------------------------------

class AuditEvidence(BaseModel):
    """One verbatim source citation backing a rule verdict: a TEXT quote
    (≤120 chars, original language, never rewritten) read off document `doc`,
    with `page` when the doc was presented with page labels (None otherwise).
    Evidence is TEXT ONLY — NEVER coordinates (bbox red line: coordinates live
    only in the review/board render layer, never in prompts or tool results)."""

    model_config = ConfigDict(extra="forbid")

    doc: str
    page: Optional[int] = None
    quote: str


class RuleCheck(BaseModel):
    """One compliance rule's verdict over a grouped set of docs. `unclear` is a
    first-class status (the judge couldn't decide / the image was illegible) —
    never silently coerced to fail. `level` mirrors the rule's severity;
    `decided_by` records whether the deterministic L1 fast path or the LLM
    judge produced the verdict. `evidence` is additive-optional (pre-2026-06-11
    report JSON has no key → defaults to [])."""

    model_config = ConfigDict(extra="forbid")

    rule: str
    status: Literal["pass", "fail", "unclear"]
    reason: str = ""
    level: Literal["critical", "warning"] = "critical"
    decided_by: Literal["l1", "judge"] = "judge"
    evidence: list[AuditEvidence] = []


class AuditReport(BaseModel):
    """The output of one `run_audit` over a single grouped set of documents.

    `group` records which doc played each role (anchor slug / source slugs →
    filename). `overall` (A3 tri-state): any critical rule failed → `fail`;
    only warning rules failed → `warn`; else `pass` (`unclear` never
    downgrades, it is surfaced separately)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: str
    group: dict[str, str]                 # role(slug) → filename
    checks: list[RuleCheck] = []
    overall: Literal["pass", "warn", "fail"]
    # Idempotency-window key (None on pre-2026-06-11 reports → never
    # cache-hit): which rules version produced this report, and the sha256 of
    # each audited doc — replacing a doc under the same filename (e.g. the
    # re-stamped 报价单) must bypass the cache.
    rules_version: Optional[int] = None
    doc_shas: Optional[dict[str, str]] = None
