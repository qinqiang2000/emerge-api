"""Per-turn event redactor for the chat stream.

Responsibilities:
- Persist (JSONL) MUST never contain plaintext API keys.
- SSE to the frontend MUST keep the freshly minted key plaintext for the
  one-time reveal modal (tool_result of issue_api_key) but MUST scrub the
  LLM's natural-language summary (agent_text) — the modal is the only
  sanctioned surface.

Asymmetry summary:
  | event              | persist (jsonl)                    | sse (frontend)                |
  | ------------------ | ---------------------------------- | ----------------------------- |
  | tool_result/issue  | key_plaintext → "[REDACTED]"       | passthrough (modal needs it)  |
  | agent_text         | ek_<32> → "[REDACTED-API-KEY]"     | ek_<32> → "[REDACTED-API-KEY]"|
  | anything else      | passthrough                        | passthrough                   |
"""
from __future__ import annotations

import json
import re
from typing import Any

_ISSUE_API_KEY_TOOL = "mcp__emerge_tools__issue_api_key"
_EK_KEY_RE = re.compile(r"ek_[A-Za-z0-9_-]{32}")
_KEY_PLAINTEXT_PLACEHOLDER = "[REDACTED]"
_AGENT_TEXT_PLACEHOLDER = "[REDACTED-API-KEY]"


class EventRedactor:
    """Stateful redactor: tracks tool_use_id → tool_name across one chat_turn."""

    def __init__(self) -> None:
        self._tool_names: dict[str, str] = {}

    def observe(self, etype: str, payload: dict[str, Any]) -> None:
        if etype == "tool_call":
            tid = payload.get("tool_use_id")
            tname = payload.get("tool_name")
            if isinstance(tid, str) and isinstance(tname, str):
                self._tool_names[tid] = tname

    def scrub_for_persist(self, etype: str, payload: dict[str, Any]) -> dict[str, Any]:
        if etype == "tool_result":
            tid = payload.get("tool_use_id", "")
            if self._tool_names.get(tid) == _ISSUE_API_KEY_TOOL:
                return _redact_issue_api_key_result(payload)
            return payload
        if etype == "agent_text":
            return _scrub_ek_keys(payload)
        return payload

    def scrub_for_sse(self, etype: str, payload: dict[str, Any]) -> dict[str, Any]:
        if etype == "agent_text":
            return _scrub_ek_keys(payload)
        return payload


def _redact_issue_api_key_result(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("result_text")
    if not isinstance(raw, str):
        return payload
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return payload
    if not isinstance(parsed, dict) or "key_plaintext" not in parsed:
        return payload
    parsed["key_plaintext"] = _KEY_PLAINTEXT_PLACEHOLDER
    return {**payload, "result_text": json.dumps(parsed, ensure_ascii=False)}


def _scrub_ek_keys(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("text")
    if not isinstance(text, str):
        return payload
    scrubbed = _EK_KEY_RE.sub(_AGENT_TEXT_PLACEHOLDER, text)
    if scrubbed == text:
        return payload
    return {**payload, "text": scrubbed}
