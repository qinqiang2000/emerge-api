"""M14 — `RunStamp` + `build_stamp` + `mint_run_id` unit tests."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.eval.run_stamp import build_stamp, mint_run_id
from app.schemas.model_config import ModelConfig
from app.schemas.prompt_variant import PromptVariant
from app.schemas.run import RunStamp


_PROMPT = PromptVariant(
    prompt_id="pr_baseline",
    label="Baseline",
    schema=[],
    global_notes="",
    derived_from=None,
    created_at="2026-05-21T00:00:00+00:00",
    updated_at="2026-05-21T00:00:00+00:00",
)
_MODEL = ModelConfig(
    model_id="m_default",
    label="Default",
    provider="google",
    provider_model_id="gemini-2.5-flash",
    params={"temperature": 0.0},
    created_at="2026-05-21T00:00:00+00:00",
)


def test_mint_run_id_format() -> None:
    """`r_{ts}_{slug(extract_model)}_{prompt_id}` — stable label, not an
    index key. Special chars in extract_model collapse to underscores so the
    id is filename-safe."""
    rid = mint_run_id(
        "2026-05-21T16-23-04Z", "gemini-2.5-flash", "pr_baseline",
    )
    assert rid == "r_2026-05-21T16-23-04Z_gemini-2.5-flash_pr_baseline"
    # Weird chars in model id (homebrew variants) collapse to `_`.
    rid2 = mint_run_id("ts", "openai/gpt-4 vision", "pr_x")
    assert "/" not in rid2
    assert " " not in rid2
    # Missing prompt / model still produce a parseable id.
    assert mint_run_id("ts", None, None) == "r_ts_unknown_unknown"


def test_build_stamp_baseline_from_model_and_prompt() -> None:
    s = build_stamp("baseline", _MODEL, _PROMPT)
    assert isinstance(s, RunStamp)
    assert s.kind == "baseline"
    assert s.model_id == "m_default"
    assert s.extract_model == "gemini-2.5-flash"
    assert s.model_label == "Default"
    assert s.prompt_id == "pr_baseline"
    assert s.prompt_label == "Baseline"
    # run_id matches `mint_run_id(s.ts, ...)`
    assert s.run_id.endswith("_gemini-2.5-flash_pr_baseline")
    assert s.run_id.startswith("r_")


def test_build_stamp_pre_label_override() -> None:
    """Pre-label has no project ModelConfig; the labeler model id is passed
    via `extract_model_override`."""
    s = build_stamp(
        "pre_label", None, _PROMPT, extract_model_override="gemini-pro-latest",
    )
    assert s.kind == "pre_label"
    assert s.extract_model == "gemini-pro-latest"
    assert s.model_id is None  # no project model record
    assert s.prompt_id == "pr_baseline"
    assert s.prompt_label == "Baseline"


def test_run_stamp_forbids_extra_keys() -> None:
    """`extra='forbid'` so downstream code that strictly parses RunStamp
    doesn't silently accept stale fields."""
    with pytest.raises(ValidationError):
        RunStamp(
            run_id="r_x",
            ts="2026-05-21",
            kind="baseline",
            unknown_extra="boom",  # type: ignore[call-arg]
        )
