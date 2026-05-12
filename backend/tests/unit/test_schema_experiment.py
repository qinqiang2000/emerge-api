from app.schemas.experiment import Experiment, ExperimentEval


def test_experiment_minimum_fields_default_status_draft():
    ex = Experiment(
        experiment_id="ex_abcdef012345",
        label="trial 1",
        prompt_id="pr_baseline",
        model_id="m_default",
        created_at="2026-05-13T00:00:00Z",
    )
    assert ex.status == "draft"
    assert ex.eval is None
    assert ex.promoted_at is None
    assert ex.notes == ""


def test_experiment_with_eval_roundtrip():
    blob = {
        "experiment_id": "ex_abcdef012345",
        "label": "trial 2",
        "prompt_id": "pr_baseline",
        "model_id": "m_default",
        "status": "ran",
        "created_at": "2026-05-13T00:00:00Z",
        "notes": "tried adding 'top-right' hint",
        "eval": {
            "ran_at": "2026-05-13T00:01:00Z",
            "score": 0.91,
            "per_field": {"supplier": 1.0, "amount": 0.85},
            "per_doc": {"d_aaa": 0.95, "d_bbb": 0.87},
            "run_id": "r_1715567890",
            "coverage": 2,
        },
    }
    ex = Experiment(**blob)
    assert ex.eval is not None
    assert ex.eval.score == 0.91
    assert ex.eval.per_field["supplier"] == 1.0
    # round-trip preserves shape
    assert Experiment(**ex.model_dump(mode="json")).eval == ex.eval


def test_experiment_rejects_unknown_status():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Experiment(
            experiment_id="ex_abcdef012345",
            label="x",
            prompt_id="pr_x",
            model_id="m_x",
            status="bogus",  # type: ignore[arg-type]
            created_at="2026-05-13T00:00:00Z",
        )
