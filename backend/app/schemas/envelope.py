from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error_code: str
    error_message_en: str


T = TypeVar("T")


class ToolResult(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    data: Optional[T] = None
    error: Optional[ErrorEnvelope] = None
