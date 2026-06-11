"""`run_audit` — audit ONE project's group of documents against its rules.

An audit project holds a single business's related documents in its own `docs/`
(报价单 + 收货单 + 订单 + …, any types) and a set of NL compliance rules. There
is NO multi-project anchor/source wiring — that was the matching (对账) model,
wrong for auditing one business's set. `run_audit` reads every document in the
project's `docs/`, sends each as an image (the source of truth) plus the rules,
and writes `audits/{run}/report.json`.

Documents do NOT need to be extracted — the judge reads the images directly; any
existing extracted fields are passed only as a hint. The judge model is resolved
from the project's own active model (provider-direct; never the agent's SDK).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.match.audit import audit_group
from app.match.audit_l1 import try_l1
from app.provider.base import ImageBlock, Provider
from app.schemas.match import AuditReport, RuleCheck
from app.tools.docs import list_docs, read_doc_image
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_audit_run_id
from app.workspace.paths import audit_result_path, audits_dir, prediction_draft_path

# Judge-trip page budget (multi-page audit, 2026-06-10). Generous enough for
# the real groups seen so far (报价单1 + 推文物料18 + 收货单3 + 订单1 = 23);
# the caps exist so one pathological 200-page PDF can't blow up the trip.
_MAX_PAGES_PER_DOC = 20
_MAX_TOTAL_PAGES = 40

# Idempotency window (2026-06-11): a dogfooded agent-brain loop re-called
# run_audit 4× with identical args, burning a full multi-page judge trip each
# time. Same docs + same rules version within this window → same verdict
# (modulo judge nondeterminism), so serve the fresh report instead of paying
# the judge again. Any loop source becomes a free no-op; a genuine re-audit
# (rules edited → version bump, docs added → group change) always re-runs.
_IDEMPOTENT_WINDOW_S = 120

# In-flight identical runs share one task (see run_audit body). Single-process
# asyncio server → a module dict is the whole registry.
_INFLIGHT: dict[tuple, "asyncio.Task[dict]"] = {}


class AuditError(Exception):
    """Audit precondition failure, carrying a stable error_code for the envelope."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.error_message_en = message


def _load_fields(workspace: Path, slug: str, filename: str) -> Optional[dict]:
    """First extracted entity for a doc, or None — OPTIONAL hint for audit, not a
    prerequisite."""
    p = prediction_draft_path(workspace, slug, filename)
    if not p.exists():
        return None
    try:
        ents = json.loads(p.read_text(encoding="utf-8")).get("entities")
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(ents, list):
        for e in ents:
            if isinstance(e, dict):
                return e
    return None


def _fresh_identical_report(
    workspace: Path, slug: str, rules_version: Optional[int],
    audited_shas: dict[str, str],
) -> Optional[dict]:
    """The latest report iff it is younger than the idempotency window AND was
    produced by the same rules version over the same doc CONTENTS (filename +
    sha — a re-uploaded doc under the same name must re-run). None = run."""
    if rules_version is None:
        return None
    import time

    adir = audits_dir(workspace, slug)
    reports = sorted(
        adir.glob("*/report.json"), key=lambda p: p.stat().st_mtime,
    ) if adir.is_dir() else []
    if not reports:
        return None
    p = reports[-1]
    if time.time() - p.stat().st_mtime > _IDEMPOTENT_WINDOW_S:
        return None
    try:
        rep = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if rep.get("rules_version") != rules_version:
        return None
    if rep.get("doc_shas") != audited_shas:
        return None
    return rep


