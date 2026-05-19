from __future__ import annotations

import json as _json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server, tool

from app.provider.base import Provider
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import SchemaField
from app.tools import ask_user as ask_user_mod
from app.tools import docs as docs_mod
from app.tools import extract as extract_mod
from app.tools import jobs as jobs_mod
from app.tools import pre_label as pre_label_mod
from app.tools import promote as promote_mod
from app.tools import publish as publish_mod
from app.tools import projects as projects_mod
from app.tools import reviewed as reviewed_mod
from app.tools import score as score_mod
from app.tools import experiment as experiment_mod
from app.tools import model as model_mod
from app.tools import prompt as prompt_mod
from app.tools import schema as schema_mod
from app.tools import surface_state as surface_state_mod
from app.tools import ui_actions as ui_actions_mod

if TYPE_CHECKING:
    from app.jobs.runner import JobRunner


# Sentinel slug used by the unbound-chat flow (mirrors `chat/service.py:
# _UNBOUND_SLUG`). Tools that require a real project context refuse to run
# against this slug and surface a structured `chat_not_bound` error so the
# agent (per skill guidance) prompts the user to create a project first
# instead of silently failing or — worse — minting one without confirmation.
_UNBOUND_SLUG = "_chats"


def _chat_not_bound_error(tool_name: str) -> dict[str, Any]:
    """Structured payload returned when a project-scoped tool is invoked from
    an unbound chat. The agent reads `error_code` to route its reply (see
    `app/skills/emerge_extractor.md` "Unbound chat" section)."""
    return {
        "ok": False,
        "error": {
            "error_code": "chat_not_bound",
            "error_message_en": (
                f"`{tool_name}` requires a project — this chat is not bound "
                "to one yet. Ask the user for a project name, then call "
                "`create_project(name=..., from_unbound_chat_id=...)` (or "
                "`promote_chat_to_project`)."
            ),
        },
    }


