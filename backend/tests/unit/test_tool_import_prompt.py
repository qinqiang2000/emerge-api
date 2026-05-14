from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.tools.prompt import (
    PromptNotFoundError,
    import_prompt,
    read_prompt,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    project_json_path,
    prompt_path,
    prompts_dir,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed(workspace: Path, pid: str, prompts: dict[str, dict]) -> None:
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "name": pid,
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": None,
    })
    for prompt_id, fields_blob in prompts.items():
        atomic_write_json(prompt_path(workspace, pid, prompt_id), {
            "prompt_id": prompt_id,
            "label": fields_blob.get("label", prompt_id),
            "schema": fields_blob.get("schema", []),
            "global_notes": fields_blob.get("global_notes", ""),
            "derived_from": None,
            "created_at": _now(),
            "updated_at": _now(),
        })


async def test_import_prompt_copies_schema_and_notes(workspace: Path) -> None:
    src_pid = "p_src111111111"
    dst_pid = "p_dst222222222"
    _seed(workspace, src_pid, {
        "pr_baseline": {
            "label": "US baseline",
            "schema": [
                {"name": "invoice_no", "type": "string", "description": "d", "required": False},
            ],
            "global_notes": "us notes",
        },
    })
    _seed(workspace, dst_pid, {
        "pr_baseline": {"label": "dst baseline", "schema": []},
    })

    new_id = await import_prompt(
        workspace,
        src_slug=src_pid, src_prompt_id="pr_baseline",
        into_slug=dst_pid,
        new_label="from US",
    )

    # New id is freshly minted, not "pr_baseline" (would collide)
    assert new_id.startswith("pr_") and new_id != "pr_baseline"

    pv = await read_prompt(workspace, dst_pid, new_id)
    assert pv.label == "from US"
    assert pv.schema[0].name == "invoice_no"
    assert pv.global_notes == "us notes"
    assert pv.derived_from == f"{src_pid}/pr_baseline"
    assert pv.prompt_id == new_id


async def test_import_prompt_label_defaults_to_src_label(workspace: Path) -> None:
    src_pid = "p_src111111111"
    dst_pid = "p_dst222222222"
    _seed(workspace, src_pid, {"pr_baseline": {"label": "US baseline"}})
    _seed(workspace, dst_pid, {"pr_baseline": {"label": "dst"}})

    new_id = await import_prompt(
        workspace,
        src_slug=src_pid, src_prompt_id="pr_baseline",
        into_slug=dst_pid,
    )
    pv = await read_prompt(workspace, dst_pid, new_id)
    assert pv.label == "US baseline"


async def test_import_prompt_missing_src_raises(workspace: Path) -> None:
    src_pid = "p_src111111111"
    dst_pid = "p_dst222222222"
    _seed(workspace, src_pid, {"pr_baseline": {}})
    _seed(workspace, dst_pid, {"pr_baseline": {}})
    with pytest.raises(PromptNotFoundError):
        await import_prompt(
            workspace,
            src_slug=src_pid, src_prompt_id="pr_does_not_exist",
            into_slug=dst_pid,
        )


async def test_import_prompt_missing_dest_raises(workspace: Path) -> None:
    src_pid = "p_src111111111"
    _seed(workspace, src_pid, {"pr_baseline": {}})
    with pytest.raises(PromptNotFoundError):
        await import_prompt(
            workspace,
            src_slug=src_pid, src_prompt_id="pr_baseline",
            into_slug="dst-does-not-exist",
        )