async def run_audit(
    workspace: Path,
    slug: str,
    *,
    filenames: Optional[list[str]] = None,
    provider: Optional[Provider] = None,
    model_id: Optional[str] = None,
) -> dict[str, Any]:
    """Audit the project `slug`: read its audit rules + its documents, judge all
    rules in one LLM trip (images = source of truth, any extracted fields =
    hint), and persist the report. `filenames` restricts the audit to those docs
    (default: every doc in `docs/`) — useful when a project also holds unrelated
    files. Returns the report dict. Raises `AuditError` when rules or documents
    are missing."""
    from app.tools.match_prompt import MatchPromptNotFoundError, read_active_match_prompt
    try:
        mpv = await read_active_match_prompt(workspace, slug)
        audit_rules = list(mpv.audit_rules)
    except MatchPromptNotFoundError:
        audit_rules = []
    if not audit_rules:
        raise AuditError(
            "audit_no_rules", "no audit rules set — call write_audit_rules first",
        )

    rules_version = getattr(mpv, "version", None)

    docs = await list_docs(workspace, slug)
    want = set(filenames) if filenames else None
    audited_shas = {d["filename"]: str(d.get("sha256") or "")
                    for d in docs
                    if d.get("filename") and (want is None or d["filename"] in want)}

    # ── idempotency window: identical re-run seconds later → cached report ──
    cached = _fresh_identical_report(workspace, slug, rules_version, audited_shas)
    if cached is not None:
        cached["cached"] = True
        return cached

    # ── in-flight dedupe: the completed-report window above can't see a run
    # that is still judging. A client tool-timeout + retry (Cowork ~60s <
    # judge trip ~70s) lands here while #1 is mid-flight — without this, the
    # retry burned a second full judge trip (dogfood 2026-06-11: race lost by
    # 2 seconds). Identical key → await the SAME task; the task is shielded
    # so the first caller's disconnect doesn't kill the run for the second.
    key = (str(workspace.resolve()), slug, rules_version,
           tuple(sorted(audited_shas.items())))
    existing = _INFLIGHT.get(key)
    if existing is not None:
        report = dict(await asyncio.shield(existing))
        report["cached"] = True
        return report
    task = asyncio.create_task(_execute_audit(
        workspace, slug, audit_rules, rules_version, docs, want,
        audited_shas, provider, model_id,
    ))
    _INFLIGHT[key] = task
    task.add_done_callback(lambda _t: _INFLIGHT.pop(key, None))
    return await asyncio.shield(task)


async def _execute_audit(
    workspace: Path,
    slug: str,
    audit_rules: list,
    rules_version: Optional[int],
    docs: list[dict[str, Any]],
    want: Optional[set[str]],
    audited_shas: dict[str, str],
    provider: Optional[Provider],
    model_id: Optional[str],
) -> dict[str, Any]:
    doc_images: dict[str, list[ImageBlock]] = {}
    doc_fields: dict[str, dict] = {}
    total_pages = 0
    for d in docs:
        fn = d.get("filename")
        if not fn or (want is not None and fn not in want):
            continue
        # ALL pages go to the judge — rules routinely reference content past
        # page 1 (收货单 totals on p3, 推文物料 evidence on p10+). Images are
        # the cost driver, so cap per doc and per trip; over budget a doc
        # still contributes page 1 (silently dropping a whole doc from an
        # audit would be worse than a shallow read of it).
        page_count = int(d.get("page_count") or 1)
        budget = min(page_count, _MAX_PAGES_PER_DOC,
                     max(1, _MAX_TOTAL_PAGES - total_pages))
        blocks: list[ImageBlock] = []
        for page in range(1, budget + 1):
            try:
                out = await read_doc_image(workspace, slug, fn, page=page)
            except Exception:
                break  # past the last renderable page / unreadable doc
            blocks.append(ImageBlock(media_type=out["mime"], data_b64=out["data"]))
        if not blocks:
            continue  # skip docs that don't render to an image
        doc_images[fn] = blocks
        total_pages += len(blocks)
        fields = _load_fields(workspace, slug, fn)
        if fields is not None:
            doc_fields[fn] = fields

    if not doc_images:
        raise AuditError(
            "audit_no_docs",
            "project has no readable documents — upload the group (报价单/收货单/…) first",
        )

    # L1 fast path (A3): a rule with a structured `check` spec whose field refs
    # resolve against the extracted fields in hand is decided deterministically
    # — for free and explainably. Everything else (no spec, doc/field missing,
    # unparsable) goes to the judge in ONE trip; all-L1 = zero judge calls.
    decided: dict[int, RuleCheck] = {}
    pending: list[tuple[int, Any]] = []
    for i, rule in enumerate(audit_rules):
        rc = try_l1(rule, doc_fields)
        if rc is not None:
            decided[i] = rc
        else:
            pending.append((i, rule))

    if pending:
        if provider is None:
            provider, resolved_model = await _resolve_judge_provider(workspace, slug)
            model_id = model_id or resolved_model
        judged = await audit_group(
            doc_images=doc_images,
            audit_rules=[r for _, r in pending],
            doc_fields=doc_fields or None,
            provider=provider,
            model_id=model_id,
        )
        for (i, _), rc in zip(pending, judged):
            decided[i] = rc

    checks = [decided[i] for i in range(len(audit_rules))]
    # Tri-state overall: any critical fail → fail; only warning fails → warn;
    # otherwise pass (`unclear` never downgrades — surfaced separately).
    if any(c.status == "fail" and c.level == "critical" for c in checks):
        overall = "fail"
    elif any(c.status == "fail" for c in checks):
        overall = "warn"
    else:
        overall = "pass"

    run_id = new_audit_run_id()
    report = AuditReport(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        group={fn: fn for fn in doc_images},   # the documents that were audited
        checks=checks,
        overall=overall,
        rules_version=rules_version,
        doc_shas={fn: audited_shas.get(fn, "") for fn in doc_images},
    )
    out_path = audit_result_path(workspace, slug, run_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_path, report.model_dump(mode="json"))
    return report.model_dump(mode="json")


