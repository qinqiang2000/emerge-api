"""Gemini thinking-token accounting (`ProviderResult.thinking_tokens`).

Gemini 2.5+ bills reasoning at the output rate but reports it OUTSIDE
`candidates_token_count`: the SDK defines `total_token_count` as
`prompt + candidates + tool_use_prompt + thoughts`, so `thoughts_token_count`
is disjoint from the visible-output count rather than a sub-total of it.
Reading only `candidates_token_count` therefore dropped the dominant term —
measured on one PDF at temperature 0.0:

    model                     prompt  candidates  thoughts
    gemini-2.5-flash            6270         634      1710
    gemini-3-flash-preview      6544         819      5630

i.e. gemini-3 at its default level hid ~87% of output-side spend.

Pins here:
- thoughts land in `thinking_tokens`, and do NOT silently inflate
  `output_tokens` (whose meaning must stay comparable with historical rows)
- the field is `Optional[int]`: absent on pre-2.5 models, None when thinking
  is off, and the whole `usage_metadata` may itself be None
- `total_output_tokens` is the number to bill on
- adapters whose usage already folds reasoning into the output count leave
  `thinking_tokens` at 0, so the sum never double-counts

Network is fully mocked (`google.genai.Client` patched); no real API call.
The response mocks use the REAL SDK usage type or a plain SimpleNamespace,
never a bare MagicMock — an auto-vivified Mock attribute is coerced by
pydantic through `__int__` into a bogus `1` instead of failing loudly.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.provider.base import ProviderResult, TextBlock


_SCHEMA = {
    "type": "object",
    "properties": {"entities": {"type": "array"}},
    "required": ["entities"],
}


def _resp(usage: Any, payload: dict | None = None) -> MagicMock:
    """A GenerateContentResponse stub carrying `usage` verbatim.

    Only `.text` and `.usage_metadata` are read by the adapter; `usage` is
    passed through untouched so each test controls the exact shape.
    """
    resp = MagicMock()
    resp.text = json.dumps(payload if payload is not None else {"entities": []})
    resp.usage_metadata = usage
    return resp


async def _extract_with_usage(usage: Any) -> ProviderResult:
    """Run GoogleProvider.extract() against a mocked client returning `usage`."""
    from app.provider.google import GoogleProvider

    with patch("google.genai.Client") as mock_client_cls:
        client = mock_client_cls.return_value
        client.aio.models.generate_content = AsyncMock(return_value=_resp(usage))

        p = GoogleProvider(api_key="g-test", retry_base_delay=0.0)
        return await p.extract(
            model_id="gemini-3-flash-preview",
            system_prompt="x",
            user_content=[TextBlock(text="x")],
            response_schema=_SCHEMA,
        )


def _sdk_usage(**kwargs: Any):
    """Build the REAL `GenerateContentResponseUsageMetadata` the SDK parses into.

    Using the genuine type (rather than a hand-rolled stub) is what pins the
    field NAME — a typo'd `thought_token_count` would construct fine on a
    SimpleNamespace and silently read 0 forever.
    """
    from google.genai import types

    return types.GenerateContentResponseUsageMetadata(**kwargs)


# ── thoughts present ─────────────────────────────────────────────────────────


async def test_thoughts_token_count_is_captured() -> None:
    """The gemini-3 measurement: 5630 thinking tokens must not vanish."""
    result = await _extract_with_usage(
        _sdk_usage(
            prompt_token_count=6544,
            candidates_token_count=819,
            thoughts_token_count=5630,
        )
    )
    assert result.input_tokens == 6544
    assert result.thinking_tokens == 5630


async def test_thoughts_do_not_inflate_output_tokens() -> None:
    """`output_tokens` keeps its original meaning (visible candidates only).

    This is the historical-comparability guard: had we folded thoughts in,
    every pre-existing row would silently become incomparable with new ones.
    """
    result = await _extract_with_usage(
        _sdk_usage(
            prompt_token_count=6270,
            candidates_token_count=634,
            thoughts_token_count=1710,
        )
    )
    assert result.output_tokens == 634, "must stay the visible-candidates count"
    assert result.thinking_tokens == 1710
    # ...and the billable total is the sum, which is what cost must use.
    assert result.total_output_tokens == 2344


async def test_total_token_count_identity_holds() -> None:
    """Cross-check against the SDK's own definition of `total_token_count`:
    prompt + candidates + tool_use_prompt + thoughts. If our three numbers
    don't reconstruct it, we are dropping a term."""
    usage = _sdk_usage(
        prompt_token_count=6544,
        candidates_token_count=819,
        thoughts_token_count=5630,
        total_token_count=6544 + 819 + 5630,
    )
    result = await _extract_with_usage(usage)
    assert (
        result.input_tokens + result.total_output_tokens == usage.total_token_count
    )


