from __future__ import annotations

import json as _json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import (
    McpSdkServerConfig,
    ToolAnnotations,
    create_sdk_mcp_server,
    tool,
)

from app.provider.base import Provider
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import SchemaField
from app.tools import ask_user as ask_user_mod
from app.tools import bench as bench_mod
from app.tools import docs as docs_mod
from app.tools import extract as extract_mod
from app.tools import jobs as jobs_mod
from app.tools import pre_label as pre_label_mod
from app.tools import project_config as project_config_mod
from app.tools import promote as promote_mod
from app.tools import publish as publish_mod
from app.tools import projects as projects_mod
from app.tools import reviewed as reviewed_mod
from app.tools import score as score_mod
from app.tools import experiment as experiment_mod
from app.tools import history as history_mod
from app.tools import model as model_mod
from app.tools import prompt as prompt_mod
from app.tools import schema as schema_mod
from app.tools import surface_state as surface_state_mod
from app.tools import textlayer as textlayer_mod
from app.tools import translate as translate_mod
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


def _extract_provider_error(exc: Exception) -> dict[str, Any]:
    """Structured envelope for an extract that died in the provider layer.

    Without this, a raw provider exception propagated out of the tool body and
    the SDK rendered it to the agent as an opaque `Command failed with no
    output` — zero signal, so the agent debugged the *document* instead of
    re-running it (the 振兴_testset turn-burn). We split two codes so the agent
    can tell apart:
      - `extract_provider_unavailable` (transient): flaky proxy / gateway —
        the right move is just re-run THIS doc; the doc is fine.
      - `extract_provider_failed` (permanent): bad schema / parse / config —
        re-running won't help; surface to the user.
    Mirrors the {ok, error:{error_code, error_message_en}} shape used by
    `translate_page` / `label_docs`; `transient` is the agent's retry hint.
    """
    from app.provider.retry import is_transient

    transient = is_transient(exc)
    return {
        "ok": False,
        "error": {
            "error_code": (
                "extract_provider_unavailable" if transient
                else "extract_provider_failed"
            ),
            "error_message_en": str(exc) or type(exc).__name__,
            "transient": transient,
        },
    }


# ── tool annotations (MCP best practice) ───────────────────────────────────
# `ToolAnnotations` are behavioural hints surfaced in the remote `tools/list`
# (create_sdk_mcp_server bakes them into mcp.types.Tool). A client like Claude
# Cowork uses them for its "Tool policy": auto-approve read-only tools, gate the
# destructive ones. Per spec `destructiveHint` DEFAULTS TO TRUE, so a non-
# destructive tool MUST say so explicitly — hence we annotate every tool from
# these central buckets (single source of truth, easier to audit than 40
# scattered decorator args). Anything not listed is a normal, non-destructive,
# non-idempotent local mutation (destructiveHint=False, the safe-but-honest case).
_READ_ONLY = frozenset({  # pure read / local compute — no durable state change
    "list_projects", "list_docs", "read_prompt",
    "ws_list", "ws_read", "ws_grep",
    "get_labeler_config", "get_project_config", "get_job", "get_surface_state",
    "read_doc_image", "pdf_render_page", "bench_view", "contract_diff",
    "readiness_check",
})
_DESTRUCTIVE = frozenset({  # irreversible / outward-facing — client should gate
    "delete_project", "freeze_version", "issue_api_key", "promote_experiment",
})
_IDEMPOTENT = frozenset({  # mutates, but re-applying the same args is a no-op
    "set_labeler_model", "set_translate_model", "set_proposer_model",
    "switch_active_prompt", "switch_active_model", "write_schema",
    "extract_textlayer", "translate_page",
    "pause_job", "resume_job", "cancel_job",
    "ui_goto_page", "ui_set_active_field", "ui_set_active_tab", "ui_set_active_entity",
})
_TOUCHES_PROVIDER = frozenset({  # calls an external LLM/OCR → openWorldHint stays true
    "derive_schema", "extract_one", "extract_with_experiment", "extract_textlayer",
    "translate_page", "label_docs", "score", "run_experiment_eval", "start_job",
    "run_match", "score_match",  # L2 judge tie-breaker may call the LLM
})


def _annotate(name: str) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=name in _READ_ONLY,
        destructiveHint=name in _DESTRUCTIVE,
        idempotentHint=name in _IDEMPOTENT,
        openWorldHint=name in _TOUCHES_PROVIDER,
    )


