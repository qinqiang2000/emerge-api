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
# A trailing run that could be the *start* of an in-progress `ek_<32>` key:
# a lone `e`, `ek`, `ek_`, or `ek_` + up to 31 key chars (32 completes it and
# is caught by `_EK_KEY_RE` instead). Anchored to the end so it only ever
# matches the tail of the accumulated text. See `_scrub_delta`.
_EK_PARTIAL_RE = re.compile(r"e(?:k(?:_[A-Za-z0-9_-]{0,31})?)?$")
_KEY_PLAINTEXT_PLACEHOLDER = "[REDACTED]"
_AGENT_TEXT_PLACEHOLDER = "[REDACTED-API-KEY]"
_DELTA_EVENTS = ("agent_text_delta", "agent_thinking")


class EventRedactor:
    """Stateful redactor: tracks tool_use_id → tool_name across one chat_turn."""

    def __init__(self) -> None:
        self._tool_names: dict[str, str] = {}
        # Per-content-block accumulator for streaming deltas: index → running
        # raw text + how much has already been emitted (over the scrubbed view).
        # Reset on each `_block_start` so a fresh content block starts clean.
        self._delta_bufs: dict[int, dict[str, Any]] = {}

    def observe(self, etype: str, payload: dict[str, Any]) -> None:
        if etype == "tool_call":
            tid = payload.get("tool_use_id")
            tname = payload.get("tool_name")
            if isinstance(tid, str) and isinstance(tname, str):
                self._tool_names[tid] = tname
        elif etype == "_block_start":
            idx = payload.get("index")
            if isinstance(idx, int):
                self._delta_bufs[idx] = {"raw": "", "emitted": 0}

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
        if etype in _DELTA_EVENTS:
            return self._scrub_delta(payload)
        if etype == "agent_text":
            return _scrub_ek_keys(payload)
        return payload

    def _scrub_delta(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Emit only the portion of a streaming delta that is provably free of
        a (possibly split-across-deltas) `ek_<32>` API key.

        A per-block buffer accumulates the raw text; we hold back any trailing
        run that could still grow into a key (`_EK_PARTIAL_RE`) and scrub any
        fully-formed key in the safe prefix. ``emitted`` tracks the length of
        the scrubbed prefix already sent, so each call returns just the new
        safe suffix. The `index` field is internal and stripped here.
        """
        idx = payload.get("index")
        key = idx if isinstance(idx, int) else 0
        buf = self._delta_bufs.setdefault(key, {"raw": "", "emitted": 0})
        delta = payload.get("text", "")
        if isinstance(delta, str):
            buf["raw"] += delta
        raw: str = buf["raw"]
        m = _EK_PARTIAL_RE.search(raw)
        hold_start = m.start() if m else len(raw)
        safe = _EK_KEY_RE.sub(_AGENT_TEXT_PLACEHOLDER, raw[:hold_start])
        emit = safe[buf["emitted"]:]
        buf["emitted"] = len(safe)
        out: dict[str, Any] = {"text": emit}
        pid = payload.get("parent_tool_use_id")
        if isinstance(pid, str):
            out["parent_tool_use_id"] = pid
        return out


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
