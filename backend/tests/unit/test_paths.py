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
    assert doc_path(workspace, "p_abc", "d_xyz", "pdf") == workspace / "p_abc" / "docs" / "d_xyz.pdf"


def test_doc_meta_path(workspace: Path) -> None:
    assert doc_meta_path(workspace, "p_abc", "d_xyz") == workspace / "p_abc" / "docs" / "d_xyz.meta.json"


def test_predictions_draft_dir(workspace: Path) -> None:
    assert predictions_draft_dir(workspace, "p_abc") == workspace / "p_abc" / "predictions" / "_draft"


def test_versions_dir(workspace: Path) -> None:
    assert versions_dir(workspace, "p_abc") == workspace / "p_abc" / "versions"


def test_chats_dir(workspace: Path) -> None:
    assert chats_dir(workspace, "p_abc") == workspace / "p_abc" / "chats"


def test_keys_path(workspace: Path) -> None:
    assert keys_path(workspace) == workspace / "_keys.json"


def test_job_locks_dir(workspace: Path) -> None:
    assert job_locks_dir(workspace) == workspace / "_job_locks"


def test_reviewed_dir(workspace: Path) -> None:
    assert reviewed_dir(workspace, "p_abc") == workspace / "p_abc" / "reviewed"


def test_reviewed_path(workspace: Path) -> None:
    assert reviewed_path(workspace, "p_abc", "d_xyz") == workspace / "p_abc" / "reviewed" / "d_xyz.json"
