from __future__ import annotations

import json
from pathlib import Path

from app.schemas.schema_field import SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import schema_path


class StructuralChangeError(Exception):
    """Raised when write_schema is called without allow_structural=True
    but the change adds, removes, or renames a field, or changes its type."""


async def read_schema(workspace: Path, project_id: str) -> list[SchemaField]:
    raw = json.loads(schema_path(workspace, project_id).read_text())
    return [SchemaField(**f) for f in raw]


def _is_structural_change(old: list[SchemaField], new: list[SchemaField]) -> bool:
    old_map = {f.name: f.type for f in old}
    new_map = {f.name: f.type for f in new}
    if set(old_map.keys()) != set(new_map.keys()):
        return True
    for name in old_map:
        if old_map[name] != new_map[name]:
            return True
    return False


async def write_schema(
    workspace: Path,
    project_id: str,
    schema: list[SchemaField],
    *,
    reason: str,
    allow_structural: bool = False,
) -> None:
    async with project_lock(workspace, project_id):
        sp = schema_path(workspace, project_id)
        if sp.exists():
            old = [SchemaField(**f) for f in json.loads(sp.read_text())]
            if _is_structural_change(old, schema) and not allow_structural:
                raise StructuralChangeError(
                    "structural change requires allow_structural=True (gated by agent)"
                )
        payload = [f.model_dump(mode="json") for f in schema]
        atomic_write_json(sp, payload)
