from pathlib import Path
import re


_VERSION_RE = re.compile(r"^v(\d+)$")


def project_dir(workspace: Path, slug: str) -> Path:
    return workspace / slug


def project_json_path(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "project.json"


def schema_path(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "schema.json"


def docs_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "docs"


def docs_meta_dir(workspace: Path, slug: str) -> Path:
    """Sidecar root under `docs/.meta/`. Houses `<filename>.json` per doc plus
    the `_render/` PDF page cache. Kept as a dotfile dir so the `docs/*` glob
    (used by `list_docs` and the `/tree` browser) skips it naturally."""
    return docs_dir(workspace, slug) / ".meta"


def doc_path(workspace: Path, slug: str, filename: str) -> Path:
    """The real file on disk. `filename` is the user-visible doc handle (e.g.
    `2025VP00413.pdf`) — there is no `d_xxx` ID anymore. Callers must pass a
    `safe_filename`-validated value when the source is untrusted (HTTP path
    params)."""
    return docs_dir(workspace, slug) / filename


def doc_meta_path(workspace: Path, slug: str, filename: str) -> Path:
    """Sidecar JSON for one doc, at `docs/.meta/{filename}.json`. Holds
    `{sha256, page_count, uploaded_at, ext, original_name}`."""
    return docs_meta_dir(workspace, slug) / f"{filename}.json"


def doc_render_dir(workspace: Path, slug: str, filename: str) -> Path:
    """Per-doc PDF page render cache root: `docs/.meta/_render/{filename}/`."""
    return docs_meta_dir(workspace, slug) / "_render" / filename


def predictions_draft_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "predictions" / "_draft"


def prediction_draft_path(workspace: Path, slug: str, filename: str) -> Path:
    """Draft prediction JSON for one doc, keyed by filename."""
    return predictions_draft_dir(workspace, slug) / f"{filename}.json"


def versions_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "versions"


def prompts_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "prompts"


def prompt_path(workspace: Path, slug: str, prompt_id: str) -> Path:
    return prompts_dir(workspace, slug) / f"{prompt_id}.json"


def models_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "models"


def model_path(workspace: Path, slug: str, model_id: str) -> Path:
    return models_dir(workspace, slug) / f"{model_id}.json"


def experiments_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "experiments"


def experiment_dir(workspace: Path, slug: str, experiment_id: str) -> Path:
    return experiments_dir(workspace, slug) / experiment_id


def experiment_meta_path(workspace: Path, slug: str, experiment_id: str) -> Path:
    return experiment_dir(workspace, slug, experiment_id) / "meta.json"


def experiment_predictions_dir(workspace: Path, slug: str, experiment_id: str) -> Path:
    return experiment_dir(workspace, slug, experiment_id) / "predictions"


def experiment_prediction_path(
    workspace: Path, slug: str, experiment_id: str, filename: str,
) -> Path:
    """Per-doc experiment prediction JSON, keyed by filename (the doc handle)."""
    return experiment_predictions_dir(workspace, slug, experiment_id) / f"{filename}.json"


def chats_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "chats"


def chat_meta_path(workspace: Path, slug: str, chat_id: str) -> Path:
    return chats_dir(workspace, slug) / f"{chat_id}.meta.json"


def chat_attachments_dir(workspace: Path, slug: str, chat_id: str) -> Path:
    """Conversation-scoped attachment dir. Files dropped/pasted in chat land
    here, NOT in `docs/` — `docs/` is the curated sample set that drives
    AutoResearch eval, predictions, and review-mode click-to-page. Promotion
    to `docs/` is a separate, explicit user-confirmed step via the
    `promote_attachment_to_docs` tool."""
    return chats_dir(workspace, slug) / chat_id / "attachments"


def chat_attachment_path(
    workspace: Path, slug: str, chat_id: str, filename: str,
) -> Path:
    return chat_attachments_dir(workspace, slug, chat_id) / filename


def dedupe_filename(parent: Path, name: str) -> str:
    """If `name` already exists under `parent`, return `<stem> (1).<ext>` (or
    `(2)`, `(3)`, …) instead. Extension-aware split — the suffix after the
    final dot stays glued to the new copy."""
    target = parent / name
    if not target.exists():
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    i = 1
    while True:
        candidate = f"{stem} ({i})" + (f".{ext}" if ext else "")
        if not (parent / candidate).exists():
            return candidate
        i += 1


def keys_path(workspace: Path) -> Path:
    return workspace / "_keys.json"


def published_dir(workspace: Path) -> Path:
    """Workspace-level registry of frozen published artifacts. Each file in
    here is an immutable `{published_id}.json` minted by `freeze_version` and
    served by the public `POST /v1/extract` endpoint. Lives alongside
    `_keys.json` at the workspace root so it survives project rename/delete —
    that decoupling is the whole point of `published_id` vs `project_id`."""
    return workspace / "_published"


def published_path(workspace: Path, published_id: str) -> Path:
    return published_dir(workspace) / f"{published_id}.json"


def job_locks_dir(workspace: Path) -> Path:
    return workspace / "_job_locks"


def reviewed_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "reviewed"


def reviewed_path(workspace: Path, slug: str, filename: str) -> Path:
    """Reviewed (ground-truth) JSON for one doc, keyed by filename."""
    return reviewed_dir(workspace, slug) / f"{filename}.json"


def metrics_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "metrics"


def metrics_path(workspace: Path, slug: str, name: str) -> Path:
    return metrics_dir(workspace, slug) / f"{name}.json"


def jobs_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "jobs"


def job_log_path(workspace: Path, slug: str, job_id: str) -> Path:
    return jobs_dir(workspace, slug) / f"{job_id}.jsonl"


def candidate_dir(workspace: Path, slug: str, job_id: str) -> Path:
    return versions_dir(workspace, slug) / "_candidate" / job_id


def candidate_turn_path(workspace: Path, slug: str, job_id: str, turn: int) -> Path:
    return candidate_dir(workspace, slug, job_id) / f"turn_{turn}.json"


def version_path(workspace: Path, slug: str, n: int) -> Path:
    return versions_dir(workspace, slug) / f"v{n}.json"


def parse_version_id(s: str) -> int | None:
    """Return integer n for a version_id like 'v3', or None if malformed."""
    m = _VERSION_RE.match(s or "")
    if not m:
        return None
    n = int(m.group(1))
    return n if n >= 1 else None


def next_version_n(workspace: Path, slug: str) -> int:
    """Return max published version number + 1, ignoring candidates and junk."""
    vd = versions_dir(workspace, slug)
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
