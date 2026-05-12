from __future__ import annotations

import json as _json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server, tool

from app.provider.base import Provider
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import SchemaField
from app.tools import docs as docs_mod
from app.tools import extract as extract_mod
from app.tools import jobs as jobs_mod
from app.tools import predictions as predictions_mod
from app.tools import publish as publish_mod
from app.tools import projects as projects_mod
from app.tools import reviewed as reviewed_mod
from app.tools import score as score_mod
from app.tools import experiment as experiment_mod
from app.tools import model as model_mod
from app.tools import prompt as prompt_mod
from app.tools import schema as schema_mod

if TYPE_CHECKING:
    from app.jobs.runner import JobRunner


def build_emerge_mcp(
    workspace: Path,
    provider: Provider,
    job_runner: "JobRunner",
) -> McpSdkServerConfig:
    """Construct an in-process MCP server exposing all emerge tools.

    Each tool closes over the workspace path and provider instance so the
    SDK-driven agent doesn't need to know either.
    """

    @tool("create_project", "Create a new extraction project.", {"name": str})
    async def t_create_project(args: dict[str, Any]) -> dict[str, Any]:
        pid = await projects_mod.create_project(workspace, name=args["name"])
        return {"content": [{"type": "text", "text": pid}]}

    @tool("list_projects", "List all projects in the workspace.", {})
    async def t_list_projects(_args: dict[str, Any]) -> dict[str, Any]:
        items = await projects_mod.list_projects(workspace)
        return {"content": [{"type": "text", "text": str(items)}]}

    @tool(
        "upload_doc",
        "Register a previously-uploaded doc by its temp path. Returns doc_id. "
        "(For chat-driven uploads, the user uploads via the upload endpoint and the "
        "doc_ids are passed to this tool only when triggered programmatically.)",
        {"project_id": str, "tmp_path": str, "filename": str},
    )
    async def t_upload_doc(args: dict[str, Any]) -> dict[str, Any]:
        data = Path(args["tmp_path"]).read_bytes()
        did = await docs_mod.upload_doc(workspace, args["project_id"], data, args["filename"])
        return {"content": [{"type": "text", "text": did}]}

    @tool("list_docs", "List documents in a project.", {"project_id": str})
    async def t_list_docs(args: dict[str, Any]) -> dict[str, Any]:
        items = await docs_mod.list_docs(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": str(items)}]}

    @tool(
        "pdf_render_page",
        "Render a PDF page as PNG; returns the path.",
        {"project_id": str, "doc_id": str, "page": int},
    )
    async def t_pdf_render_page(args: dict[str, Any]) -> dict[str, Any]:
        p = await docs_mod.pdf_render_page(
            workspace, args["project_id"], args["doc_id"], page=args["page"]
        )
        return {"content": [{"type": "text", "text": str(p)}]}

    @tool(
        "derive_schema",
        "Propose a schema from sample documents and a user intent.",
        {"project_id": str, "sample_doc_ids": list, "intent": str},
    )
    async def t_derive_schema(args: dict[str, Any]) -> dict[str, Any]:
        fields = await schema_mod.derive_schema(
            workspace,
            args["project_id"],
            sample_doc_ids=args["sample_doc_ids"],
            intent=args["intent"],
            provider=provider,
        )
        return {"content": [{"type": "text", "text": str([f.model_dump(mode="json") for f in fields])}]}

    @tool("read_schema", "Read the current schema for a project.", {"project_id": str})
    async def t_read_schema(args: dict[str, Any]) -> dict[str, Any]:
        fields = await schema_mod.read_schema(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": str([f.model_dump(mode="json") for f in fields])}]}

    @tool(
        "write_schema",
        "Write a new schema. Set allow_structural=true to add/remove/rename/retype fields.",
        {"project_id": str, "schema": list, "reason": str, "allow_structural": bool},
    )
    async def t_write_schema(args: dict[str, Any]) -> dict[str, Any]:
        fields = [SchemaField(**f) for f in args["schema"]]
        await schema_mod.write_schema(
            workspace,
            args["project_id"],
            fields,
            reason=args["reason"],
            allow_structural=args.get("allow_structural", False),
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "write_prompt",
        "Write fields + global_notes to an existing prompt variant. "
        "prompt_id=null targets the active prompt. Use this instead of write_schema "
        "for any new code path — write_schema is the legacy wrapper.",
        {
            "project_id": str,
            "prompt_id": str,  # accept "" for None (claude-agent-sdk doesn't pass typed null)
            "schema": list,
            "global_notes": str,
        },
    )
    async def t_write_prompt(args: dict[str, Any]) -> dict[str, Any]:
        raw_pid_arg = args.get("prompt_id") or None  # "" → None
        fields = [SchemaField(**f) for f in args["schema"]]
        resolved = await prompt_mod.write_prompt(
            workspace,
            args["project_id"],
            prompt_id=raw_pid_arg,
            schema=fields,
            global_notes=args.get("global_notes", ""),
        )
        return {"content": [{"type": "text", "text": resolved}]}

    @tool(
        "create_prompt",
        "Create a new prompt variant by cloning either the current active prompt "
        "(derived_from='') or a specific prompt_id. Cross-project lineage strings "
        "({src_pid}/{src_prompt_id}) are recorded for display; actual cross-project "
        "import lands in M9.5.",
        {"project_id": str, "label": str, "derived_from": str},
    )
    async def t_create_prompt(args: dict[str, Any]) -> dict[str, Any]:
        derived = args.get("derived_from") or None
        new_id = await prompt_mod.create_prompt(
            workspace,
            args["project_id"],
            label=args["label"],
            derived_from=derived,
        )
        return {"content": [{"type": "text", "text": new_id}]}

    @tool(
        "switch_active_prompt",
        "Set the project's active prompt to the given prompt_id. Affects all "
        "subsequent reads of the active prompt (extract, freeze, etc).",
        {"project_id": str, "prompt_id": str},
    )
    async def t_switch_active_prompt(args: dict[str, Any]) -> dict[str, Any]:
        await prompt_mod.switch_active_prompt(
            workspace, args["project_id"], args["prompt_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "list_prompts",
        "List all prompt variants in a project with is_active flag.",
        {"project_id": str},
    )
    async def t_list_prompts(args: dict[str, Any]) -> dict[str, Any]:
        items = await prompt_mod.list_prompts(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": _json.dumps(items)}]}

    @tool(
        "delete_prompt",
        "Physically remove a prompt variant file. Cannot delete the active prompt "
        "(switch active first).",
        {"project_id": str, "prompt_id": str},
    )
    async def t_delete_prompt(args: dict[str, Any]) -> dict[str, Any]:
        await prompt_mod.delete_prompt(
            workspace, args["project_id"], args["prompt_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "write_model",
        "Upsert a model config (create if missing, otherwise update label/params/provider_model_id). "
        "provider is one of 'anthropic'|'openai'|'google'.",
        {
            "project_id": str,
            "model_id": str,
            "label": str,
            "provider": str,
            "provider_model_id": str,
            "params": dict,
        },
    )
    async def t_write_model(args: dict[str, Any]) -> dict[str, Any]:
        await model_mod.write_model(
            workspace,
            args["project_id"],
            model_id=args["model_id"],
            label=args["label"],
            provider=args["provider"],  # type: ignore[arg-type]
            provider_model_id=args["provider_model_id"],
            params=args.get("params") or {},
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "create_model",
        "Create a new model config with an auto-minted model_id. Returns the new model_id.",
        {
            "project_id": str,
            "label": str,
            "provider": str,
            "provider_model_id": str,
            "params": dict,
        },
    )
    async def t_create_model(args: dict[str, Any]) -> dict[str, Any]:
        new_mid = await model_mod.create_model(
            workspace,
            args["project_id"],
            label=args["label"],
            provider=args["provider"],  # type: ignore[arg-type]
            provider_model_id=args["provider_model_id"],
            params=args.get("params") or {},
        )
        return {"content": [{"type": "text", "text": new_mid}]}

    @tool(
        "switch_active_model",
        "Set the project's active model to the given model_id. Affects all "
        "subsequent extract calls when model_id arg is not explicitly provided.",
        {"project_id": str, "model_id": str},
    )
    async def t_switch_active_model(args: dict[str, Any]) -> dict[str, Any]:
        await model_mod.switch_active_model(
            workspace, args["project_id"], args["model_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "list_models",
        "List all model configs in a project with is_active flag.",
        {"project_id": str},
    )
    async def t_list_models(args: dict[str, Any]) -> dict[str, Any]:
        items = await model_mod.list_models(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": _json.dumps(items)}]}

    @tool(
        "delete_model",
        "Physically remove a model config file. Cannot delete the active model "
        "(switch active first).",
        {"project_id": str, "model_id": str},
    )
    async def t_delete_model(args: dict[str, Any]) -> dict[str, Any]:
        await model_mod.delete_model(
            workspace, args["project_id"], args["model_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "create_experiment",
        "Create an experiment referencing a (prompt_id, model_id) pair. Both axes "
        "default to the project's active. Returns the new experiment_id.",
        {"project_id": str, "label": str, "prompt_id": str, "model_id": str},
    )
    async def t_create_experiment(args: dict[str, Any]) -> dict[str, Any]:
        eid = await experiment_mod.create_experiment(
            workspace, args["project_id"],
            label=args.get("label") or None,
            prompt_id=args.get("prompt_id") or None,
            model_id=args.get("model_id") or None,
        )
        return {"content": [{"type": "text", "text": eid}]}

    @tool(
        "extract_with_experiment",
        "Run an experiment's (prompt, model) pair on a single doc; writes "
        "experiments/{experiment_id}/extracts/{doc_id}.json. Returns the payload.",
        {"project_id": str, "experiment_id": str, "doc_id": str},
    )
    async def t_extract_with_experiment(args: dict[str, Any]) -> dict[str, Any]:
        ex = await experiment_mod.read_experiment(
            workspace, args["project_id"], args["experiment_id"],
        )
        model = await model_mod.read_model(
            workspace, args["project_id"], ex.model_id,
        )
        from app.provider import get_provider_for_model
        exp_provider = get_provider_for_model(model.provider_model_id)
        payload = await experiment_mod.extract_with_experiment(
            workspace, args["project_id"], args["experiment_id"], args["doc_id"],
            provider=exp_provider,
        )
        return {"content": [{"type": "text", "text": _json.dumps(payload)}]}

    @tool(
        "run_experiment_eval",
        "Loop reviewed/ docs through the experiment's (prompt, model); writes "
        "per-doc extracts and computes overall + per-field + per-doc scores. "
        "Returns the eval dict and sets status='ran'.",
        {"project_id": str, "experiment_id": str},
    )
    async def t_run_experiment_eval(args: dict[str, Any]) -> dict[str, Any]:
        ex = await experiment_mod.read_experiment(
            workspace, args["project_id"], args["experiment_id"],
        )
        model = await model_mod.read_model(
            workspace, args["project_id"], ex.model_id,
        )
        from app.provider import get_provider_for_model
        exp_provider = get_provider_for_model(model.provider_model_id)
        ev = await experiment_mod.run_experiment_eval(
            workspace, args["project_id"], args["experiment_id"],
            provider=exp_provider,
        )
        return {"content": [{"type": "text", "text": _json.dumps(ev)}]}

    @tool(
        "promote_experiment",
        "Set the experiment's (prompt_id, model_id) as the project's active pair; "
        "clear predictions/_draft/ and re-seed from the experiment's extracts. "
        "Marks experiment status='promoted' (audit trail).",
        {"project_id": str, "experiment_id": str},
    )
    async def t_promote_experiment(args: dict[str, Any]) -> dict[str, Any]:
        await experiment_mod.promote_experiment(
            workspace, args["project_id"], args["experiment_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "archive_experiment",
        "Mark an experiment as archived (excluded from default lists, not deleted). "
        "Cannot archive a promoted experiment.",
        {"project_id": str, "experiment_id": str},
    )
    async def t_archive_experiment(args: dict[str, Any]) -> dict[str, Any]:
        await experiment_mod.archive_experiment(
            workspace, args["project_id"], args["experiment_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "list_experiments",
        "List experiments in a project. Archived experiments excluded unless "
        "include_archived=true.",
        {"project_id": str, "include_archived": bool},
    )
    async def t_list_experiments(args: dict[str, Any]) -> dict[str, Any]:
        rows = await experiment_mod.list_experiments(
            workspace, args["project_id"],
            include_archived=bool(args.get("include_archived", False)),
        )
        return {"content": [{"type": "text", "text": _json.dumps(rows)}]}

    @tool(
        "delete_experiment",
        "Physically remove an experiment directory. Cannot delete a promoted "
        "experiment (audit trail).",
        {"project_id": str, "experiment_id": str},
    )
    async def t_delete_experiment(args: dict[str, Any]) -> dict[str, Any]:
        await experiment_mod.delete_experiment(
            workspace, args["project_id"], args["experiment_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "extract_one",
        "Extract from a single document.",
        {"project_id": str, "doc_id": str},
    )
    async def t_extract_one(args: dict[str, Any]) -> dict[str, Any]:
        out = await extract_mod.extract_one(
            workspace, args["project_id"], args["doc_id"], provider=provider
        )
        return {"content": [{"type": "text", "text": str(out)}]}

    @tool(
        "extract_batch",
        "Extract over a list of documents (foreground).",
        {"project_id": str, "doc_ids": list},
    )
    async def t_extract_batch(args: dict[str, Any]) -> dict[str, Any]:
        summary = await extract_mod.extract_batch(
            workspace, args["project_id"], args["doc_ids"], provider=provider
        )
        return {"content": [{"type": "text", "text": str(summary)}]}

    @tool(
        "save_reviewed",
        "Save a corrected extraction as ground truth for a doc.",
        {
            "project_id": str,
            "doc_id": str,
            "entities": list,
            "source": str,  # "manual" | "feedback"
            "notes": dict,  # optional; pass {} if none
        },
    )
    async def t_save_reviewed(args: dict[str, Any]) -> dict[str, Any]:
        await reviewed_mod.save_reviewed(
            workspace,
            args["project_id"],
            args["doc_id"],
            entities=args["entities"],
            source=ReviewedSource(args.get("source", "manual")),
            notes=args.get("notes") or None,
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "list_reviewed",
        "List all reviewed examples in a project.",
        {"project_id": str},
    )
    async def t_list_reviewed(args: dict[str, Any]) -> dict[str, Any]:
        items = await reviewed_mod.list_reviewed(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": str(items)}]}

    @tool(
        "get_reviewed",
        "Get the reviewed payload for one doc or null if not reviewed.",
        {"project_id": str, "doc_id": str},
    )
    async def t_get_reviewed(args: dict[str, Any]) -> dict[str, Any]:
        payload = await reviewed_mod.get_reviewed(
            workspace, args["project_id"], args["doc_id"]
        )
        return {"content": [{"type": "text", "text": str(payload)}]}

    @tool(
        "get_prediction",
        "Get the latest draft prediction for a doc or null if not extracted.",
        {"project_id": str, "doc_id": str},
    )
    async def t_get_prediction(args: dict[str, Any]) -> dict[str, Any]:
        payload = await predictions_mod.get_prediction(
            workspace, args["project_id"], args["doc_id"]
        )
        text = _json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "score",
        "Compute precision/recall/F1 by comparing draft predictions against reviewed examples. Persists a metrics snapshot under metrics/eval_{ts}.json. Returns ScoreResult.",
        {"project_id": str},
    )
    async def t_score(args: dict[str, Any]) -> dict[str, Any]:
        result = await score_mod.run_eval(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": _json.dumps(result.model_dump(mode='json'))}]}

    @tool(
        "readiness_check",
        "Run the publish readiness checklist for a project.",
        {"project_id": str},
    )
    async def t_readiness_check(args: dict[str, Any]) -> dict[str, Any]:
        out = await publish_mod.readiness_check(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "contract_diff",
        "Diff current schema against the active version's frozen schema.",
        {"project_id": str},
    )
    async def t_contract_diff(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.schema import read_schema
        from app.workspace.paths import parse_version_id, project_json_path, version_path

        pid = args["project_id"]
        schema = await read_schema(workspace, pid)
        project = _json.loads(project_json_path(workspace, pid).read_text())
        active_version_id = project.get("active_version_id")
        if not active_version_id:
            out = {
                "added": [field.name for field in schema],
                "removed": [],
                "type_changed": [],
                "enum_narrowed": [],
                "is_breaking": False,
                "note": "no prior active version",
            }
        else:
            prev: list[SchemaField] = []
            n = parse_version_id(active_version_id)
            if n is not None and version_path(workspace, pid, n).exists():
                prev_blob = _json.loads(version_path(workspace, pid, n).read_text())
                prev = [SchemaField(**field) for field in prev_blob.get("schema", [])]
            out = publish_mod.contract_diff(prev, schema)
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "freeze_version",
        "Freeze the current schema as the next immutable versions/v{n}.json. GATED.",
        {"project_id": str},
    )
    async def t_freeze_version(args: dict[str, Any]) -> dict[str, Any]:
        try:
            out = await publish_mod.freeze_version(workspace, args["project_id"])
        except publish_mod.PublishNotReadyError as exc:
            out = {
                "error": {
                    "error_code": exc.error_code,
                    "error_message_en": exc.error_message_en,
                    "checks": exc.checks,
                }
            }
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "issue_api_key",
        "Issue or rotate an API key. Plaintext appears exactly once in this tool result.",
        {"project_id": str},
    )
    async def t_issue_api_key(args: dict[str, Any]) -> dict[str, Any]:
        out = await publish_mod.issue_api_key(workspace, args["project_id"])
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "start_job",
        "Kick off a background job. v1 supports skill='autoresearch'. Returns a job_id; subscribe to /lab/jobs/{job_id}/events for progress.",
        {"skill": str, "project_id": str, "params": dict},
    )
    async def t_start_job(args: dict[str, Any]) -> dict[str, Any]:
        jid = await jobs_mod.start_job_impl(
            job_runner, skill=args["skill"], project_id=args["project_id"],
            params=args.get("params") or {},
        )
        return {"content": [{"type": "text", "text": jid}]}

    @tool("get_job", "Get current job status (latest turn, best F1 so far).", {"job_id": str})
    async def t_get_job(args: dict[str, Any]) -> dict[str, Any]:
        info = await jobs_mod.get_job_impl(job_runner, job_id=args["job_id"])
        return {"content": [{"type": "text", "text": str(info)}]}

    @tool("pause_job", "Pause a running job at the next turn boundary.", {"job_id": str})
    async def t_pause_job(args: dict[str, Any]) -> dict[str, Any]:
        await jobs_mod.pause_job_impl(job_runner, job_id=args["job_id"])
        return {"content": [{"type": "text", "text": "paused"}]}

    @tool("resume_job", "Resume a paused job.", {"job_id": str})
    async def t_resume_job(args: dict[str, Any]) -> dict[str, Any]:
        await jobs_mod.resume_job_impl(job_runner, job_id=args["job_id"])
        return {"content": [{"type": "text", "text": "resumed"}]}

    @tool("cancel_job", "Cancel a running or paused job. Discards remaining turns.", {"job_id": str})
    async def t_cancel_job(args: dict[str, Any]) -> dict[str, Any]:
        await jobs_mod.cancel_job_impl(job_runner, job_id=args["job_id"])
        return {"content": [{"type": "text", "text": "cancelled"}]}

    return create_sdk_mcp_server(
        name="emerge_tools",
        version="0.0.1",
        tools=[
            t_create_project,
            t_list_projects,
            t_upload_doc,
            t_list_docs,
            t_pdf_render_page,
            t_derive_schema,
            t_read_schema,
            t_write_schema,
            t_write_prompt,
            t_create_prompt,
            t_switch_active_prompt,
            t_list_prompts,
            t_delete_prompt,
            t_write_model,
            t_create_model,
            t_switch_active_model,
            t_list_models,
            t_delete_model,
            t_create_experiment,
            t_extract_with_experiment,
            t_run_experiment_eval,
            t_promote_experiment,
            t_archive_experiment,
            t_list_experiments,
            t_delete_experiment,
            t_extract_one,
            t_extract_batch,
            t_save_reviewed,
            t_list_reviewed,
            t_get_reviewed,
            t_get_prediction,
            t_score,
            t_readiness_check,
            t_contract_diff,
            t_freeze_version,
            t_issue_api_key,
            t_start_job,
            t_get_job,
            t_pause_job,
            t_resume_job,
            t_cancel_job,
        ],
    )


_EMERGE_TOOL_NAMES = (
    "create_project", "list_projects", "upload_doc", "list_docs", "pdf_render_page",
    "derive_schema", "read_schema", "write_schema",
    "write_prompt", "create_prompt", "switch_active_prompt", "list_prompts", "delete_prompt",
    "write_model", "create_model", "switch_active_model", "list_models", "delete_model",
    "create_experiment", "extract_with_experiment", "run_experiment_eval",
    "promote_experiment", "archive_experiment", "list_experiments", "delete_experiment",
    "extract_one", "extract_batch",
    "save_reviewed", "list_reviewed", "get_reviewed", "get_prediction",
    "score",
    "start_job", "get_job", "pause_job", "resume_job", "cancel_job",
    "readiness_check", "contract_diff", "freeze_version", "issue_api_key",
)


def _emerge_tool_names() -> tuple[str, ...]:
    return _EMERGE_TOOL_NAMES