# ── thoughts absent / None ───────────────────────────────────────────────────


async def test_thoughts_field_unset_defaults_to_zero() -> None:
    """Real SDK object with the field never populated — it defaults to None."""
    usage = _sdk_usage(prompt_token_count=100, candidates_token_count=50)
    assert usage.thoughts_token_count is None, "SDK default must be None"

    result = await _extract_with_usage(usage)
    assert result.thinking_tokens == 0
    assert (result.input_tokens, result.output_tokens) == (100, 50)
    assert result.total_output_tokens == 50


async def test_thoughts_explicitly_none_when_thinking_off() -> None:
    """`thinking_budget=0` (the OCR path) returns no thoughts at all."""
    result = await _extract_with_usage(
        _sdk_usage(
            prompt_token_count=6270,
            candidates_token_count=634,
            thoughts_token_count=None,
        )
    )
    assert result.thinking_tokens == 0
    assert result.output_tokens == 634


async def test_attribute_missing_entirely_on_legacy_usage() -> None:
    """Pre-2.5 / older API surfaces omit the attribute rather than null it.

    SimpleNamespace (not MagicMock) so the attribute genuinely raises
    AttributeError — this is what exercises the `getattr(..., 0)` default.
    """
    usage = SimpleNamespace(prompt_token_count=1200, candidates_token_count=300)
    assert not hasattr(usage, "thoughts_token_count")

    result = await _extract_with_usage(usage)
    assert result.thinking_tokens == 0
    assert (result.input_tokens, result.output_tokens) == (1200, 300)


async def test_usage_metadata_none_yields_all_zeros() -> None:
    """`GenerateContentResponse.usage_metadata` is itself Optional."""
    result = await _extract_with_usage(None)
    assert (result.input_tokens, result.output_tokens, result.thinking_tokens) == (0, 0, 0)
    assert result.total_output_tokens == 0


async def test_zero_thoughts_is_preserved_not_confused_with_missing() -> None:
    """A reported 0 and an absent field both mean 'no thinking spend' — pinned
    so the `or 0` fallback can't be swapped for something that mangles 0."""
    result = await _extract_with_usage(
        _sdk_usage(
            prompt_token_count=10, candidates_token_count=20, thoughts_token_count=0
        )
    )
    assert result.thinking_tokens == 0


# ── the ProviderResult contract itself ───────────────────────────────────────


def test_thinking_tokens_defaults_to_zero_for_other_providers() -> None:
    """Anthropic / OpenAI Chat Completions / OpenAI Responses already fold
    reasoning INTO their output count, so they must NOT set this field —
    doing so would double-count. The default keeps `total_output_tokens`
    correct for them without any adapter change."""
    r = ProviderResult(
        raw_json={}, model_id="claude-sonnet-4-6", input_tokens=100, output_tokens=50
    )
    assert r.thinking_tokens == 0
    assert r.total_output_tokens == 50


@pytest.mark.parametrize(
    ("out", "think", "expected"),
    [(0, 0, 0), (819, 5630, 6449), (634, 1710, 2344), (50, 0, 50)],
)
def test_total_output_tokens_is_the_sum(out: int, think: int, expected: int) -> None:
    r = ProviderResult(
        raw_json={}, model_id="m", output_tokens=out, thinking_tokens=think
    )
    assert r.total_output_tokens == expected


def test_mock_usage_must_not_leak_a_bogus_count() -> None:
    """Regression guard for the trap this fix walked into: a bare MagicMock
    auto-vivifies `thoughts_token_count`, and pydantic coerces that child Mock
    via `__int__` into `1` rather than raising — so a careless test mock
    reports one phantom thinking token and still passes. Any shared
    `usage_metadata` mock must pin the field explicitly."""
    leaky = MagicMock(prompt_token_count=100, candidates_token_count=50)
    coerced = ProviderResult(
        raw_json={},
        model_id="m",
        thinking_tokens=getattr(leaky, "thoughts_token_count", 0) or 0,
    )
    assert coerced.thinking_tokens == 1, "pydantic still coerces Mock via __int__"

    pinned = MagicMock(
        prompt_token_count=100, candidates_token_count=50, thoughts_token_count=0
    )
    assert (getattr(pinned, "thoughts_token_count", 0) or 0) == 0


