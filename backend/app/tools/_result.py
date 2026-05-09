from typing import Any

from app.schemas.envelope import ErrorEnvelope, ToolResult


def tool_ok(data: Any) -> ToolResult:
    return ToolResult(ok=True, data=data)


def tool_err(code: str, message: str) -> ToolResult:
    return ToolResult(ok=False, error=ErrorEnvelope(error_code=code, error_message_en=message))