def build_emerge_mcp(
    workspace: Path,
    provider: Provider,
    job_runner: "JobRunner",
) -> McpSdkServerConfig:
    """Construct an in-process MCP server exposing emerge's business tools.

    Step B (SDK reframe) cut the filesystem-wrapper tools — ls/cp/rm/cat
    replacements (`list_docs`, `upload_doc`, `delete_doc`, `read_schema`,
    `list_projects`, `list_prompts`, `list_models`, `list_reviewed`,
    `list_experiments`, `get_prediction`, `get_reviewed`, `get_pending`,
    `rename_project`, `ingest_local_path`, `import_prompt`,
    `create_prompt`, `write_prompt`, `delete_prompt`,
    `create_model`, `write_model`, `delete_model`,
    `archive_experiment`, `delete_experiment`) — and rely on the Claude
    Agent SDK's built-in Bash/Glob/Grep/Read/Write/Edit instead, gated by
    the three-tier permission stack in `chat/sdk_settings.json` +
    `_workspace_safety_gate`. What stays here is the business moat: schema
    + version atomicity, provider-bound extract/label, doc vision,
    lifecycle ops with audit trails, and the UI-action bridge.

    Every tool that needs a project handle takes a `slug` — the
    human-readable folder name (`us-invoice`, `美国发票`) — never the opaque
    `p_xxx` pid. The pid is internal audit metadata persisted only inside
    `project.json` and chat/jobs jsonl event streams.
    """

    @tool(
        "create_project",
        "Create a new extraction project. When called from inside an "
        "unbound chat (CURRENT_PROJECT_DIR empty), pass "
        "`from_unbound_chat_id=<your chat_id>` so the chat's history + "
        "attachments are atomically relocated under the new project's slug; "
        "the unbound chat is then tombstoned and you operate in the new "
        "project context for the rest of the turn. ALWAYS ask the user for a "
        "name first — never silently bind a chat on their behalf.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "from_unbound_chat_id": {"type": "string"},
            },
            "required": ["name"],
        },
    )
    async def t_create_project(args: dict[str, Any]) -> dict[str, Any]:
        out = await projects_mod.create_project(
            workspace,
            name=args["name"],
            from_unbound_chat_id=args.get("from_unbound_chat_id") or None,
        )
        # `out` is `{project_id, slug}`. The slug is the only handle every
        # subsequent tool takes; the pid is audit metadata.
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "delete_project",
        "Permanently delete a whole project: rmtree its dir and drop the pid "
        "from the index. Returns {deleted_slug, deleted_pid}. ALWAYS ask the "
        "user to confirm first — this is unrecoverable. Use this instead of "
        "`Bash rm -rf <project_dir>`: bare rm leaves the chat-log writer free "
        "to resurrect `chats/` with a trailing `agent_text`, producing a "
        "half-zombie folder. This tool tombstones project.json first so the "
        "log writer's gate trips even on in-flight events from the same turn. "
        "For sub-paths (docs/, prompts/, experiments/, individual files) keep "
        "using Bash rm — only whole-project delete needs this tool.",
        {"slug": str},
    )
    async def t_delete_project(args: dict[str, Any]) -> dict[str, Any]:
        try:
            out = await projects_mod.delete_project(workspace, args["slug"])
        except FileNotFoundError as e:
            out = {
                "ok": False,
                "error": {
                    "error_code": "project_not_found",
                    "error_message_en": str(e),
                },
            }
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "promote_chat_to_project",
        "Bind the current unbound chat to a freshly minted project. Mints "
        "the project (via `create_project`), then atomically relocates the "
        "chat's `_chats/<chat_id>.jsonl` + `.meta.json` + `<chat_id>/` "
        "attachments under the new project's `chats/`. Returns "
        "`{slug, project_id}`. Prefer `create_project(name=..., "
        "from_unbound_chat_id=...)` from inside an unbound chat — this tool "
        "is the symmetric HTTP-route handle (used by `/init` / Promote "
        "button). ALWAYS ask the user for a name first.",
        {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string"},
                "name": {"type": "string"},
                "slug": {"type": "string"},
            },
            "required": ["chat_id", "name"],
        },
    )
    async def t_promote_chat_to_project(args: dict[str, Any]) -> dict[str, Any]:
        out = await promote_mod.promote_chat_to_project(
            workspace,
            args["chat_id"],
            name=args["name"],
            slug=args.get("slug") or None,
        )
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "promote_attachment_to_docs",
        "Move a chat-scoped attachment from `chats/<chat_id>/attachments/` "
        "into the curated `docs/` sample set (with sidecar + sha256 + dedupe). "
        "Use this ONLY after the user explicitly confirms they want the file "
        "added to the project's samples — paste/drop defaults to "
        "conversational scratch. Returns `{final_name}`.",
        {"slug": str, "chat_id": str, "filename": str},
    )
    async def t_promote_attachment_to_docs(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("promote_attachment_to_docs")
            )}]}
        out = await promote_mod.promote_attachment_to_docs(
            workspace, args["slug"], args["chat_id"], args["filename"],
        )
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "pre_label",
        "Pro-labeler batch draft. Calls the project's `labeler_model` (a "
        "stronger LLM, e.g. `gemini-pro-latest`) on each filename and writes "
        "a draft to `reviewed/_pending/{filename}.json` for the human boss "
        "to verify in Review mode. Skips docs that already have `reviewed/`. "
        "Overwrites existing pending (re-run with a different model OK). "
        "Pass empty filenames=[] (or omit) to label every unreviewed doc. "
        "Cap each call at ≤10 filenames — batch larger sets across multiple "
        "calls so chat feedback stays responsive. Returns "
        "{processed, skipped, errors, labeler_model}. This is NOT a "
        "substitute for extract — output goes to reviewed/_pending/, never "
        "predictions/_draft/ or reviewed/.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filenames": {"type": "array", "items": {"type": "string"}},
                "labeler_model": {"type": "string"},
            },
            "required": ["slug"],
        },
    )
    async def t_pre_label(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("pre_label")
            )}]}
        try:
            out = await pre_label_mod.pre_label(
                workspace, args["slug"],
                filenames=args.get("filenames") or None,
                labeler_model=args.get("labeler_model") or None,
            )
        except pre_label_mod.LabelerNotConfiguredError as e:
            out = {
                "ok": False,
                "error": {
                    "error_code": "labeler_model_not_configured",
                    "error_message_en": str(e),
                },
            }
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "set_labeler_model",
        "Set a project-specific labeler override (writes "
        "project.json.labeler_model). Use ONLY when the user explicitly "
        "names a model for this project (\"换 pro 模型\" / \"this project "
        "should use X as labeler\"). DO NOT call this just because "
        "project.json.labeler_model is null — that's the normal state and "
        "means pre_label falls through to EMERGE_DEFAULT_LABELER_MODEL. To "
        "check what pre_label would actually run, call `get_labeler_config` "
        "first. No risk gate; the override is recoverable.",
        {"slug": str, "model_id": str},
    )
    async def t_set_labeler_model(args: dict[str, Any]) -> dict[str, Any]:
        await pre_label_mod.set_labeler_model(
            workspace, args["slug"], args["model_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "get_labeler_config",
        "Inspect the labeler-model resolution for this project. Returns "
        "{override, env_default, resolved, source}: `override` is "
        "project.json.labeler_model (usually null = no project-specific "
        "override), `env_default` is EMERGE_DEFAULT_LABELER_MODEL, `resolved` "
        "is what pre_label will actually call, and `source` is "
        "'override'|'env_default'|'unconfigured'. Call this whenever you "
        "would otherwise inspect project.json directly to decide if the "
        "labeler is configured — Reading project.json misses the env "
        "fallback and leads to false \"还没配\" claims.",
        {"slug": str},
    )
    async def t_get_labeler_config(args: dict[str, Any]) -> dict[str, Any]:
        out = await pre_label_mod.get_labeler_config(workspace, args["slug"])
        return {
            "content": [
                {"type": "text", "text": _json.dumps(out, ensure_ascii=False)}
            ]
        }

    @tool(
        "pdf_render_page",
        "Render a PDF page as PNG; returns the path.",
        {"slug": str, "filename": str, "page": int},
    )
    async def t_pdf_render_page(args: dict[str, Any]) -> dict[str, Any]:
        p = await docs_mod.pdf_render_page(
            workspace, args["slug"], args["filename"], page=args["page"]
        )
        return {"content": [{"type": "text", "text": str(p)}]}

    @tool(
        "read_doc_image",
        "Return the visual content of one doc as an inline image so you can see "
        "what the user sees. Use this when the user asks about the visual content "
        "of a doc you can't read from JSON state alone (e.g. 'what is this doc', "
        "'识别一下', 'is this page blurry'). PNG/JPG: pass page=1 (ignored). "
        "PDF: pass the specific page; check surface_context.page if the user is "
        "in review mode. Do NOT call extract just to 'see' a doc — that uses an "
        "LLM call to produce structured JSON; this tool gives you direct vision. "
        "If you need multiple pages of a long PDF, call this tool once per page.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
                "page": {"type": "integer"},
            },
            "required": ["slug", "filename"],
        },
    )
    async def t_read_doc_image(args: dict[str, Any]) -> dict[str, Any]:
        out = await docs_mod.read_doc_image(
            workspace, args["slug"], args["filename"],
            page=int(args.get("page") or 1),
        )
        return {
            "content": [
                {"type": "image", "data": out["data"], "mimeType": out["mime"]},
                {
                    "type": "text",
                    "text": _json.dumps({
                        "filename": out["filename"],
                        "page": out["page"],
                        "page_count": out["page_count"],
                    }),
                },
            ]
        }

    @tool(
        "derive_schema",
        "Propose a schema from sample documents and a user intent.",
        {"slug": str, "sample_filenames": list, "intent": str},
    )
    async def t_derive_schema(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("derive_schema")
            )}]}
        from app.provider import get_provider_for_model

        mc = await model_mod.read_active_model(workspace, args["slug"])
        mid = mc.provider_model_id
        prj_provider = get_provider_for_model(mid, provider=mc.provider)
        fields = await schema_mod.derive_schema(
            workspace,
            args["slug"],
            sample_filenames=args["sample_filenames"],
            intent=args["intent"],
            provider=prj_provider,
            model_id=mid,
        )
        return {"content": [{"type": "text", "text": str([f.model_dump(mode="json") for f in fields])}]}

    @tool(
        "write_schema",
        "Write a new schema and/or update global_notes. Set allow_structural=true to "
        "add/remove/rename/retype fields. Pass global_notes to update it atomically in "
        "the same write; omit to preserve the current value.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "schema": {"type": "array"},
                "reason": {"type": "string"},
                "allow_structural": {"type": "boolean"},
                "global_notes": {"type": "string"},
            },
            "required": ["slug", "schema", "reason"],
        },
    )
    async def t_write_schema(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("write_schema")
            )}]}
        fields = [SchemaField(**f) for f in args["schema"]]
        await schema_mod.write_schema(
            workspace,
            args["slug"],
            fields,
            reason=args["reason"],
            allow_structural=args.get("allow_structural", False),
            global_notes=args.get("global_notes"),
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "switch_active_prompt",
        "Set the project's active prompt to the given prompt_id. Affects all "
        "subsequent reads of the active prompt (extract, freeze, etc).",
        {"slug": str, "prompt_id": str},
    )
    async def t_switch_active_prompt(args: dict[str, Any]) -> dict[str, Any]:
        await prompt_mod.switch_active_prompt(
            workspace, args["slug"], args["prompt_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "switch_active_model",
        "Set the project's active model to the given model_id. Affects all "
        "subsequent extract calls when model_id arg is not explicitly provided.",
        {"slug": str, "model_id": str},
    )
    async def t_switch_active_model(args: dict[str, Any]) -> dict[str, Any]:
        await model_mod.switch_active_model(
            workspace, args["slug"], args["model_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "create_experiment",
        "Upsert an experiment by (prompt_id, model_id) pair. If one already "
        "exists for this exact pair, returns its existing experiment_id; else "
        "mints a new one. Both axes default to the project's active. Label is "
        "derived from prompt + model labels (not user-provided).",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "prompt_id": {"type": "string"},
                "model_id": {"type": "string"},
            },
            "required": ["slug"],
        },
    )
    async def t_create_experiment(args: dict[str, Any]) -> dict[str, Any]:
        eid = await experiment_mod.create_experiment(
            workspace, args["slug"],
            prompt_id=args.get("prompt_id") or None,
            model_id=args.get("model_id") or None,
        )
        return {"content": [{"type": "text", "text": eid}]}

    @tool(
        "extract_with_experiment",
        "Run an experiment's (prompt, model) pair on a single doc; writes "
        "experiments/{experiment_id}/predictions/{filename}.json. Returns the payload.",
        {"slug": str, "experiment_id": str, "filename": str},
    )
    async def t_extract_with_experiment(args: dict[str, Any]) -> dict[str, Any]:
        ex = await experiment_mod.read_experiment(
            workspace, args["slug"], args["experiment_id"],
        )
        model = await model_mod.read_model(
            workspace, args["slug"], ex.model_id,
        )
        from app.provider import get_provider_for_model
        exp_provider = get_provider_for_model(
            model.provider_model_id, provider=model.provider,
        )
        payload = await experiment_mod.extract_with_experiment(
            workspace, args["slug"], args["experiment_id"], args["filename"],
            provider=exp_provider,
        )
        return {"content": [{"type": "text", "text": _json.dumps(payload)}]}

    @tool(
        "run_experiment_eval",
        "Loop reviewed/ docs through the experiment's (prompt, model); writes "
        "per-doc extracts and computes overall + per-field + per-doc scores. "
        "Returns the eval dict and sets status='ran'.",
        {"slug": str, "experiment_id": str},
    )
    async def t_run_experiment_eval(args: dict[str, Any]) -> dict[str, Any]:
        ex = await experiment_mod.read_experiment(
            workspace, args["slug"], args["experiment_id"],
        )
        model = await model_mod.read_model(
            workspace, args["slug"], ex.model_id,
        )
        from app.provider import get_provider_for_model
        exp_provider = get_provider_for_model(
            model.provider_model_id, provider=model.provider,
        )
        ev = await experiment_mod.run_experiment_eval(
            workspace, args["slug"], args["experiment_id"],
            provider=exp_provider,
        )
        return {"content": [{"type": "text", "text": _json.dumps(ev)}]}

    @tool(
        "promote_experiment",
        "Set the experiment's (prompt_id, model_id) as the project's active pair; "
        "clear predictions/_draft/ and re-seed from the experiment's extracts. "
        "Marks experiment status='promoted' (audit trail).",
        {"slug": str, "experiment_id": str},
    )
    async def t_promote_experiment(args: dict[str, Any]) -> dict[str, Any]:
        await experiment_mod.promote_experiment(
            workspace, args["slug"], args["experiment_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "fork_project",
        "Clone-at-time fork of an existing project. Copies project.json + "
        "prompts/ + models/ into a fresh project (new slug + pid). Skips chats, "
        "reviewed, predictions/_draft, experiments, versions, metrics. Set "
        "include_docs=true to also hardlink docs/ files. Returns {project_id, slug}.",
        {
            "type": "object",
            "properties": {
                "src_slug": {"type": "string"},
                "name": {"type": "string"},
                "include_docs": {"type": "boolean"},
            },
            "required": ["src_slug", "name"],
        },
    )
    async def t_fork_project(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.fork import fork_project as fork_project_impl
        out = await fork_project_impl(
            workspace,
            src_slug=args["src_slug"],
            name=args["name"],
            include_docs=bool(args.get("include_docs", False)),
        )
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "extract_one",
        "Extract from a single document. `filename` is the doc handle (the "
        "on-disk filename, e.g. `2025VP00413.pdf`).",
        {"slug": str, "filename": str},
    )
    async def t_extract_one(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("extract_one")
            )}]}
        out = await extract_mod.extract_one(
            workspace, args["slug"], args["filename"], provider=provider
        )
        return {"content": [{"type": "text", "text": str(out)}]}

    @tool(
        "extract_batch",
        "Extract over a list of documents (foreground). `filenames` is a list "
        "of on-disk filenames (the doc handles).",
        {"slug": str, "filenames": list},
    )
    async def t_extract_batch(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("extract_batch")
            )}]}
        summary = await extract_mod.extract_batch(
            workspace, args["slug"], args["filenames"], provider=provider
        )
        return {"content": [{"type": "text", "text": str(summary)}]}

    @tool(
        "save_reviewed",
        "Save a corrected extraction as ground truth for a doc. "
        "`notes_consumed` is an audit-trail map keyed by field name; it is "
        "lifecycle metadata maintained by the AutoResearch `accept_candidate` "
        "flow — agents should normally OMIT it (defensive merge will preserve "
        "the existing on-disk map). Pass an explicit empty `{}` only when the "
        "intent is genuinely to clear the map.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
                "entities": {"type": "array"},
                "source": {"type": "string"},
                "notes": {"type": "object"},
                "notes_consumed": {"type": "object"},
            },
            "required": ["slug", "filename", "entities"],
        },
    )
    async def t_save_reviewed(args: dict[str, Any]) -> dict[str, Any]:
        # If the agent omits `notes_consumed`, the kwarg disappears entirely
        # (so save_reviewed sees its _OMITTED sentinel and preserves on-disk).
        # If it's present (even {}), pass it through verbatim — save_reviewed
        # interprets `{}` as "clear" and a populated dict as "replace".
        try:
            source = ReviewedSource(args.get("source", "manual"))
        except ValueError:
            source = ReviewedSource.MANUAL
        save_kwargs: dict[str, Any] = {
            "entities": args["entities"],
            "source": source,
            "notes": args.get("notes") or None,
        }
        if "notes_consumed" in args:
            save_kwargs["notes_consumed"] = args["notes_consumed"]
        await reviewed_mod.save_reviewed(
            workspace,
            args["slug"],
            args["filename"],
            **save_kwargs,
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "score",
        "Compute precision/recall/F1 by comparing draft predictions against reviewed examples. Persists a metrics snapshot under metrics/eval_{ts}.json. Returns ScoreResult.",
        {"slug": str},
    )
    async def t_score(args: dict[str, Any]) -> dict[str, Any]:
        result = await score_mod.run_eval(workspace, args["slug"])
        return {"content": [{"type": "text", "text": _json.dumps(result.model_dump(mode='json'))}]}

    @tool(
        "readiness_check",
        "Run the publish readiness checklist for a project.",
        {"slug": str},
    )
    async def t_readiness_check(args: dict[str, Any]) -> dict[str, Any]:
        out = await publish_mod.readiness_check(workspace, args["slug"])
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "contract_diff",
        "Diff current schema against the active version's frozen schema.",
        {"slug": str},
    )
    async def t_contract_diff(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.schema import read_schema
        from app.workspace.paths import parse_version_id, project_json_path, version_path

        slug = args["slug"]
        schema = await read_schema(workspace, slug)
        project = _json.loads(project_json_path(workspace, slug).read_text())
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
            if n is not None and version_path(workspace, slug, n).exists():
                prev_blob = _json.loads(version_path(workspace, slug, n).read_text())
                prev = [SchemaField(**field) for field in prev_blob.get("schema", [])]
            out = publish_mod.contract_diff(prev, schema)
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "freeze_version",
        "Freeze the current schema. Writes both versions/v{n}.json (lab lineage) "
        "and _published/{pub_xxx}.json (frozen artifact servable by POST /v1/extract). "
        "Returns {version_id, published_id}. GATED — readiness checks must pass.",
        {"slug": str},
    )
    async def t_freeze_version(args: dict[str, Any]) -> dict[str, Any]:
        try:
            out = await publish_mod.freeze_version(workspace, args["slug"])
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
        "Issue or rotate an API key for a user. Keys are user-scoped (not "
        "project-scoped) — one key calls any published_id the user wants. "
        "Pass `user_id` to scope; defaults to the single-user placeholder "
        "\"default\". Plaintext appears exactly once in this tool result.",
        {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
            },
            "required": [],
        },
    )
    async def t_issue_api_key(args: dict[str, Any]) -> dict[str, Any]:
        user_id = args.get("user_id") or "default"
        out = await publish_mod.issue_api_key(workspace, user_id=user_id)
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "start_job",
        "Kick off a background job. v1 supports skill='autoresearch'. Returns a job_id; subscribe to /lab/jobs/{job_id}/events for progress.",
        {
            "type": "object",
            "properties": {
                "skill": {"type": "string"},
                "slug": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["skill", "slug"],
        },
    )
    async def t_start_job(args: dict[str, Any]) -> dict[str, Any]:
        # `start_job_impl` keeps the legacy `project_id` kwarg name; the value
        # carries the slug (paths are slug-keyed end-to-end).
        jid = await jobs_mod.start_job_impl(
            job_runner, skill=args["skill"], project_id=args["slug"],
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

    @tool(
        "get_surface_state",
        "Read rich state of a UI surface the user is looking at. Phase 1 "
        "supports surface='review' (requires `filename`) and returns "
        "{review_status: 'unprocessed'|'pending'|'reviewed', has_prediction, "
        "has_reviewed, has_pending (Pro-labeler draft awaiting boss verify), "
        "page_count, evidence, notes, entity_count, "
        "experiments_with_prediction}. Call this when the user asks 'what's "
        "the status of this doc' / 'pending 是什么意思' / 'which experiments "
        "have run on this' — it replies from disk truth so you don't have "
        "to invent.",
        {
            "type": "object",
            "properties": {
                "surface": {"type": "string"},
                "slug": {"type": "string"},
                "filename": {"type": "string"},
            },
            "required": ["surface", "slug"],
        },
    )
    async def t_get_surface_state(args: dict[str, Any]) -> dict[str, Any]:
        out = await surface_state_mod.get_surface_state(
            workspace,
            surface=args["surface"],
            slug=args["slug"],
            filename=args.get("filename") or None,
        )
        return {
            "content": [
                {"type": "text", "text": _json.dumps(out, ensure_ascii=False, indent=2)}
            ]
        }

    @tool(
        "ui_goto_page",
        "Navigate the review viewer to page N (1-indexed). Pure navigation; "
        "no disk side-effect. Errors if called outside an active chat turn.",
        {"slug": str, "filename": str, "page": int},
    )
    async def t_ui_goto_page(args: dict[str, Any]) -> dict[str, Any]:
        out = await ui_actions_mod.ui_goto_page(
            slug=args["slug"], filename=args["filename"], page=args["page"],
        )
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "ui_set_active_field",
        "Focus a specific field row in the review editor. `path` is the "
        "field identifier the editor uses (e.g. `buyer_name` or "
        "`line_items[0].amount`). Pure navigation; no disk side-effect.",
        {"slug": str, "filename": str, "path": str},
    )
    async def t_ui_set_active_field(args: dict[str, Any]) -> dict[str, Any]:
        out = await ui_actions_mod.ui_set_active_field(
            slug=args["slug"], filename=args["filename"], path=args["path"],
        )
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "ui_set_active_tab",
        "Switch the review tab strip. `tab_key='active'` selects the saved "
        "annotation; any other value is treated as an experiment_id. Pure "
        "navigation; no disk side-effect.",
        {"slug": str, "filename": str, "tab_key": str},
    )
    async def t_ui_set_active_tab(args: dict[str, Any]) -> dict[str, Any]:
        out = await ui_actions_mod.ui_set_active_tab(
            slug=args["slug"], filename=args["filename"], tab_key=args["tab_key"],
        )
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "ask_user",
        "Ask the user a structured multiple-choice question and wait for "
        "their answer. Use this whenever you need an explicit confirmation or "
        "choice the chat can't safely infer — e.g. \"write schema with mapping "
        "A or B?\", \"promote experiment exp_xxx? (irreversible)\". Schema: "
        "questions = [{question: str, header: <=12 char chip, options: 2-4 of "
        "{label, description}, multiSelect: bool (default false)}]. Up to 4 "
        "questions per call. Returns {ok, answers: [{question_index, "
        "selected: [{option_index, label}]}]}. The frontend renders option "
        "buttons (and 1/2/3 keyboard shortcuts) so the user picks without "
        "having to type. DO NOT call the SDK built-in `AskUserQuestion` — it "
        "is not wired in emerge; use this tool.",
        {"questions": list},
    )
    async def t_ask_user(args: dict[str, Any]) -> dict[str, Any]:
        out = await ask_user_mod.ask_user(args.get("questions") or [])
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "ui_set_active_entity",
        "Switch the entity tab in a multi-entity doc. `idx` is 0-indexed. "
        "Pure navigation; no disk side-effect.",
        {"slug": str, "filename": str, "idx": int},
    )
    async def t_ui_set_active_entity(args: dict[str, Any]) -> dict[str, Any]:
        out = await ui_actions_mod.ui_set_active_entity(
            slug=args["slug"], filename=args["filename"], idx=args["idx"],
        )
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    return create_sdk_mcp_server(
        name="emerge_tools",
        version="0.0.1",
        tools=[
            t_create_project,
            t_promote_chat_to_project,
            t_promote_attachment_to_docs,
            t_pre_label,
            t_set_labeler_model,
            t_get_labeler_config,
            t_pdf_render_page,
            t_read_doc_image,
            t_derive_schema,
            t_write_schema,
            t_switch_active_prompt,
            t_switch_active_model,
            t_create_experiment,
            t_extract_with_experiment,
            t_run_experiment_eval,
            t_promote_experiment,
            t_fork_project,
            t_extract_one,
            t_extract_batch,
            t_save_reviewed,
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
            t_get_surface_state,
            t_ui_goto_page,
            t_ui_set_active_field,
            t_ui_set_active_tab,
            t_ui_set_active_entity,
            t_ask_user,
        ],
    )


_EMERGE_TOOL_NAMES = (
    "create_project",
    "promote_chat_to_project",
    "promote_attachment_to_docs",
    "pre_label", "set_labeler_model", "get_labeler_config",
    "pdf_render_page", "read_doc_image",
    "derive_schema", "write_schema",
    "switch_active_prompt", "switch_active_model",
    "create_experiment", "extract_with_experiment", "run_experiment_eval",
    "promote_experiment",
    "fork_project",
    "extract_one", "extract_batch",
    "save_reviewed",
    "score",
    "start_job", "get_job", "pause_job", "resume_job", "cancel_job",
    "readiness_check", "contract_diff", "freeze_version", "issue_api_key",
    "get_surface_state",
    "ui_goto_page", "ui_set_active_field", "ui_set_active_tab", "ui_set_active_entity",
    "ask_user",
)


def _emerge_tool_names() -> tuple[str, ...]:
    return _EMERGE_TOOL_NAMES