# ── downstream: the only consumer that persists these counts ─────────────────
#
# `translate_page` is the sole reader of ProviderResult's token fields in the
# whole backend (every other `provider.extract()` call site discards usage), and
# it writes them into a per-page sidecar that the API returns verbatim. If the
# new count stops at the adapter, the fix is invisible — so pin the handoff.


def _text_pdf() -> bytes:
    import io

    import fitz

    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "Hello World, this is a long sentence.")
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


async def test_translate_page_persists_thinking_tokens(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.docs import upload_doc
    from app.tools.projects import create_project
    from app.tools.textlayer import extract_textlayer
    from app.tools.translate import translate_page

    pid = (await create_project(workspace, name="x"))["slug"]
    fname = (await upload_doc(workspace, pid, _text_pdf(), "doc.pdf"))["filename"]

    # Electronic PDFs still fire textlayer's OCR fallback; stub it empty so
    # this stays a pure textlayer-branch test (mirrors test_translate.py).
    ocr_stub = AsyncMock()
    ocr_stub.extract = AsyncMock(
        return_value=ProviderResult(raw_json={"lines": []}, model_id="stub")
    )
    monkeypatch.setattr(
        "app.provider.get_provider_for_model", lambda model_id, **_kw: ocr_stub
    )

    sidecar = await extract_textlayer(workspace, pid, fname, page=1)
    n = len(sidecar["spans"])
    assert n >= 1, "fixture must have at least one span"

    stub = AsyncMock()
    stub.extract = AsyncMock(
        return_value=ProviderResult(
            raw_json={"items": [{"index": i, "translated": "你好"} for i in range(n)]},
            model_id="gemini-3-flash-preview",
            input_tokens=6544,
            output_tokens=819,
            thinking_tokens=5630,
        )
    )
    monkeypatch.setattr(
        "app.tools.translate.get_provider_for_model", lambda model_id, **_kw: stub
    )

    result = await translate_page(workspace, pid, fname, page=1)

    assert result["input_tokens"] == 6544
    assert result["output_tokens"] == 819
    assert result["thinking_tokens"] == 5630

    # The sidecar is the cached artifact the route re-serves — the count must
    # survive the round trip to disk, not just the in-memory return.
    from app.workspace.paths import doc_translate_path

    cached = json.loads(
        doc_translate_path(
            workspace,
            pid,
            fname,
            page=1,
            target_lang="zh",
            mode=result["mode"],
            model_id=result["model_id"],
        ).read_text()
    )
    assert cached["thinking_tokens"] == 5630


async def test_translate_page_thinking_tokens_zero_for_non_thinking_provider(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider that leaves the field at its default must serialise a real
    0 — never a missing key or None, which would break arithmetic downstream."""
    from app.tools.docs import upload_doc
    from app.tools.projects import create_project
    from app.tools.textlayer import extract_textlayer
    from app.tools.translate import translate_page

    pid = (await create_project(workspace, name="x"))["slug"]
    fname = (await upload_doc(workspace, pid, _text_pdf(), "doc.pdf"))["filename"]

    ocr_stub = AsyncMock()
    ocr_stub.extract = AsyncMock(
        return_value=ProviderResult(raw_json={"lines": []}, model_id="stub")
    )
    monkeypatch.setattr(
        "app.provider.get_provider_for_model", lambda model_id, **_kw: ocr_stub
    )

    sidecar = await extract_textlayer(workspace, pid, fname, page=1)
    n = len(sidecar["spans"])

    stub = AsyncMock()
    stub.extract = AsyncMock(
        return_value=ProviderResult(
            raw_json={"items": [{"index": i, "translated": "你好"} for i in range(n)]},
            model_id="claude-sonnet-4-6",
            input_tokens=10,
            output_tokens=20,
        )
    )
    monkeypatch.setattr(
        "app.tools.translate.get_provider_for_model", lambda model_id, **_kw: stub
    )

    result = await translate_page(workspace, pid, fname, page=1)
    assert result["thinking_tokens"] == 0
    assert isinstance(result["thinking_tokens"], int)
