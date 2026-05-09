import pytest
from app.chat.service import _emerge_only_permission
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny


@pytest.mark.asyncio
@pytest.mark.parametrize("name,expected", [
    ("mcp__emerge_tools__list_projects", PermissionResultAllow),
    ("mcp__emerge_tools__write_schema", PermissionResultAllow),
    ("Glob", PermissionResultDeny),
    ("Read", PermissionResultDeny),
    ("Bash", PermissionResultDeny),
    ("mcp__some_other_server__do_thing", PermissionResultDeny),
    ("", PermissionResultDeny),
])
async def test_emerge_only_permission_classifies(name, expected) -> None:
    result = await _emerge_only_permission(name, {}, None)  # ctx unused
    assert isinstance(result, expected)