async def read_audit_report(workspace: Path, slug: str) -> dict[str, Any]:
    """The project's most recent audit report (`audits/{run}/report.json`),
    picked by report mtime with run_id as the tie-break. Raises
    `audit_no_report` when the project has never been audited.

    When the user left doodles on the board (D2, 2026-06-12 doodle plan), the
    report additionally carries `board_annotations` — the PURE-TEXT digest of
    `board_notes.json` (`{doc, page, kind, user_text?, region_text?}`, never a
    rect). Additive: the key is absent when there are no annotations, so
    existing consumers see the exact report.json shape. Living here (not in
    the @tool wrapper) means the HTTP twin `/audit/latest` and the MCP server
    inherit it for free — one function body, three surfaces.
    """
    reports = sorted(
        audits_dir(workspace, slug).glob("*/report.json"),
        key=lambda p: (p.stat().st_mtime, p.parent.name),
    ) if audits_dir(workspace, slug).is_dir() else []
    if not reports:
        raise AuditError(
            "audit_no_report", "project has no audit report yet — call run_audit first",
        )
    try:
        report = json.loads(reports[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise AuditError(
            "audit_no_report", "latest audit report is unreadable — re-run run_audit",
        )
    # Lazy import: audit_notes pulls in textlayer (fitz) — keep this module's
    # import graph light, same stance as the routes layer.
    from app.tools.audit_notes import digest_board_annotations

    digest = await digest_board_annotations(
        workspace, slug, str(report.get("run_id") or ""),
    )
    if digest:
        report["board_annotations"] = digest
    return report


async def _resolve_judge_provider(
    workspace: Path, slug: str,
) -> tuple[Optional[Provider], Optional[str]]:
    """(provider, model_id) for the judge from the project's own active model —
    provider-direct (extract/judge tier), never the agent's SDK. (None, None) if
    unresolvable → engine runs pure-`unclear`."""
    try:
        from app.provider import get_provider_for_model
        from app.tools.model import read_active_model

        mc = await read_active_model(workspace, slug)
        return get_provider_for_model(mc.provider_model_id, provider=mc.provider), mc.provider_model_id
    except Exception:
        return None, None
