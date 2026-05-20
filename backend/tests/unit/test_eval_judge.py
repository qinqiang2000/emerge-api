from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.eval.judge import _hash_pair, judge_batch
from app.provider.base import ProviderResult
from app.schemas.schema_field import SchemaField
from app.workspace.paths import eval_judge_cache_path


def _stub_provider(monkeypatch: pytest.MonkeyPatch, payload: dict) -> AsyncMock:
    """Patch get_provider_for_model in app.eval.judge to return a mock provider
    whose .extract returns ProviderResult(raw_json=payload, ...). Returns the
    AsyncMock for .extract so the test can assert call counts."""
    extract_mock = AsyncMock(return_value=ProviderResult(
        raw_json=payload, model_id="stub", input_tokens=0, output_tokens=0,
    ))
    provider_obj = AsyncMock()
    provider_obj.extract = extract_mock
    monkeypatch.setattr(
        "app.eval.judge.get_provider_for_model",
        lambda mid: provider_obj,
    )
    return extract_mock


def _field(name: str = "x") -> SchemaField:
    return SchemaField(name=name, type="string", description="…")


async def test_empty_input(workspace: Path) -> None:
    out, skipped = await judge_batch(workspace, "p_abc", [])
    assert out == []
    assert skipped == 0


async def test_cache_miss_calls_provider_and_writes_cache(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extract_mock = _stub_provider(monkeypatch, {
        "verdicts": [
            {"idx": 0, "equivalent": True, "reason": "same"},
        ],
    })
    f = _field("addr")
    out, skipped = await judge_batch(
        workspace, "p_abc",
        [(f, "广东省深圳市", "广东省 深圳市")],
    )
    assert skipped == 0
    assert out[0] is not None
    assert out[0].equivalent is True
    assert out[0].reason == "same"
    assert out[0].cached is False
    assert extract_mock.await_count == 1
    sha = _hash_pair("addr", "广东省深圳市", "广东省 深圳市")
    assert eval_judge_cache_path(workspace, "p_abc", sha).exists()


async def test_cache_hit_skips_provider(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # First call populates cache.
    _stub_provider(monkeypatch, {
        "verdicts": [{"idx": 0, "equivalent": True, "reason": "cached"}],
    })
    f = _field("addr")
    await judge_batch(workspace, "p_abc", [(f, "a", "b")])
    # Second call: provider should NOT be invoked.
    extract_mock2 = _stub_provider(monkeypatch, {"verdicts": []})
    out, skipped = await judge_batch(workspace, "p_abc", [(f, "a", "b")])
    assert skipped == 0
    assert out[0] is not None
    assert out[0].equivalent is True
    assert out[0].cached is True
    assert extract_mock2.await_count == 0


async def test_budget_exceeded_leaves_remaining_unjudged(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extract_mock = _stub_provider(monkeypatch, {
        "verdicts": [
            {"idx": 0, "equivalent": True, "reason": "ok"},
            {"idx": 1, "equivalent": True, "reason": "ok"},
        ],
    })
    f = _field("f")
    pairs = [(f, f"truth-{i}", f"pred-{i}") for i in range(5)]
    out, skipped = await judge_batch(workspace, "p_abc", pairs, budget=2)
    assert skipped == 3
    assert out[0] is not None
    assert out[1] is not None
    assert out[2] is None
    assert out[3] is None
    assert out[4] is None
    assert extract_mock.await_count == 1  # one call covers the budgeted pairs


async def test_malformed_response_keeps_l1(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_provider(monkeypatch, {"oops": "no verdicts key"})
    f = _field("f")
    out, skipped = await judge_batch(workspace, "p_abc", [(f, "a", "b")])
    assert out == [None]
    assert skipped == 1


async def test_provider_exception_keeps_l1(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_obj = AsyncMock()
    provider_obj.extract = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(
        "app.eval.judge.get_provider_for_model",
        lambda mid: provider_obj,
    )
    f = _field("f")
    out, skipped = await judge_batch(workspace, "p_abc", [(f, "a", "b")])
    assert out == [None]
    assert skipped == 1


async def test_hash_includes_field_name(workspace: Path) -> None:
    sha_a = _hash_pair("field_a", "x", "y")
    sha_b = _hash_pair("field_b", "x", "y")
    assert sha_a != sha_b


async def test_different_pair_distinct_caches(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Field a returns False, field b returns True; the cache must keep them
    # apart so re-judging the same (truth, pred) under another field can
    # land on a different verdict.
    fa = _field("a")
    fb = _field("b")
    _stub_provider(monkeypatch, {
        "verdicts": [
            {"idx": 0, "equivalent": False, "reason": "diff under a"},
            {"idx": 1, "equivalent": True, "reason": "same under b"},
        ],
    })
    out, skipped = await judge_batch(
        workspace, "p_abc",
        [(fa, "x", "y"), (fb, "x", "y")],
    )
    assert skipped == 0
    assert out[0].equivalent is False
    assert out[1].equivalent is True
    sha_a = _hash_pair("a", "x", "y")
    sha_b = _hash_pair("b", "x", "y")
    assert sha_a != sha_b
    assert eval_judge_cache_path(workspace, "p_abc", sha_a).exists()
    assert eval_judge_cache_path(workspace, "p_abc", sha_b).exists()
