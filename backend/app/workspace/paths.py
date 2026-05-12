from pathlib import Path
import re


_VERSION_RE = re.compile(r"^v(\d+)$")


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


def prompts_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "prompts"


def prompt_path(workspace: Path, project_id: str, prompt_id: str) -> Path:
    return prompts_dir(workspace, project_id) / f"{prompt_id}.json"


def models_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "models"


def model_path(workspace: Path, project_id: str, model_id: str) -> Path:
    return models_dir(workspace, project_id) / f"{model_id}.json"


def experiments_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "experiments"


def experiment_dir(workspace: Path, project_id: str, experiment_id: str) -> Path:
    return experiments_dir(workspace, project_id) / experiment_id


def experiment_meta_path(workspace: Path, project_id: str, experiment_id: str) -> Path:
    return experiment_dir(workspace, project_id, experiment_id) / "meta.json"


def experiment_extracts_dir(workspace: Path, project_id: str, experiment_id: str) -> Path:
    return experiment_dir(workspace, project_id, experiment_id) / "extracts"


def experiment_extract_path(
    workspace: Path, project_id: str, experiment_id: str, doc_id: str,
) -> Path:
    return experiment_extracts_dir(workspace, project_id, experiment_id) / f"{doc_id}.json"


def chats_dir(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "chats"


def chat_meta_path(workspace: Path, project_id: str, chat_id: str) -> Path:
    return chats_dir(workspace, project_id) / f"{chat_id}.meta.json"


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


def version_path(workspace: Path, project_id: str, n: int) -> Path:
    return versions_dir(workspace, project_id) / f"v{n}.json"


def parse_version_id(s: str) -> int | None:
    """Return integer n for a version_id like 'v3', or None if malformed."""
    m = _VERSION_RE.match(s or "")
    if not m:
        return None
    n = int(m.group(1))
    return n if n >= 1 else None


def next_version_n(workspace: Path, project_id: str) -> int:
    """Return max published version number + 1, ignoring candidates and junk."""
    vd = versions_dir(workspace, project_id)
    if not vd.exists():
        return 1
    seen: list[int] = []
    for child in vd.iterdir():
        if not child.is_file() or not child.name.endswith(".json"):
            continue
        n = parse_version_id(child.stem)
        if n is not None:
            seen.append(n)
    return max(seen) + 1 if seen else 1
