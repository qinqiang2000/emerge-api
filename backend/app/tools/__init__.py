from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server, tool

from app.provider.base import Provider
from app.schemas.schema_field import SchemaField
from app.tools import docs as docs_mod
from app.tools import extract as extract_mod
from app.tools import projects as projects_mod
from app.tools import schema as schema_mod


def build_emerge_mcp(workspace: Path, provider: Provider) -> McpSdkServerConfig:
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
            t_extract_one,
            t_extract_batch,
        ],
    )
