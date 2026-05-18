"""``ask_user`` tool: structured user-question round-trip.

Mirrors the Claude Code AskUserQuestion contract — the agent passes a list
of questions, each with header (≤12-char chip), question text, multiSelect
flag, and 2-4 options of ``{label, description}``. The tool body pushes the
payload onto the active chat's SSE stream as an ``ask_user_request`` event,
blocks on a per-(chat_id, request_id) future, and returns the user's
selections as ``{ok: true, answers: [{question_index, selected: [...]}]}``.

Why this is a real MCP tool and not a permission-gate hijack: the answer is
structured data, not approve/deny. Returning labels as a tool result is the
contract the agent expects — same shape Claude Code's built-in would
produce. Permission-gate deny-with-message would fool the agent into seeing
the call as failed. Keeping ask_user separate also makes the operation
addressable (one named op, agent + HTTP + kbd can each be a client) per
``operations-first`` design.
"""
from __future__ import annotations

from typing import Any

from app.chat.ask_user import request_user_answer
from app.chat.sse_context import current_chat_id, current_sse_writer


# Cap matches Claude Code AskUserQuestion: 1-4 questions, each with 2-4
# options. We enforce server-side so a malformed tool call surfaces a useful
# error envelope instead of confusing the UI.
_MAX_QUESTIONS = 4
_MIN_OPTIONS = 2
_MAX_OPTIONS = 4
_HEADER_MAX_LEN = 12


def _err(code: str, msg: str) -> dict[str, Any]:
    return {"ok": False, "error": {"error_code": code, "error_message_en": msg}}


def _validate_questions(qs: Any) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """Return (normalised_list, None) on success, (None, error_envelope) on
    failure. We re-emit a sanitised payload to the SSE event so the frontend
    never sees stray fields the agent may have included."""
    if not isinstance(qs, list) or not qs:
        return None, _err("ask_user_invalid_input", "questions must be a non-empty list")
    if len(qs) > _MAX_QUESTIONS:
        return None, _err(
            "ask_user_invalid_input",
            f"too many questions ({len(qs)}); max {_MAX_QUESTIONS}",
        )
    out: list[dict[str, Any]] = []
    for i, q in enumerate(qs):
        if not isinstance(q, dict):
            return None, _err("ask_user_invalid_input", f"questions[{i}] must be an object")
        question = q.get("question")
        options = q.get("options")
        if not isinstance(question, str) or not question.strip():
            return None, _err(
                "ask_user_invalid_input",
                f"questions[{i}].question must be a non-empty string",
            )
        if not isinstance(options, list):
            return None, _err(
                "ask_user_invalid_input",
                f"questions[{i}].options must be a list",
            )
        if not (_MIN_OPTIONS <= len(options) <= _MAX_OPTIONS):
            return None, _err(
                "ask_user_invalid_input",
                f"questions[{i}].options must have {_MIN_OPTIONS}-{_MAX_OPTIONS} entries; "
                f"got {len(options)}",
            )
        norm_options: list[dict[str, Any]] = []
        for j, o in enumerate(options):
            if not isinstance(o, dict):
                return None, _err(
                    "ask_user_invalid_input",
                    f"questions[{i}].options[{j}] must be an object",
                )
            label = o.get("label")
            if not isinstance(label, str) or not label.strip():
                return None, _err(
                    "ask_user_invalid_input",
                    f"questions[{i}].options[{j}].label must be a non-empty string",
                )
            desc = o.get("description")
            if desc is not None and not isinstance(desc, str):
                return None, _err(
                    "ask_user_invalid_input",
                    f"questions[{i}].options[{j}].description must be a string when provided",
                )
            entry: dict[str, Any] = {"label": label}
            if isinstance(desc, str) and desc:
                entry["description"] = desc
            norm_options.append(entry)
        header = q.get("header")
        if header is not None and not isinstance(header, str):
            return None, _err(
                "ask_user_invalid_input",
                f"questions[{i}].header must be a string when provided",
            )
        if isinstance(header, str) and len(header) > _HEADER_MAX_LEN:
            # Truncate rather than reject — the chip will render fine,
            # and rejecting on a chip-length quibble is hostile UX.
            header = header[:_HEADER_MAX_LEN]
        multi = q.get("multiSelect")
        if multi is not None and not isinstance(multi, bool):
            return None, _err(
                "ask_user_invalid_input",
                f"questions[{i}].multiSelect must be a boolean when provided",
            )
        norm_q: dict[str, Any] = {
            "question": question,
            "options": norm_options,
            "multiSelect": bool(multi),
        }
        if isinstance(header, str) and header:
            norm_q["header"] = header
        out.append(norm_q)
    return out, None


async def ask_user(questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Push a structured question to the chat client and await the user's
    answer. Returns ``{ok, answers}`` where each answer is
    ``{question_index, selected: [{option_index, label}]}``."""
    norm, err = _validate_questions(questions)
    if err is not None:
        return err
    assert norm is not None  # for type checkers

    chat_id = current_chat_id.get()
    writer = current_sse_writer.get()
    if chat_id is None or writer is None:
        return _err(
            "ask_user_no_session",
            "ask_user requires an active chat session; no SSE writer is in scope",
        )

    return await request_user_answer(
        chat_id=chat_id,
        questions=norm,
        sse_writer=writer,
    )
