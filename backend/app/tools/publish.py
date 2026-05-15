from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.schema_field import SchemaField
from app.security.keys import (
    generate_key,
    get_keystore,
    key_hash_short,
    key_prefix_display,
    sha256_key,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_published_id
from app.workspace.lock import project_lock
from app.workspace.paths import (
    jobs_dir,
    metrics_dir,
    next_version_n,
    predictions_draft_dir,
    project_json_path,
    published_dir,
    published_path,
    reviewed_dir,
    version_path,
)
from app.workspace.paths import parse_version_id


_log = logging.getLogger(__name__)


def contract_diff(
    prev: list[SchemaField],
    candidate: list[SchemaField],
) -> dict[str, Any]:
    """Top-level backward-compatibility diff for publish gating."""
    prev_by_name = {f.name: f for f in prev}
    cand_by_name = {f.name: f for f in candidate}

    added = sorted(set(cand_by_name) - set(prev_by_name))
    removed = sorted(set(prev_by_name) - set(cand_by_name))

    type_changed: list[dict[str, str]] = []
    enum_narrowed: list[dict[str, Any]] = []
    for name in sorted(set(prev_by_name) & set(cand_by_name)):
        before = prev_by_name[name]
        after = cand_by_name[name]
        if before.type != after.type:
            type_changed.append({
                "name": name,
                "prev_type": before.type.value,
                "candidate_type": after.type.value,
            })
            continue

        prev_enum = before.enum
        cand_enum = after.enum
        if prev_enum is None and cand_enum is not None:
            enum_narrowed.append({
                "name": name,
                "prev_enum": None,
                "candidate_enum": list(cand_enum),
            })
        elif prev_enum is not None and cand_enum is not None:
            if not set(prev_enum).issubset(set(cand_enum)):
                enum_narrowed.append({
                    "name": name,
                    "prev_enum": list(prev_enum),
                    "candidate_enum": list(cand_enum),
                })

    is_breaking = bool(removed or type_changed or enum_narrowed)
    return {
        "added": added,
        "removed": removed,
        "type_changed": type_changed,
        "enum_narrowed": enum_narrowed,
        "is_breaking": is_breaking,
    }


def _last_event_type(jsonl_path: Path) -> str | None:
    try:
        text = jsonl_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    lines = [line for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        return obj.get("type")
    return None


def _load_reviewed(workspace: Path, slug: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    rd = reviewed_dir(workspace, slug)
    if not rd.exists():
        return out
    for path in sorted(rd.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        out[path.stem] = blob.get("entities", [])
    return out


def _load_predictions(workspace: Path, slug: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    pd = predictions_draft_dir(workspace, slug)
    if not pd.exists():
        return out
    for path in sorted(pd.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        out[path.stem] = blob.get("entities", [])
    return out


async def readiness_check(workspace: Path, slug: str) -> dict[str, Any]:
    """Run publish hard gates and soft warnings for the current lab schema."""
    from app.tools.schema import read_schema
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, slug)
    schema = await read_schema(workspace, slug)
    project = json.loads(project_json_path(workspace, slug).read_text(encoding="utf-8"))
    threshold = float(project.get("publish_min_macro_f1") or 0.7)
    active_vid = project.get("active_version_id")

    checks: list[dict[str, Any]] = []
    soft_warnings: list[dict[str, Any]] = []
    macro_f1: float | None = None
    per_field: list[Any] = []

    checks.append({
        "key": "schema_non_empty",
        "status": "pass" if schema else "fail",
        "detail": f"{len(schema)} fields" if schema else "schema is empty",
    })

    reviewed = _load_reviewed(workspace, slug)
    n_reviewed = len(reviewed)
    if n_reviewed < 3:
        checks.append({
            "key": "reviewed_and_f1",
            "status": "fail",
            "detail": f"need >=3 reviewed examples; have {n_reviewed}",
        })
    elif not schema:
        checks.append({
            "key": "reviewed_and_f1",
            "status": "fail",
            "detail": "schema empty; cannot compute F1",
        })
    else:
        from app.tools.score import score

        result = score(schema, _load_predictions(workspace, slug), reviewed)
        per_field = result.per_field
        supported = [field_score for field_score in per_field if field_score.support > 0]
        macro_f1 = (
            sum(field_score.f1 for field_score in supported) / len(supported)
            if supported else result.macro_f1
        )
        if macro_f1 < threshold:
            checks.append({
                "key": "reviewed_and_f1",
                "status": "fail",
                "detail": f"macro_f1={macro_f1:.3f} < threshold {threshold}",
            })
        else:
            checks.append({
                "key": "reviewed_and_f1",
                "status": "pass",
                "detail": f"macro_f1={macro_f1:.3f} (threshold {threshold}); n_reviewed={n_reviewed}",
            })

    schema_field_names = {field.name for field in schema}
    orphans: set[str] = set()
    for entities in reviewed.values():
        for entity in entities:
            for key in entity:
                if not key.startswith("_") and key not in schema_field_names:
                    orphans.add(key)
    checks.append({
        "key": "reviewed_fields_in_schema",
        "status": "fail" if orphans else "pass",
        "detail": (
            f"reviewed fields not in current schema: {sorted(orphans)}"
            if orphans else "all reviewed fields are in schema"
        ),
    })

    running: list[str] = []
    jd = jobs_dir(workspace, slug)
    if jd.exists():
        for path in sorted(jd.glob("*.jsonl")):
            event_type = _last_event_type(path)
            if event_type and event_type not in {"ended", "cancelled", "error"}:
                running.append(path.stem)
    checks.append({
        "key": "no_running_jobs",
        "status": "fail" if running else "pass",
        "detail": f"running jobs: {running}" if running else "no running jobs",
    })

    if active_vid:
        n = parse_version_id(active_vid)
        if n is None or not version_path(workspace, slug, n).exists():
            checks.append({
                "key": "contract_diff_compat",
                "status": "fail",
                "detail": f"active_version_id={active_vid} but {active_vid}.json missing",
            })
        else:
            prev_blob = json.loads(version_path(workspace, slug, n).read_text(encoding="utf-8"))
            prev_schema = [SchemaField(**field) for field in prev_blob.get("schema", [])]
            diff = contract_diff(prev_schema, schema)
            if diff["is_breaking"]:
                checks.append({
                    "key": "contract_diff_compat",
                    "status": "fail",
                    "detail": (
                        f"breaking changes vs {active_vid}: "
                        f"removed={diff['removed']}, "
                        f"type_changed={diff['type_changed']}, "
                        f"enum_narrowed={diff['enum_narrowed']}"
                    ),
                })
            else:
                detail = (
                    f"additive vs {active_vid}: added={diff['added']}"
                    if diff["added"] else f"no changes vs {active_vid}"
                )
                checks.append({"key": "contract_diff_compat", "status": "pass", "detail": detail})
    else:
        checks.append({
            "key": "contract_diff_compat",
            "status": "pass",
            "detail": "no prior active version (first publish)",
        })

    if macro_f1 is not None and threshold <= macro_f1 < 0.85:
        soft_warnings.append({
            "key": "f1_borderline",
            "status": "warn",
            "detail": f"macro_f1={macro_f1:.3f} in [{threshold}, 0.85); consider /improve before publish",
        })
    for field_score in per_field:
        if field_score.support == 0:
            soft_warnings.append({
                "key": "field_zero_support",
                "status": "warn",
                "detail": f"field '{field_score.field}' has 0 support in reviewed set (untested)",
            })
    md = metrics_dir(workspace, slug)
    if md.exists() and schema:
        evals = sorted(md.glob("eval_*.json"))
        if evals:
            last = json.loads(evals[-1].read_text(encoding="utf-8"))
            if last.get("schema_field_count") != len(schema):
                soft_warnings.append({
                    "key": "eval_stale",
                    "status": "warn",
                    "detail": "schema field count changed since last /eval; consider /eval",
                })

    hard_pass = all(check["status"] == "pass" for check in checks)
    return {
        "checks": checks,
        "soft_warnings": soft_warnings,
        "hard_pass": hard_pass,
        "macro_f1": macro_f1,
        "n_reviewed": n_reviewed,
    }


class PublishNotReadyError(Exception):
    """Raised when freeze_version is called before readiness hard gates pass."""

    def __init__(
        self,
        *,
        error_code: str,
        error_message_en: str,
        checks: list[dict] | None = None,
    ) -> None:
        self.error_code = error_code
        self.error_message_en = error_message_en
        self.checks = checks or []
        super().__init__(error_message_en)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def freeze_version(
    workspace: Path, slug: str, *, force: bool = False,
) -> dict[str, str]:
    """Freeze current lab state into both a lab-side `versions/v{n}.json` and
    a workspace-level frozen artifact at `_published/{pub_xxx}.json`.

    Two artifacts, two audiences:
      * `versions/v{n}.json` — the *lab* publish lineage. Lives inside the
        project folder, so a project rename moves it; a project delete removes
        it. Powers `contract_diff` for next-publish gating.
      * `_published/{pub_xxx}.json` — the *frozen artifact* the public
        `POST /v1/extract` endpoint serves. Self-contained `{schema, model_id,
        params, global_notes, …}` so it survives project rename/delete and so
        emerge can hand its content off to a separate production deployment
        verbatim. Immutable (`chmod 0o444`).

    `project.json.published_ids` is appended in time order so the UI can list
    "current" + history without re-scanning `_published/`.

    Returns `{version_id, published_id}`."""
    from app.tools.model import read_active_model
    from app.tools.prompt import read_active_prompt
    from app.workspace.migrate import migrate_project_if_needed

    if not force:
        readiness = await readiness_check(workspace, slug)
        if not readiness["hard_pass"]:
            failed = [check for check in readiness["checks"] if check["status"] == "fail"]
            raise PublishNotReadyError(
                error_code="not_ready",
                error_message_en=f"readiness checks failed: {[check['key'] for check in failed]}",
                checks=readiness["checks"],
            )

    await migrate_project_if_needed(workspace, slug)

    async with project_lock(workspace, slug):
        pv = await read_active_prompt(workspace, slug)
        mc = await read_active_model(workspace, slug)
        schema_blob = [f.model_dump(mode="json") for f in pv.schema]

        pj_path = project_json_path(workspace, slug)
        project_blob = json.loads(pj_path.read_text(encoding="utf-8"))
        pid = project_blob.get("project_id")

        n = next_version_n(workspace, slug)
        version_id = f"v{n}"
        target = version_path(workspace, slug, n)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target, {
            "version_id": version_id,
            "schema": schema_blob,
            "global_notes": pv.global_notes,
            "provider": mc.provider,
            "model_id": mc.provider_model_id,
            "params": mc.params,
            "frozen_at": _iso_now(),
            "derived_from": {
                "prompt_id": pv.prompt_id,
                "model_id": mc.model_id,
                "experiment_id": None,
            },
        })
        target.chmod(0o444)

        # Mint and write the workspace-level frozen artifact. The dir lives at
        # the workspace root so it survives project rename/delete, matching
        # the "emerge mirrors prod" story for the public extract endpoint.
        published_id = new_published_id()
        published_dir(workspace).mkdir(parents=True, exist_ok=True)
        pub_target = published_path(workspace, published_id)
        atomic_write_json(pub_target, {
            "published_id": published_id,
            "source_project_slug": slug,
            "source_project_id": pid,
            "source_version_id": version_id,
            "schema": schema_blob,
            "global_notes": pv.global_notes,
            "provider": mc.provider,
            "model_id": mc.provider_model_id,
            "params": mc.params,
            "created_at": _iso_now(),
        })
        pub_target.chmod(0o444)

        project_blob["active_version_id"] = version_id
        ids = project_blob.get("published_ids")
        if not isinstance(ids, list):
            ids = []
        ids.append(published_id)
        project_blob["published_ids"] = ids
        atomic_write_json(pj_path, project_blob)

    return {"version_id": version_id, "published_id": published_id}


async def issue_api_key(
    workspace: Path, *, user_id: str = "default",
) -> dict[str, str]:
    """Mint and persist a new hashed API key row for `user_id`.

    Keys are user-scoped (not project-scoped): one live key per `(user_id,
    scope)` pair calls *any* `published_id` the user wants. `user_id="default"`
    is the single-user placeholder until a real user system lands. The
    plaintext is returned exactly once — callers must surface it through a
    one-time reveal UI and never persist it server-side."""
    plaintext = generate_key()
    h = sha256_key(plaintext)
    store = get_keystore(workspace)
    store.upsert_for_user(user_id, plaintext, scope="extract")
    _log.info(
        "issued api key for user=%s: prefix=%s hash_short=%s",
        user_id,
        key_prefix_display(plaintext),
        key_hash_short(h),
    )
    return {
        "key_plaintext": plaintext,
        "key_hash": h,
        "key_prefix": key_prefix_display(plaintext),
        "created_at": _iso_now(),
    }
