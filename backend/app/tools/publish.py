from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.schema_field import SchemaField
from app.workspace.paths import (
    jobs_dir,
    metrics_dir,
    predictions_draft_dir,
    project_dir,
    project_json_path,
    reviewed_dir,
    schema_path,
    version_path,
)
from app.workspace.paths import parse_version_id


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


def _global_notes_path(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "global_notes.md"


def _load_reviewed(workspace: Path, project_id: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    rd = reviewed_dir(workspace, project_id)
    if not rd.exists():
        return out
    for path in sorted(rd.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        out[path.stem] = blob.get("entities", [])
    return out


def _load_predictions(workspace: Path, project_id: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    pd = predictions_draft_dir(workspace, project_id)
    if not pd.exists():
        return out
    for path in sorted(pd.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        out[path.stem] = blob.get("entities", [])
    return out


async def readiness_check(workspace: Path, project_id: str) -> dict[str, Any]:
    """Run publish hard gates and soft warnings for the current lab schema."""
    schema_blob = json.loads(schema_path(workspace, project_id).read_text(encoding="utf-8"))
    schema = [SchemaField(**field) for field in schema_blob]
    project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
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

    reviewed = _load_reviewed(workspace, project_id)
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

        result = score(schema, _load_predictions(workspace, project_id), reviewed)
        macro_f1 = result.macro_f1
        per_field = result.per_field
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
    jd = jobs_dir(workspace, project_id)
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
        if n is None or not version_path(workspace, project_id, n).exists():
            checks.append({
                "key": "contract_diff_compat",
                "status": "fail",
                "detail": f"active_version_id={active_vid} but {active_vid}.json missing",
            })
        else:
            prev_blob = json.loads(version_path(workspace, project_id, n).read_text(encoding="utf-8"))
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
    md = metrics_dir(workspace, project_id)
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
