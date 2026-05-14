from pathlib import Path

from app.workspace.paths import (
    project_dir,
    schema_path,
    project_json_path,
    docs_dir,
    doc_path,
    doc_meta_path,
    predictions_draft_dir,
    versions_dir,
    chats_dir,
    keys_path,
    job_locks_dir,
    reviewed_dir,
    reviewed_path,
    next_version_n,
    parse_version_id,
    version_path,
)


def test_project_dir_under_workspace(workspace: Path) -> None:
    assert project_dir(workspace, "p_abc") == workspace / "p_abc"


def test_schema_path(workspace: Path) -> None:
    assert schema_path(workspace, "p_abc") == workspace / "p_abc" / "schema.json"


def test_project_json_path(workspace: Path) -> None:
    assert project_json_path(workspace, "p_abc") == workspace / "p_abc" / "project.json"


def test_docs_dir(workspace: Path) -> None:
    assert docs_dir(workspace, "p_abc") == workspace / "p_abc" / "docs"


def test_doc_path_pdf(workspace: Path) -> None:
    # Post-d_xxx: doc_path is keyed by filename; the file's name on disk IS
    # the doc handle (including its extension).
    assert doc_path(workspace, "p_abc", "inv-001.pdf") == workspace / "p_abc" / "docs" / "inv-001.pdf"


def test_doc_meta_path(workspace: Path) -> None:
    # Sidecars live under `docs/.meta/<filename>.json` (a dotfile dir so glob
    # of `docs/*` ignores it).
    assert doc_meta_path(workspace, "p_abc", "inv-001.pdf") == (
        workspace / "p_abc" / "docs" / ".meta" / "inv-001.pdf.json"
    )


def test_predictions_draft_dir(workspace: Path) -> None:
    assert predictions_draft_dir(workspace, "p_abc") == workspace / "p_abc" / "predictions" / "_draft"


def test_versions_dir(workspace: Path) -> None:
    assert versions_dir(workspace, "p_abc") == workspace / "p_abc" / "versions"


def test_chats_dir(workspace: Path) -> None:
    assert chats_dir(workspace, "p_abc") == workspace / "p_abc" / "chats"


def test_chat_meta_path(workspace: Path) -> None:
    from app.workspace.paths import chat_meta_path

    assert (
        chat_meta_path(workspace, "p_abc", "c_xyz")
        == workspace / "p_abc" / "chats" / "c_xyz.meta.json"
    )


def test_keys_path(workspace: Path) -> None:
    assert keys_path(workspace) == workspace / "_keys.json"


def test_job_locks_dir(workspace: Path) -> None:
    assert job_locks_dir(workspace) == workspace / "_job_locks"


def test_reviewed_dir(workspace: Path) -> None:
    assert reviewed_dir(workspace, "p_abc") == workspace / "p_abc" / "reviewed"


def test_reviewed_path(workspace: Path) -> None:
    assert reviewed_path(workspace, "p_abc", "d_xyz") == workspace / "p_abc" / "reviewed" / "d_xyz.json"


def test_metrics_dir(workspace: Path) -> None:
    from app.workspace.paths import metrics_dir

    assert metrics_dir(workspace, "p_abc") == workspace / "p_abc" / "metrics"


def test_metrics_path(workspace: Path) -> None:
    from app.workspace.paths import metrics_path

    assert (
        metrics_path(workspace, "p_abc", "eval_2026-05-09T00-00-00Z")
        == workspace / "p_abc" / "metrics" / "eval_2026-05-09T00-00-00Z.json"
    )


def test_jobs_dir(workspace: Path) -> None:
    from app.workspace.paths import jobs_dir
    assert jobs_dir(workspace, "p_abc") == workspace / "p_abc" / "jobs"


def test_job_log_path(workspace: Path) -> None:
    from app.workspace.paths import job_log_path
    assert (
        job_log_path(workspace, "p_abc", "j_xyz")
        == workspace / "p_abc" / "jobs" / "j_xyz.jsonl"
    )


def test_candidate_dir(workspace: Path) -> None:
    from app.workspace.paths import candidate_dir
    assert (
        candidate_dir(workspace, "p_abc", "j_xyz")
        == workspace / "p_abc" / "versions" / "_candidate" / "j_xyz"
    )


def test_candidate_turn_path(workspace: Path) -> None:
    from app.workspace.paths import candidate_turn_path
    assert (
        candidate_turn_path(workspace, "p_abc", "j_xyz", 3)
        == workspace / "p_abc" / "versions" / "_candidate" / "j_xyz" / "turn_3.json"
    )


def test_version_path_constructs_v1(tmp_path: Path) -> None:
    p = version_path(tmp_path, "p_abc123def456", 1)
    assert p == tmp_path / "p_abc123def456" / "versions" / "v1.json"


def test_parse_version_id_valid() -> None:
    assert parse_version_id("v1") == 1
    assert parse_version_id("v42") == 42


def test_parse_version_id_invalid_returns_none() -> None:
    assert parse_version_id("v") is None
    assert parse_version_id("1") is None
    assert parse_version_id("v0") is None
    assert parse_version_id("vfoo") is None
    assert parse_version_id("") is None


def test_next_version_n_no_versions_dir(tmp_path: Path) -> None:
    assert next_version_n(tmp_path, "p_abc123def456") == 1


def test_next_version_n_skips_candidate_and_unrelated(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    vd = versions_dir(tmp_path, pid)
    vd.mkdir(parents=True)
    (vd / "v1.json").write_text("{}")
    (vd / "v3.json").write_text("{}")
    (vd / "_candidate").mkdir()
    (vd / "notes.txt").write_text("ignored")
    assert next_version_n(tmp_path, pid) == 4


def test_prompts_dir(workspace: Path) -> None:
    from app.workspace.paths import prompts_dir
    assert prompts_dir(workspace, "p_abc") == workspace / "p_abc" / "prompts"


def test_prompt_path(workspace: Path) -> None:
    from app.workspace.paths import prompt_path
    assert prompt_path(workspace, "p_abc", "pr_baseline") == workspace / "p_abc" / "prompts" / "pr_baseline.json"


def test_models_dir(workspace: Path) -> None:
    from app.workspace.paths import models_dir
    assert models_dir(workspace, "p_abc") == workspace / "p_abc" / "models"


def test_model_path(workspace: Path) -> None:
    from app.workspace.paths import model_path
    assert model_path(workspace, "p_abc", "m_default") == workspace / "p_abc" / "models" / "m_default.json"
