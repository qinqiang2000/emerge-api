from pathlib import Path


def project_dir(workspace: Path, project_id: str) -> Path:
    return workspace / project_id


def project_json_path(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "project.json"


def schema_path(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "schema.json"


def docs_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "docs"


def doc_path(workspace: Path, project_id: str, doc_id: str, ext: str) -> Path:
    return docs_dir(workspace, project_id) / f"{doc_id}.{ext}"


def doc_meta_path(workspace: Path, project_id: str, doc_id: str) -> Path:
    return docs_dir(workspace, project_id) / f"{doc_id}.meta.json"


def predictions_draft_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "predictions" / "_draft"


def versions_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "versions"


def chats_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "chats"


def keys_path(workspace: Path) -> Path:
    return workspace / "_keys.json"


def job_locks_dir(workspace: Path) -> Path:
    return workspace / "_job_locks"


def reviewed_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "reviewed"


def reviewed_path(workspace: Path, project_id: str, doc_id: str) -> Path:
    return reviewed_dir(workspace, project_id) / f"{doc_id}.json"


def metrics_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "metrics"


def metrics_path(workspace: Path, project_id: str, name: str) -> Path:
    return metrics_dir(workspace, project_id) / f"{name}.json"


def jobs_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "jobs"


def job_log_path(workspace: Path, project_id: str, job_id: str) -> Path:
    return jobs_dir(workspace, project_id) / f"{job_id}.jsonl"


def candidate_dir(workspace: Path, project_id: str, job_id: str) -> Path:
    return versions_dir(workspace, project_id) / "_candidate" / job_id


def candidate_turn_path(workspace: Path, project_id: str, job_id: str, turn: int) -> Path:
    return candidate_dir(workspace, project_id, job_id) / f"turn_{turn}.json"
