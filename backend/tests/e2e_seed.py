"""Seed a project + doc + prediction so the e2e review-mode test has data.

Invoked from playwright config's webServer command before uvicorn starts.
"""
import asyncio
import os
from pathlib import Path

from app.chat.log import append_event, ensure_chat_meta
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir


async def main() -> None:
    workspace = Path(os.environ.get("EMERGE_WORKSPACE_ROOT", "./.tmp_workspace"))
    workspace.mkdir(parents=True, exist_ok=True)
    pid = await create_project(workspace, name="e2e-test")
    await write_schema(
        workspace,
        pid,
        [
            SchemaField(name="invoice_number", type=FieldType.STRING, description="Invoice no"),
            SchemaField(name="total_amount", type=FieldType.NUMBER, description="Total"),
        ],
        reason="e2e seed",
        allow_structural=True,
    )
    fixture = Path(__file__).parent / "fixtures" / "invoice_sample.pdf"
    did = await upload_doc(workspace, pid, fixture.read_bytes(), "sample.pdf")
    pdir = predictions_draft_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        pdir / f"{did}.json",
        {
            "entities": [{"invoice_number": "DRAFT-1", "total_amount": 100.0}],
            "_evidence": [{"invoice_number": 1, "total_amount": 1}],
        },
    )

    eval_did = await upload_doc(workspace, pid, fixture.read_bytes(), "eval_gt.pdf")
    atomic_write_json(
        pdir / f"{eval_did}.json",
        {"entities": [{"invoice_number": "DRAFT-1", "total_amount": 100.0}]},
    )
    await save_reviewed(
        workspace,
        pid,
        eval_did,
        entities=[{"invoice_number": "DRAFT-1", "total_amount": 100.0}],
        source=ReviewedSource.MANUAL,
    )
    print(f"  + reviewed for {eval_did}")

    # Seed a chat log + meta sidecar so the chat-history popover e2e has something to list.
    seed_chat_id = "c_seed00000001"
    await append_event(workspace, pid, seed_chat_id, {"type": "user", "text": "/improve weak fields"})
    await append_event(workspace, pid, seed_chat_id, {"type": "agent_text", "text": "Seeded session for the e2e."})
    ensure_chat_meta(
        workspace,
        pid,
        seed_chat_id,
        first_user_message="/improve weak fields",
        has_attachments=False,
    )
    print(f"  + seeded chat {seed_chat_id}")
    print(f"SEEDED pid={pid} did={did}")


if __name__ == "__main__":
    asyncio.run(main())
