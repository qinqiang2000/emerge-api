from app.schemas.schema_field import FieldType, SchemaField
from app.tools.publish import contract_diff


def _f(name, type_=FieldType.STRING, *, enum=None, children=None):
    kwargs = {"name": name, "type": type_, "description": "x"}
    if enum is not None:
        kwargs["enum"] = enum
    if children is not None:
        kwargs["children"] = children
    return SchemaField(**kwargs)


def test_no_change_returns_empty() -> None:
    a = [_f("a"), _f("b")]
    b = [_f("a"), _f("b")]
    diff = contract_diff(a, b)
    assert diff == {
        "added": [], "removed": [], "type_changed": [], "enum_narrowed": [],
        "is_breaking": False,
    }


def test_added_only_is_compatible() -> None:
    diff = contract_diff([_f("a")], [_f("a"), _f("b")])
    assert diff["added"] == ["b"]
    assert diff["is_breaking"] is False


def test_removed_field_is_breaking() -> None:
    diff = contract_diff([_f("a"), _f("b")], [_f("a")])
    assert diff["removed"] == ["b"]
    assert diff["is_breaking"] is True


def test_type_change_is_breaking() -> None:
    diff = contract_diff(
        [_f("a", FieldType.STRING)],
        [_f("a", FieldType.NUMBER)],
    )
    assert diff["type_changed"] == [
        {"name": "a", "prev_type": "string", "candidate_type": "number"},
    ]
    assert diff["is_breaking"] is True


def test_enum_narrowed_is_breaking() -> None:
    diff = contract_diff(
        [_f("k", enum=["x", "y", "z"])],
        [_f("k", enum=["x", "y"])],
    )
    assert diff["enum_narrowed"] == [
        {"name": "k", "prev_enum": ["x", "y", "z"], "candidate_enum": ["x", "y"]},
    ]
    assert diff["is_breaking"] is True


def test_enum_added_where_none_was_is_breaking() -> None:
    diff = contract_diff([_f("k")], [_f("k", enum=["a", "b"])])
    assert diff["enum_narrowed"] == [
        {"name": "k", "prev_enum": None, "candidate_enum": ["a", "b"]},
    ]
    assert diff["is_breaking"] is True


def test_enum_widened_is_compatible() -> None:
    diff = contract_diff(
        [_f("k", enum=["x"])],
        [_f("k", enum=["x", "y"])],
    )
    assert diff == {
        "added": [], "removed": [], "type_changed": [], "enum_narrowed": [],
        "is_breaking": False,
    }


def test_enum_dropped_is_compatible() -> None:
    diff = contract_diff([_f("k", enum=["x"])], [_f("k")])
    assert diff["is_breaking"] is False


def test_mixed_add_and_remove() -> None:
    diff = contract_diff([_f("a"), _f("b")], [_f("a"), _f("c")])
    assert sorted(diff["added"]) == ["c"]
    assert sorted(diff["removed"]) == ["b"]
    assert diff["is_breaking"] is True


import pytest
from pathlib import Path


async def test_contract_diff_mcp_tool_works_on_fresh_project(
    workspace: Path,
    stub_provider,
) -> None:
    """Regression: the MCP-exposed `t_contract_diff` must read the active prompt
    via read_schema, not schema.json directly. After M9.1 new projects don't
    write schema.json, so the old code would FileNotFoundError."""
    from unittest.mock import MagicMock
    import json as _json
    from app.tools import build_emerge_mcp
    from app.tools.projects import create_project
    from app.tools.prompt import write_prompt
    from app.schemas.schema_field import FieldType, SchemaField
    import mcp.types as mcp_types

    pid = (await create_project(workspace, name="x"))["slug"]
    await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
    )

    server = build_emerge_mcp(workspace=workspace, provider=stub_provider, job_runner=MagicMock())
    instance = server["instance"]
    call_handler = instance.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name="contract_diff", arguments={"project_id": pid}),
    )
    result = await call_handler(req)
    payload_text = result.root.content[0].text  # type: ignore[index]
    payload = _json.loads(payload_text)
    assert payload["added"] == ["invoice_no"]
    assert payload["is_breaking"] is False