def build_emerge_mcp(
    workspace: Path,
    provider: Provider,
    job_runner: "JobRunner",
    *,
    headless: bool = False,
) -> McpSdkServerConfig:
    """Construct an in-process MCP server exposing emerge's business tools.

    ``headless=True`` additionally registers the filesystem-*discovery* tools
    (``list_projects`` / ``list_docs`` / ``read_prompt``). emerge's own chat
    agent shares the workspace filesystem and discovers via the SDK built-in
    Bash/Read (Step B cut these wrappers), so it builds with ``headless=False``.
    But a REMOTE MCP client (Cowork / Desktop, via ``build_mcp_server``) runs
    its Bash in a different sandbox and cannot see this server's disk — without
    these tools a remote agent has no way to enumerate what exists. This is the
    additive twin of ``_HEADLESS_EXCLUDE`` (which subtracts the ``ui_*`` tools
    from the same headless surface).

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
        "Delete a whole project: MOVE its dir to _trash/ (recoverable for ~2 "
        "weeks) and drop the pid from the index. Returns {deleted_slug, "
        "deleted_pid}. Still ask the user to confirm first. Use this instead of "
        "`Bash rm -rf <project_dir>`: bare rm leaves the chat-log writer free "
        "to resurrect `chats/` with a trailing `agent_text`, producing a "
        "half-zombie folder. This tool renames the dir into _trash/ in one "
        "atomic step, so the live project.json vanishes (the log writer's gate "
        "trips even on in-flight events) while the trashed copy stays restorable. "
        "For sub-paths (docs/, prompts/, experiments/, individual files) keep "
        "using Bash rm — only whole-project delete needs this tool.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
            },
            "required": ["slug"],
        },
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
        "history_log",
        "List the version timeline (git history) of the team workspace, newest "
        "first. Pass `slug` to scope to one project. Each version has a `ref` "
        "(short hash), `date`, and `message` (the turn intent that produced it). "
        "Use this to answer 'what versions exist?' / 'when did X change?', then "
        "feed a `ref` to history_diff or history_restore. Rendering: in a browser "
        "give a one-line summary (the UI shows the list); headless, print the "
        "versions as a dated list.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    )
    async def t_history_log(args: dict[str, Any]) -> dict[str, Any]:
        out = await history_mod.history_log(
            workspace, slug=args.get("slug") or None, limit=int(args.get("limit") or 30)
        )
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "history_diff",
        "Show what changed between two versions (or between a version and the "
        "current state when `b` is omitted). `a`/`b` are refs from history_log. "
        "Pass `slug` to scope to one project. Returns a unified diff (`truncated` "
        "signals it was capped). Rendering: browser → summarize the changes in a "
        "sentence (UI can show the diff); headless → print the diff.",
        {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string"},
                "slug": {"type": "string"},
            },
            "required": ["a"],
        },
    )
    async def t_history_diff(args: dict[str, Any]) -> dict[str, Any]:
        out = await history_mod.history_diff(
            workspace, ref_a=args["a"], ref_b=args.get("b") or None, slug=args.get("slug") or None
        )
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "history_restore",
        "Restore the team workspace (or one project via `slug`) to its state at "
        "`ref` (from history_log). The restore is ITSELF a new version, so it's "
        "reversible — nothing is lost. ALWAYS confirm with the user first and "
        "tell them which version (date + message) you're rolling back to. "
        "Rendering: browser → one-line confirmation; headless → state the "
        "restored ref and the new version hash.",
        {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "slug": {"type": "string"},
            },
            "required": ["ref"],
        },
    )
    async def t_history_restore(args: dict[str, Any]) -> dict[str, Any]:
        out = await history_mod.history_restore(
            workspace, ref=args["ref"], slug=args.get("slug") or None
        )
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

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
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "chat_id": {"type": "string"},
                "filename": {"type": "string"},
            },
            "required": ["slug", "chat_id", "filename"],
        },
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
        "label_docs",
        "Atomic small-batch pro-label. Calls the project's `labeler_model` (a "
        "stronger LLM, e.g. `gemini-pro-latest`) on each filename and writes a "
        "draft to `reviewed/_pending/{filename}.json` for the human boss to "
        "verify. Skips docs that already have `reviewed/` (human wins) or an "
        "existing `_pending/` draft (idempotent — re-running with the same "
        "filenames after a disconnect is a no-op, not a re-spend). Pass "
        "filenames=[] (or omit) to label every unreviewed doc. The upstream "
        "caller (main agent / CLI / `pre_label_runner` subagent) chunks large "
        "sets in batches of ≤10 — this tool does no chunking itself. Returns "
        "{processed, skipped, errors, labeler_model}. Output goes to "
        "reviewed/_pending/, never predictions/_draft/ or reviewed/.",
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
    async def t_label_docs(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("label_docs")
            )}]}
        try:
            out = await pre_label_mod.label_docs(
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
        "means label_docs falls through to EMERGE_DEFAULT_LABELER_MODEL. To "
        "check what label_docs would actually run, call `get_labeler_config` "
        "first. No risk gate; the override is recoverable.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "model_id": {"type": "string"},
            },
            "required": ["slug", "model_id"],
        },
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
        "is what label_docs will actually call, and `source` is "
        "'override'|'env_default'|'unconfigured'. Call this whenever you "
        "would otherwise inspect project.json directly to decide if the "
        "labeler is configured — Reading project.json misses the env "
        "fallback and leads to false \"还没配\" claims.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
            },
            "required": ["slug"],
        },
    )
    async def t_get_labeler_config(args: dict[str, Any]) -> dict[str, Any]:
        out = await pre_label_mod.get_labeler_config(workspace, args["slug"])
        return {
            "content": [
                {"type": "text", "text": _json.dumps(out, ensure_ascii=False)}
            ]
        }

    @tool(
        "get_project_config",
        "Snapshot this project's tunable LLM-role config — what `/config` "
        "shows. Returns {active_prompt_id, extract, labeler, proposer, "
        "translate, agent_brain}. `extract` is the live active model triple; "
        "labeler/proposer/translate each carry {override, resolved, source} "
        "so you can name the resolved model AND where it came from (project "
        "override vs env default) without Reading project.json (which misses "
        "env fallbacks). `agent_brain` is locked (system-level, not "
        "project-tunable). No secrets/keys are ever included — selection only. "
        "Call this for any 'what models are you using / 给我看看你的配置' ask.",
        {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    )
    async def t_get_project_config(args: dict[str, Any]) -> dict[str, Any]:
        out = await project_config_mod.get_project_config(workspace, args["slug"])
        return {
            "content": [
                {"type": "text", "text": _json.dumps(out, ensure_ascii=False)}
            ]
        }

    @tool(
        "set_translate_model",
        "Pin the review-mode translator model for this project (writes "
        "project.json.translate_model). Use when the user names a translator "
        "(\"翻译用 X\" / \"把翻译模型换成 X\"). Translate is review-UX only — it "
        "never feeds the extract/labeler/proposer prompt — so there is no risk "
        "gate; the override is recoverable. To see the current resolution call "
        "`get_project_config` (the `translate` block).",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "model_id": {"type": "string"},
            },
            "required": ["slug", "model_id"],
        },
    )
    async def t_set_translate_model(args: dict[str, Any]) -> dict[str, Any]:
        await translate_mod.set_translate_model(
            workspace, args["slug"], args["model_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "set_proposer_model",
        "Pin the AutoResearch proposer model for this project (writes "
        "project.json.autoresearch_proposer_model). Use when the user names a "
        "proposer for `/improve` (\"用 X 来调 prompt\" / \"proposer 换成 X\"). "
        "DO NOT call this just because it's null — null means `/improve` falls "
        "through to the project's active extract model, which is the normal "
        "default. Takes effect on the next `/improve` job. Recoverable, no "
        "risk gate. To see the current resolution call `get_project_config` "
        "(the `proposer` block).",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "model_id": {"type": "string"},
            },
            "required": ["slug", "model_id"],
        },
    )
    async def t_set_proposer_model(args: dict[str, Any]) -> dict[str, Any]:
        from app.jobs.autoresearch import set_proposer_model

        await set_proposer_model(workspace, args["slug"], args["model_id"])
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "pdf_render_page",
        "Render a PDF page as PNG; returns the path.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
                "page": {"type": "integer"},
            },
            "required": ["slug", "filename", "page"],
        },
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
        "extract_textlayer",
        "Return the vector text spans for one PDF page (or an empty layer for "
        "image / scanned docs), persisted to a per-page sidecar. Powers the "
        "review-mode transparent overlay that lets the user select + copy "
        "original text on top of the rasterised page. bbox is in PDF point "
        "units; image_w/image_h match the 150dpi raster produced by "
        "pdf_render_page so the frontend can scale spans onto the bitmap. "
        "`scanned=true` signals an honest degrade — the page is mostly raster, "
        "no selectable text. NEVER feed the bbox / span text back into "
        "extract or runtime prompts (hard rule); this is review UX only.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
                "page": {"type": "integer", "minimum": 1},
            },
            "required": ["slug", "filename", "page"],
        },
    )
    async def t_extract_textlayer(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("extract_textlayer")
            )}]}
        try:
            out = await textlayer_mod.extract_textlayer(
                workspace, args["slug"], args["filename"], page=int(args["page"]),
            )
        except FileNotFoundError as e:
            out = {
                "ok": False,
                "error": {
                    "error_code": "doc_not_found",
                    "error_message_en": str(e),
                },
            }
        except ValueError as e:
            out = {
                "ok": False,
                "error": {
                    "error_code": "textlayer_invalid_args",
                    "error_message_en": str(e),
                },
            }
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "translate_page",
        "Translate a single page of a doc. Picks textlayer mode (electronic "
        "PDF — sends vector spans as JSON to a cheap translator LLM, no "
        "image) or vision mode (scanned PDF / image — OCR + locate + "
        "translate in one vision call) automatically based on the page's "
        "textlayer sidecar. Returns `{mode, page_w, page_h, image_w, "
        "image_h, lines: [{bbox, original, translated}], model_id, "
        "input_tokens, output_tokens}`. `bbox` is ALWAYS in PDF page units "
        "(top-left origin, fitz convention). Cache key includes mode + "
        "target_lang + model_id; pass `force_refresh=true` to bypass "
        "(Shift+T from the frontend). Default target_lang=zh (简体中文). "
        "Translation is review UX only — bbox / lines NEVER feed back into "
        "extract or runtime prompts (hard rule).",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
                "page": {"type": "integer", "minimum": 1},
                "target_lang": {"type": "string", "default": "zh"},
                "force_refresh": {"type": "boolean", "default": False},
            },
            "required": ["slug", "filename", "page"],
        },
    )
    async def t_translate_page(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("translate_page")
            )}]}
        try:
            out = await translate_mod.translate_page(
                workspace, args["slug"], args["filename"],
                page=int(args["page"]),
                target_lang=str(args.get("target_lang") or "zh"),
                force_refresh=bool(args.get("force_refresh", False)),
            )
        except FileNotFoundError as e:
            out = {
                "ok": False,
                "error": {
                    "error_code": "doc_not_found",
                    "error_message_en": str(e),
                },
            }
        except ValueError as e:
            out = {
                "ok": False,
                "error": {
                    "error_code": "translate_invalid_args",
                    "error_message_en": str(e),
                },
            }
        except Exception as e:  # noqa: BLE001 — provider failure envelope
            out = {
                "ok": False,
                "error": {
                    "error_code": "translate_provider_failed",
                    "error_message_en": str(e),
                },
            }
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "derive_schema",
        "Propose a schema from sample documents and a user intent.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "sample_filenames": {"type": "array", "items": {"type": "string"}},
                "intent": {"type": "string"},
            },
            "required": ["slug", "sample_filenames", "intent"],
        },
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
        "import_schema_from_yaml",
        "Import a chat-attached yml/yaml/json file as a project prompt schema. "
        "The file must already live at chats/<chat_id>/attachments/<filename> "
        "(dropped/pasted into the composer). Parses as a list of SchemaField "
        "dicts. Two targets: as_new_variant=false (default) atomically REPLACES "
        "the active prompt's schema via the same writer write_schema uses "
        "(allow_structural defaults true, import is inherently structural); "
        "as_new_variant=true mints a NEW prompt variant (cloned from active for "
        "lineage) without touching the active prompt — use when the user wants "
        "the import to coexist for A/B rather than overwrite. new_label names "
        "the variant (defaults imported:<filename>). On success returns {ok: "
        "true, field_count, names: [...]} (plus prompt_id, label when "
        "as_new_variant); on parse/validation failure returns {ok: false, "
        "error: {error_code: 'invalid_schema_yaml', error_message_en}}. ALWAYS "
        "confirm with the user before invoking.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "chat_id": {"type": "string"},
                "filename": {"type": "string"},
                "allow_structural": {"type": "boolean"},
                "as_new_variant": {"type": "boolean"},
                "new_label": {"type": "string"},
            },
            "required": ["slug", "chat_id", "filename"],
        },
    )
    async def t_import_schema_from_yaml(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("import_schema_from_yaml")
            )}]}
        try:
            out = await schema_mod.import_schema_from_yaml(
                workspace,
                args["slug"],
                args["chat_id"],
                args["filename"],
                allow_structural=bool(args.get("allow_structural", True)),
                as_new_variant=bool(args.get("as_new_variant", False)),
                new_label=args.get("new_label") or None,
            )
        except FileNotFoundError as exc:
            out = {
                "ok": False,
                "error": {
                    "error_code": "attachment_not_found",
                    "error_message_en": str(exc),
                },
            }
        except schema_mod.SchemaImportError as exc:
            out = {
                "ok": False,
                "error": {
                    "error_code": exc.error_code,
                    "error_message_en": exc.error_message_en,
                },
            }
        except schema_mod.StructuralChangeError as exc:
            out = {
                "ok": False,
                "error": {
                    "error_code": "structural_change_blocked",
                    "error_message_en": str(exc),
                },
            }
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "switch_active_prompt",
        "Set the project's active prompt to the given prompt_id. Affects all "
        "subsequent reads of the active prompt (extract, freeze, etc).",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "prompt_id": {"type": "string"},
            },
            "required": ["slug", "prompt_id"],
        },
    )
    async def t_switch_active_prompt(args: dict[str, Any]) -> dict[str, Any]:
        await prompt_mod.switch_active_prompt(
            workspace, args["slug"], args["prompt_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "add_model",
        "Register an extract model in a project so it can be made active or used "
        "in an experiment. Mints a fresh model_id and writes its config "
        "atomically (the id + ModelConfig shape are invariants — do NOT hand-"
        "write models/{id}.json). `provider` is one of anthropic|openai|google|"
        "codex (Gemini → google); `provider_model_id` is the provider's own name "
        "(e.g. \"gemini-2.5-flash\"). To copy another project's model, ws_read "
        "its models/{id}.json for the provider + provider_model_id first. Returns "
        "{model_id}. Follow with switch_active_model or create_experiment to use "
        "it. Rendering: browser → one-line confirm; headless → state the new "
        "model_id + label.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "label": {"type": "string"},
                "provider": {"type": "string", "enum": ["anthropic", "openai", "google", "codex"]},
                "provider_model_id": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["slug", "provider", "provider_model_id"],
        },
    )
    async def t_add_model(args: dict[str, Any]) -> dict[str, Any]:
        mid = await model_mod.create_model(
            workspace, args["slug"],
            label=args.get("label") or args["provider_model_id"],
            provider=args["provider"],
            provider_model_id=args["provider_model_id"],
            params=args.get("params") or {},
        )
        return {"content": [{"type": "text", "text": _json.dumps(
            {"model_id": mid}, ensure_ascii=False)}]}

    @tool(
        "switch_active_model",
        "Set the project's active model to the given model_id. Affects all "
        "subsequent extract calls when model_id arg is not explicitly provided.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "model_id": {"type": "string"},
            },
            "required": ["slug", "model_id"],
        },
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
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "experiment_id": {"type": "string"},
                "filename": {"type": "string"},
            },
            "required": ["slug", "experiment_id", "filename"],
        },
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
        try:
            payload = await experiment_mod.extract_with_experiment(
                workspace, args["slug"], args["experiment_id"], args["filename"],
                provider=exp_provider,
            )
        except Exception as e:  # noqa: BLE001 — provider failure envelope
            return {"content": [{"type": "text", "text": _json.dumps(
                _extract_provider_error(e), ensure_ascii=False)}]}
        return {"content": [{"type": "text", "text": _json.dumps(payload)}]}

    @tool(
        "run_experiment_eval",
        "Loop reviewed/ docs through the experiment's (prompt, model); writes "
        "per-doc extracts and computes overall + per-field + per-doc scores. "
        "Returns the eval dict and sets status='ran'. Pass use_llm_judge=false "
        "to skip the L2 LLM-as-judge layer (on by default).",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "experiment_id": {"type": "string"},
                "use_llm_judge": {"type": "boolean", "default": True},
            },
            "required": ["slug", "experiment_id"],
        },
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
            use_llm_judge=bool(args.get("use_llm_judge", True)),
        )
        return {"content": [{"type": "text", "text": _json.dumps(ev)}]}

    @tool(
        "promote_experiment",
        "Set the experiment's (prompt_id, model_id) as the project's active pair; "
        "clear predictions/_draft/ and re-seed from the experiment's extracts. "
        "Marks experiment status='promoted' (audit trail).",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "experiment_id": {"type": "string"},
            },
            "required": ["slug", "experiment_id"],
        },
    )
    async def t_promote_experiment(args: dict[str, Any]) -> dict[str, Any]:
        await experiment_mod.promote_experiment(
            workspace, args["slug"], args["experiment_id"],
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "bench_view",
        "Project-level bench leaderboard: one row per non-archived experiment "
        "+ a synthetic baseline row (when a baseline eval exists). Each row "
        "carries `{prompt_id, model_id, status, score, delta, summary_ts, "
        "cells: {field: {correct, total, strip}}}`. Pure read; no LLM calls. "
        "Use when the user asks 'which (prompt × model) is best' / 'show me "
        "the leaderboard' / '哪个 experiment 跑得最好' — single shot avoids "
        "the per-experiment ls+cat dance.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
            },
            "required": ["slug"],
        },
    )
    async def t_bench_view(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("bench_view")
            )}]}
        out = await bench_mod.bench_view(workspace, args["slug"])
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

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
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
            },
            "required": ["slug", "filename"],
        },
    )
    async def t_extract_one(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("extract_one")
            )}]}
        try:
            out = await extract_mod.extract_one(
                workspace, args["slug"], args["filename"], provider=provider
            )
        except Exception as e:  # noqa: BLE001 — provider failure envelope
            return {"content": [{"type": "text", "text": _json.dumps(
                _extract_provider_error(e), ensure_ascii=False)}]}
        return {"content": [{"type": "text", "text": str(out)}]}

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
                "corrections": {"type": "object"},
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
        # `corrections` is the per-field before/after diff; when present it both
        # lands in the reviewed file and bumps the tune-nudge counter. Only pass
        # through when non-empty so an absent/empty value doesn't move the counter.
        if args.get("corrections"):
            save_kwargs["corrections"] = args["corrections"]
        await reviewed_mod.save_reviewed(
            workspace,
            args["slug"],
            args["filename"],
            **save_kwargs,
        )
        return {"content": [{"type": "text", "text": "ok"}]}

    @tool(
        "score",
        "Compute field accuracy + doc accuracy by comparing draft "
        "predictions against reviewed examples via the L1 normalize + "
        "(optional) L2 LLM-judge + L3 presence pipeline. Persists a "
        "directory artifact under metrics/eval_{ts}/ "
        "(summary.json + cells.jsonl + matrix.csv + meta.json). Returns "
        "the summary. Pass use_llm_judge=false to skip the L2 LLM-as-judge "
        "layer (on by default).",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "use_llm_judge": {"type": "boolean", "default": True},
            },
            "required": ["slug"],
        },
    )
    async def t_score(args: dict[str, Any]) -> dict[str, Any]:
        result = await score_mod.run_eval(
            workspace, args["slug"],
            use_llm_judge=bool(args.get("use_llm_judge", True)),
        )
        return {"content": [{"type": "text", "text": _json.dumps(result.model_dump(mode='json'))}]}

    @tool(
        "readiness_check",
        "Run the publish readiness checklist for a project.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
            },
            "required": ["slug"],
        },
    )
    async def t_readiness_check(args: dict[str, Any]) -> dict[str, Any]:
        out = await publish_mod.readiness_check(workspace, args["slug"])
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    @tool(
        "contract_diff",
        "Diff current schema against the active version's frozen schema.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
            },
            "required": ["slug"],
        },
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
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
            },
            "required": ["slug"],
        },
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
        # No workspace arg: the keystore is global (true root), not team-scoped.
        out = await publish_mod.issue_api_key(user_id=user_id)
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

    @tool(
        "get_job",
        "Get current job status (latest turn, best F1 so far).",
        {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
            },
            "required": ["job_id"],
        },
    )
    async def t_get_job(args: dict[str, Any]) -> dict[str, Any]:
        info = await jobs_mod.get_job_impl(job_runner, job_id=args["job_id"])
        return {"content": [{"type": "text", "text": str(info)}]}

    @tool(
        "pause_job",
        "Pause a running job at the next turn boundary.",
        {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
            },
            "required": ["job_id"],
        },
    )
    async def t_pause_job(args: dict[str, Any]) -> dict[str, Any]:
        await jobs_mod.pause_job_impl(job_runner, job_id=args["job_id"])
        return {"content": [{"type": "text", "text": "paused"}]}

    @tool(
        "resume_job",
        "Resume a paused job.",
        {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
            },
            "required": ["job_id"],
        },
    )
    async def t_resume_job(args: dict[str, Any]) -> dict[str, Any]:
        await jobs_mod.resume_job_impl(job_runner, job_id=args["job_id"])
        return {"content": [{"type": "text", "text": "resumed"}]}

    @tool(
        "cancel_job",
        "Cancel a running or paused job. Discards remaining turns.",
        {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
            },
            "required": ["job_id"],
        },
    )
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
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
                "page": {"type": "integer"},
            },
            "required": ["slug", "filename", "page"],
        },
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
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["slug", "filename", "path"],
        },
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
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
                "tab_key": {"type": "string"},
            },
            "required": ["slug", "filename", "tab_key"],
        },
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
        {
            "type": "object",
            "properties": {
                "questions": {"type": "array"},
            },
            "required": ["questions"],
        },
    )
    async def t_ask_user(args: dict[str, Any]) -> dict[str, Any]:
        out = await ask_user_mod.ask_user(args.get("questions") or [])
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "ui_set_active_entity",
        "Switch the entity tab in a multi-entity doc. `idx` is 0-indexed. "
        "Pure navigation; no disk side-effect.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
                "idx": {"type": "integer"},
            },
            "required": ["slug", "filename", "idx"],
        },
    )
    async def t_ui_set_active_entity(args: dict[str, Any]) -> dict[str, Any]:
        out = await ui_actions_mod.ui_set_active_entity(
            slug=args["slug"], filename=args["filename"], idx=args["idx"],
        )
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}

    # ── headless discovery tools (stdio + remote MCP only) ─────────────────
    # Registered only when `headless=True` — see the build_emerge_mcp docstring
    # for why a remote agent (no shared filesystem) needs these but the
    # in-session chat agent (Bash-on-workspace) does not. HTTP twins already
    # exist (GET /lab/projects · .../docs · .../schema/raw) and are mapped in
    # test_symmetry_invariant.py, so the dual-form contract holds.
    @tool(
        "list_projects",
        "List all projects in the current team workspace. Returns "
        "[{slug, status, ...}]; `slug` is the handle every other tool takes. "
        "Call this FIRST when you don't yet know which projects exist — a "
        "remote MCP client cannot `ls` this server's disk. Rendering: headless "
        "→ print the projects as a list (slug + status).",
        {"type": "object", "properties": {}},
    )
    async def t_list_projects(args: dict[str, Any]) -> dict[str, Any]:
        out = await projects_mod.list_projects(workspace)
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "list_docs",
        "List the documents in a project's docs/ sample set. Returns "
        "[{filename, ...}]; `filename` is the doc handle for extract_one / "
        "read_doc_image / save_reviewed. Pairs with list_projects so a remote "
        "client can navigate without filesystem access. Rendering: headless → "
        "print the filenames.",
        {"type": "object", "properties": {"slug": {"type": "string"}}, "required": ["slug"]},
    )
    async def t_list_docs(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("list_docs"))}]}
        out = await docs_mod.list_docs(workspace, args["slug"])
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "read_prompt",
        "Read a project's active extraction PROMPT — the schema fields (each with "
        "its description) AND the project-level `global_notes`. These two halves "
        "together ARE the prompt the extract model runs, so this is the tool to "
        "answer 'what is this project's prompt / what does it extract'. Returns "
        "the active prompt variant: {schema:[{name,type,description,...}], "
        "global_notes, version, ...}. (The in-session agent Reads the prompt "
        "files directly; a remote client cannot.) Rendering: browser → one-line "
        "summary, the UI prompt panel shows the rest; headless → tabulate the "
        "fields (name · type · description), THEN print `global_notes` verbatim "
        "under its own heading — it is half the prompt, never omit it.",
        {"type": "object", "properties": {"slug": {"type": "string"}}, "required": ["slug"]},
    )
    async def t_read_prompt(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("slug") == _UNBOUND_SLUG:
            return {"content": [{"type": "text", "text": _json.dumps(
                _chat_not_bound_error("read_prompt"))}]}
        from app.tools.prompt import read_active_prompt
        pv = await read_active_prompt(workspace, args["slug"])
        return {"content": [{"type": "text", "text": _json.dumps(
            pv.model_dump(mode="json", exclude_none=True), ensure_ascii=False)}]}

    # ── workspace filesystem tools (headless only) ─────────────────────────
    # emerge's agent model is "paths are the API" (emerge_extractor.md). The
    # in-session agent does this with built-in Bash/Glob/Grep/Read on the shared
    # workspace FS; a REMOTE client's Bash is in a different sandbox, so we
    # re-expose the SAME six verbs as MCP tools scoped to the team root. One
    # surface restores every core object's read CRUD (objects ARE files). All
    # paths are contained to the team workspace by `workspace_fs._safe_ws_path`.
    # See plan 2026-06-09-filesystem-over-mcp.md.
    def _ws_result(payload: dict) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": _json.dumps(payload, ensure_ascii=False)}]}

    def _ws_guard(fn):
        from app.tools.workspace_fs import WsPathError

        def _run(args: dict[str, Any]) -> dict[str, Any]:
            try:
                return _ws_result(fn(args))
            except WsPathError as exc:
                return _ws_result({"error_code": "ws_path_blocked", "error_message_en": str(exc)})

        return _run

    @tool(
        "ws_list",
        "List a directory in the team workspace — the remote replacement for "
        "`ls`. `path` is relative to the workspace root (e.g. \".\" for all "
        "projects, \"{slug}\" for a project, \"{slug}/models\" for its model "
        "files). Set recursive=true for a tree. emerge's core objects ARE files "
        "(project.json, models/{id}.json, prompts/{id}.json, predictions/*.json) "
        "so this is how a remote client discovers everything the in-session "
        "agent would `ls`. Hidden dot/underscore entries are skipped. Rendering: "
        "headless → print the entries (name · type · size).",
        {"type": "object", "properties": {
            "path": {"type": "string", "default": "."},
            "recursive": {"type": "boolean", "default": False},
        }},
    )
    async def t_ws_list(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools import workspace_fs
        return _ws_guard(lambda a: workspace_fs.ws_list(
            workspace, a.get("path", "."), bool(a.get("recursive", False))))(args)

    @tool(
        "ws_read",
        "Read a UTF-8 text/JSON file in the team workspace — the remote `cat`. "
        "`path` is relative to the workspace root (e.g. \"{slug}/project.json\", "
        "\"{slug}/models/{id}.json\", \"{slug}/predictions/_draft/{f}.json\"). "
        "Use this to inspect any core object's raw on-disk form a remote client "
        "cannot `cat`. PDFs/images are refused — pull those with read_doc_image / "
        "pdf_render_page instead. Output truncates at 64 KiB. Rendering: headless "
        "→ print the file content.",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    )
    async def t_ws_read(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools import workspace_fs
        return _ws_guard(lambda a: workspace_fs.ws_read(workspace, a["path"]))(args)

    @tool(
        "ws_grep",
        "Recursive content search in the team workspace — the remote `grep`. "
        "`pattern` is a regex; `path` scopes the search (default whole "
        "workspace); optional `glob` filters filenames (e.g. \"*.json\"). Returns "
        "{file, line, text} hits (capped). Use it to find which project/model/"
        "prompt mentions a value when you don't know the path. Binary files and "
        "hidden sentinels are skipped. Rendering: headless → print the hits.",
        {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "default": "."},
            "glob": {"type": "string"},
        }, "required": ["pattern"]},
    )
    async def t_ws_grep(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools import workspace_fs
        return _ws_guard(lambda a: workspace_fs.ws_grep(
            workspace, a["pattern"], a.get("path", "."), a.get("glob")))(args)

    # ── document matching (reconciliation) ─────────────────────────────────
    # A match project references existing extract projects (anchor + sources)
    # and reconciles their extracted fields. Rules live in a versioned match
    # prompt (key_mappings + NL rules). See plan 2026-06-10-matching-p0-impl.md.
    @tool(
        "create_match_project",
        "Create a reconciliation (match) project that cross-checks one ANCHOR "
        "document set against one or more SOURCE sets — e.g. invoices ↔ "
        "{payments, purchase orders, receipts}. `anchor` and each of `sources` "
        "must be the slug of an EXISTING extract project (matching reads their "
        "already-extracted fields, it does not re-extract). Returns "
        "{project_id, slug}. Next: write_match_prompt to declare the key "
        "field-mappings + rules, then run_match.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "anchor": {"type": "string"},
                "sources": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name", "anchor", "sources"],
        },
    )
    async def t_create_match_project(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.match_project import MatchProjectError, create_match_project
        try:
            out = await create_match_project(
                workspace, name=args["name"], anchor=args["anchor"],
                sources=list(args.get("sources") or []),
            )
        except MatchProjectError as e:
            return {"content": [{"type": "text", "text": _json.dumps(
                {"error_code": e.error_code, "error_message_en": e.error_message_en},
                ensure_ascii=False)}]}
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "write_match_prompt",
        "Declare/refine a match project's rules — the prompt twin for matching. "
        "`mappings` is keyed by SOURCE project slug; each entry is a list of "
        "{anchor: <anchor field>, source: <source field>, tol: {type, abs?, "
        "days?}} pairs. tol.type ∈ exact | number (abs tolerance) | date_days "
        "(±days). `rules` is natural-language guidance for the L2 judge (e.g. "
        "'订单号是主键，必须精确对上；商户名不同写法但同一公司视为一致'). Upserts the "
        "project's single active match prompt (version bumps on content change). "
        "Returns the match-prompt id.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "mappings": {"type": "object"},
                "rules": {"type": "string"},
                "label": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["slug", "mappings"],
        },
    )
    async def t_write_match_prompt(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.match_prompt import write_match_prompt
        mpr_id = await write_match_prompt(
            workspace, args["slug"],
            mappings=args["mappings"], rules=args.get("rules", ""),
            label=args.get("label", ""), reason=args.get("reason", ""),
        )
        return {"content": [{"type": "text", "text": _json.dumps(
            {"match_prompt_id": mpr_id}, ensure_ascii=False)}]}

    @tool(
        "run_match",
        "Run a match project's reconciliation: reads the anchor + source "
        "extract results, judges candidate pairs (rules first, LLM tie-break on "
        "ambiguous cases), assigns 1:1 per source, and writes a result with one "
        "card per anchor (matched source doc or 'missing' per source) plus "
        "orphan source docs. Returns a summary {run_id, cards, complete, "
        "partial, unmatched, orphans}.",
        {"type": "object", "properties": {"slug": {"type": "string"}},
         "required": ["slug"]},
    )
    async def t_run_match(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.match_run import run_match
        out = await run_match(workspace, args["slug"])
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "save_reviewed_match",
        "Record the human-verified pairing for one anchor doc as ground truth. "
        "`expected` maps each source project slug → the TRUE source filename "
        "that pairs with this anchor, or null when the anchor correctly has no "
        "match in that source (e.g. an unpaid invoice). Feeds score_match.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "anchor_doc": {"type": "string"},
                "expected": {"type": "object"},
                "reason": {"type": "string"},
            },
            "required": ["slug", "anchor_doc", "expected"],
        },
    )
    async def t_save_reviewed_match(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.match_project import MatchProjectError
        from app.tools.match_review import save_reviewed_match
        try:
            out = await save_reviewed_match(
                workspace, args["slug"], anchor_doc=args["anchor_doc"],
                expected=dict(args.get("expected") or {}), reason=args.get("reason", ""),
            )
        except MatchProjectError as e:
            return {"content": [{"type": "text", "text": _json.dumps(
                {"error_code": e.error_code, "error_message_en": e.error_message_en},
                ensure_ascii=False)}]}
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    @tool(
        "score_match",
        "Score a match project against its reviewed ground truth: re-runs the "
        "match, then reports per-source precision/recall (over reviewed anchors "
        "only) + doc_completeness (fraction of reviewed anchors whose full "
        "pairing was exactly right). Returns {reviewed, per_source, "
        "doc_completeness}.",
        {"type": "object", "properties": {"slug": {"type": "string"}},
         "required": ["slug"]},
    )
    async def t_score_match(args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.match_review import score_match
        out = await score_match(workspace, args["slug"])
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}

    _tools = [
            t_create_project,
            t_delete_project,
            t_promote_chat_to_project,
            t_promote_attachment_to_docs,
            t_label_docs,
            t_set_labeler_model,
            t_get_labeler_config,
            t_get_project_config,
            t_set_translate_model,
            t_set_proposer_model,
            t_pdf_render_page,
            t_read_doc_image,
            t_extract_textlayer,
            t_translate_page,
            t_derive_schema,
            t_write_schema,
            t_import_schema_from_yaml,
            t_switch_active_prompt,
            t_add_model,
            t_switch_active_model,
            t_create_experiment,
            t_extract_with_experiment,
            t_run_experiment_eval,
            t_promote_experiment,
            t_bench_view,
            t_fork_project,
            t_create_match_project,
            t_write_match_prompt,
            t_run_match,
            t_save_reviewed_match,
            t_score_match,
            t_extract_one,
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
    ]
    if headless:
        _tools += [t_list_projects, t_list_docs, t_read_prompt,
                   t_ws_list, t_ws_read, t_ws_grep]
    # Stamp behavioural hints from the central buckets so the remote tools/list
    # carries them (drives a client's auto-approve / destructive-gate policy).
    # On the headless (remote/stdio) surface only, also wrap each handler to log
    # the call — emerge's own browser chat is the operator, not a teammate, so it
    # isn't counted. The usage log feeds P4 tool convergence (see tools/usage.py).
    for _t in _tools:
        _t.annotations = _annotate(_t.name)
        if headless:
            from app.tools.usage import wrap_handler
            _t.handler = wrap_handler(_t.handler, workspace, _t.name)
    return create_sdk_mcp_server(
        name="emerge_tools",
        version="0.0.1",
        tools=_tools,
    )


_EMERGE_TOOL_NAMES = (
    "create_project",
    "delete_project",
    "promote_chat_to_project",
    "promote_attachment_to_docs",
    "label_docs", "set_labeler_model", "get_labeler_config",
    "get_project_config", "set_translate_model", "set_proposer_model",
    "pdf_render_page", "read_doc_image", "extract_textlayer", "translate_page",
    "derive_schema", "write_schema", "import_schema_from_yaml",
    "switch_active_prompt", "switch_active_model",
    "create_experiment", "extract_with_experiment", "run_experiment_eval",
    "promote_experiment",
    "bench_view",
    "fork_project",
    "extract_one",
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
