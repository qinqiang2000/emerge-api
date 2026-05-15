from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.provider.base import (
    ContentBlock,
    DocumentBlock,
    ImageBlock,
    Provider,
    ProviderResult,
    TextBlock,
)
from app.provider.retry import RetryableError, retry_async


_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
_CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_TOOL_NAME = "emit_extraction"


class CodexAuthError(RuntimeError):
    pass


def _codex_auth_path() -> Path:
    home = os.getenv("CODEX_HOME", "").strip()
    if not home:
        home = str(Path.home() / ".codex")
    return Path(home).expanduser() / "auth.json"


def _read_auth_payload() -> dict[str, Any]:
    path = _codex_auth_path()
    if not path.is_file():
        raise CodexAuthError(
            "Codex CLI credentials not found. Run `codex` and log in first."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CodexAuthError("Codex CLI auth file is unreadable.") from exc
    if not isinstance(payload, dict):
        raise CodexAuthError("Codex CLI auth file has invalid shape.")
    return payload


def _jwt_exp(access_token: str) -> int | None:
    parts = access_token.split(".")
    if len(parts) < 2:
        return None
    segment = parts[1]
    segment += "=" * (-len(segment) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(segment.encode("ascii")))
    except Exception:
        return None
    exp = payload.get("exp")
    return int(exp) if isinstance(exp, (int, float)) else None


def _access_token_expiring(access_token: str, skew_seconds: int = 120) -> bool:
    exp = _jwt_exp(access_token)
    if exp is None:
        return False
    return exp <= int(time.time()) + skew_seconds


async def _refresh_tokens(tokens: dict[str, Any]) -> dict[str, str]:
    refresh_token = tokens.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise CodexAuthError("Codex CLI auth is missing refresh_token.")
    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
        resp = await client.post(
            _CODEX_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": _CODEX_CLIENT_ID,
            },
        )
    if resp.status_code != 200:
        raise CodexAuthError(f"Codex token refresh failed with status {resp.status_code}.")
    data = resp.json()
    access = data.get("access_token")
    if not isinstance(access, str) or not access.strip():
        raise CodexAuthError("Codex token refresh response was missing access_token.")
    updated = dict(tokens)
    updated["access_token"] = access.strip()
    new_refresh = data.get("refresh_token")
    if isinstance(new_refresh, str) and new_refresh.strip():
        updated["refresh_token"] = new_refresh.strip()
    return updated


async def _resolve_codex_cli_access_token() -> str:
    payload = _read_auth_payload()
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        raise CodexAuthError("Codex CLI auth file is missing tokens.")
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access.strip():
        raise CodexAuthError("Codex CLI auth is missing access_token.")
    if not _access_token_expiring(access):
        return access.strip()

    updated_tokens = await _refresh_tokens(tokens)
    payload["tokens"] = updated_tokens
    payload["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path = _codex_auth_path()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    path.chmod(0o600)
    return str(updated_tokens["access_token"])


def _block_to_responses_part(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "input_text", "text": block.text}
    if isinstance(block, ImageBlock):
        return {
            "type": "input_image",
            "image_url": f"data:{block.media_type};base64,{block.data_b64}",
        }
    if isinstance(block, DocumentBlock):
        return {
            "type": "input_file",
            "filename": f"document.{block.media_type.rsplit('/', 1)[-1] or 'pdf'}",
            "file_data": f"data:{block.media_type};base64,{block.data_b64}",
        }
    raise ValueError(f"unknown block type: {block!r}")


def _extract_tool_payload(data: dict[str, Any]) -> dict[str, Any]:
    for item in data.get("output", []) if isinstance(data.get("output"), list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call" and item.get("name") == _TOOL_NAME:
            args = item.get("arguments")
            if isinstance(args, str):
                return json.loads(args)
            if isinstance(args, dict):
                return args
        for part in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return json.loads(text)
    text = data.get("output_text")
    if isinstance(text, str) and text.strip():
        return json.loads(text)
    raise RuntimeError(f"no extraction payload in codex response: {data}")


def _extract_tool_payload_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in events:
        if event.get("type") == "response.output_item.done":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "function_call":
                args = item.get("arguments")
                if item.get("name") == _TOOL_NAME and isinstance(args, str):
                    return json.loads(args)
        if event.get("type") == "response.function_call_arguments.done":
            args = event.get("arguments")
            if isinstance(args, str):
                return json.loads(args)
    for event in reversed(events):
        response = event.get("response")
        if isinstance(response, dict):
            try:
                return _extract_tool_payload(response)
            except RuntimeError:
                continue
    raise RuntimeError("no extraction payload in codex stream")


def _stream_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        response = event.get("response")
        if isinstance(response, dict) and isinstance(response.get("usage"), dict):
            return response["usage"]
    return {}


class CodexCliProvider(Provider):
    """OpenAI Codex Responses adapter using the Codex CLI login at ~/.codex/auth.json."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 180.0,
        retry_max_attempts: int = 3,
        retry_base_delay: float = 0.5,
    ) -> None:
        self._base_url = (base_url or os.getenv("EMERGE_CODEX_BASE_URL") or _CODEX_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._retry_max = retry_max_attempts
        self._retry_base = retry_base_delay

    async def extract(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_content: list[ContentBlock],
        response_schema: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> ProviderResult:
        params = params or {}
        parts = [_block_to_responses_part(block) for block in user_content]
        body: dict[str, Any] = {
            "model": model_id,
            "instructions": system_prompt,
            "input": [{"role": "user", "content": parts}],
            "tools": [
                {
                    "type": "function",
                    "name": _TOOL_NAME,
                    "description": "Emit the structured extraction result.",
                    "parameters": response_schema,
                    "strict": False,
                }
            ],
            "tool_choice": {"type": "function", "name": _TOOL_NAME},
            "store": False,
            "stream": True,
            "reasoning": {
                "effort": params.get("reasoning_effort", "medium"),
                "summary": "auto",
            },
        }
        # The ChatGPT Codex backend rejects `temperature`; keep extraction params
        # deterministic through schema/tool forcing rather than sampling knobs.
        if params.get("max_output_tokens"):
            body["max_output_tokens"] = params["max_output_tokens"]
        if params.get("fast") is True:
            body["service_tier"] = params.get("service_tier", "priority")
        elif params.get("service_tier"):
            body["service_tier"] = params["service_tier"]

        async def _call() -> ProviderResult:
            token = await _resolve_codex_cli_access_token()
            events: list[dict[str, Any]] = []
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/responses",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    if resp.status_code in (429, 502, 503, 504):
                        text = (await resp.aread()).decode(errors="replace")
                        raise RetryableError(f"codex {resp.status_code}: {text[:200]}")
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        events.append(json.loads(raw))
            usage = _stream_usage(events)
            return ProviderResult(
                raw_json=_extract_tool_payload_from_events(events),
                model_id=model_id,
                input_tokens=usage.get("input_tokens", 0) or 0,
                output_tokens=usage.get("output_tokens", 0) or 0,
            )

        return await retry_async(
            _call,
            max_attempts=self._retry_max,
            base_delay=self._retry_base,
        )
