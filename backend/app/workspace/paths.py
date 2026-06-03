from pathlib import Path
import hashlib
import json
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


def content_cache_root(workspace: Path) -> Path:
    """Workspace-level, content-addressed cache root: `{workspace}/.cache/`.

    Holds the three *content-derived* sidecar families — `_render` (PNG
    raster), `_textlayer` (fitz/OCR spans), `_translate` (per-page
    translations). Each is a pure function of the doc bytes (+ page, and for
    translate +lang/mode/model) and is **project-agnostic**: the same PDF
    copied / forked / re-uploaded into any project shares the same entries,
    so the work is paid once. Dotfile dir → skipped by every workspace
    scanner (`pid_index._scan`, `orphans.cleanup`, `fork`)."""
    return workspace / ".cache"


def doc_content_sha(workspace: Path, slug: str, filename: str) -> str:
    """Resolve the content-cache key for a doc: its sha256.

    Reads the sha from the doc's meta sidecar (written at upload/ingest).
    Falls back to hashing the on-disk bytes only if the sidecar is missing
    the field (predates `sha256`) — keeps the cache correct for old docs
    without a migration. Raises if the doc itself is gone."""
    meta_p = doc_meta_path(workspace, slug, filename)
    try:
        sha = json.loads(meta_p.read_text()).get("sha256")
        if sha:
            return str(sha)
    except (OSError, json.JSONDecodeError):
        pass
    return hashlib.sha256(
        doc_path(workspace, slug, filename).read_bytes()
    ).hexdigest()


def doc_render_dir(workspace: Path, slug: str, filename: str) -> Path:
    """Content-addressed PDF page render cache root: `.cache/_render/{sha}/`.

    Keyed by doc content (sha256), not by project/filename — see
    `content_cache_root`. Same bytes across projects → one shared render."""
    sha = doc_content_sha(workspace, slug, filename)
    return content_cache_root(workspace) / "_render" / sha


def doc_textlayer_dir(workspace: Path, slug: str, filename: str) -> Path:
    """Content-addressed text-layer sidecar root: `.cache/_textlayer/{sha}/`.

    Sibling to `doc_render_dir`. Each PDF page lands a `p{n}.json` sidecar
    holding fitz spans + bbox + scanned flag — see
    `app/tools/textlayer.py:extract_textlayer`. Lets review-mode show the
    raster bitmap (for evidence) while still letting the user select / copy
    the underlying text (PDF.js-style transparent overlay). Keyed by content
    (sha256) so a doc copied between projects reuses the OCR/span work."""
    sha = doc_content_sha(workspace, slug, filename)
    return content_cache_root(workspace) / "_textlayer" / sha


def doc_textlayer_path(
    workspace: Path, slug: str, filename: str, page: int,
) -> Path:
    """Per-page text-layer sidecar JSON path."""
    return doc_textlayer_dir(workspace, slug, filename) / f"p{page}.json"


def _safe_model_segment(model_id: str) -> str:
    """Filename-safe rendering of a `model_id` for use as a path segment.

    Gemini publishes both bare names (`gemini-flash-lite-latest`) and
    qualified resource paths (`models/gemini-foo`). The latter would smuggle
    a `/` separator into the cache filename — so we collapse `/` and `:`
    (which Anthropic uses in some snapshot tags like `claude-3-5:beta`) to
    underscores. Stable across renames because the model_id itself is the
    cache key; switching model_id → cache miss → fresh translate."""
    return model_id.replace("/", "_").replace(":", "_")


def doc_translate_dir(workspace: Path, slug: str, filename: str) -> Path:
    """Content-addressed translation sidecar root: `.cache/_translate/{sha}/`.

    Sibling to `doc_textlayer_dir` and `doc_render_dir`. Each translated page
    lands a per-(page, target_lang, mode, model_id) JSON sidecar — see
    `app/tools/translate.py:translate_page`. Cache keys include `mode` (the
    branch the translator took — text-only vs vision) and `model_safe` (the
    sanitised model_id) so switching model or branch never returns a stale
    payload. Keyed by content (sha256), so the same PDF in any project shares
    one translation — translation is a pure function of bytes + lang + model,
    independent of the project's schema."""
    sha = doc_content_sha(workspace, slug, filename)
    return content_cache_root(workspace) / "_translate" / sha


def doc_translate_path(
    workspace: Path,
    slug: str,
    filename: str,
    *,
    page: int,
    target_lang: str,
    mode: str,
    model_id: str,
) -> Path:
    """Per-page translation sidecar JSON path. Key shape:
    `p{n}_{target_lang}_{mode}_{model_safe}.json`."""
    safe = _safe_model_segment(model_id)
    return (
        doc_translate_dir(workspace, slug, filename)
        / f"p{page}_{target_lang}_{mode}_{safe}.json"
    )


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


def prompt_versions_dir(workspace: Path, slug: str, prompt_id: str) -> Path:
    """Append-only snapshot history for one prompt. Lives under `prompts/` as a
    DIR (not a `.json` file) so `list_prompts`' file-only scan skips it."""
    return prompts_dir(workspace, slug) / "_versions" / prompt_id


def prompt_version_path(workspace: Path, slug: str, prompt_id: str, version: int) -> Path:
    return prompt_versions_dir(workspace, slug, prompt_id) / f"v{version}.json"


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


# ── Unbound-chat paths ────────────────────────────────────────────────────
# A chat that hasn't been promoted to a project yet lives under
# `workspace/_chats/` — parallel to `_staging/`. The leading underscore keeps
# it invisible to `list_projects` (projects.py filters underscore-prefixed
# children) so unbound chats never pollute the sidebar.
#
# Same per-chat layout as a project chat, just rooted under `_chats/` instead
# of `<slug>/chats/`:
#   _chats/<chat_id>.jsonl              ← event log
#   _chats/<chat_id>.meta.json          ← sidecar (label / kind / sdk_session_id)
#   _chats/<chat_id>/attachments/<f>    ← per-chat attachments
#
# Promotion (`promote_chat_to_project`) atomically `os.rename`s these three
# entries under `<new_slug>/chats/` inside the new project's lock.


def unbound_chats_root(workspace: Path) -> Path:
    """Workspace-level root for all unbound chats. Parallel to `_staging/`;
    naturally excluded from `list_projects` by the underscore filter."""
    return workspace / "_chats"


def unbound_chat_log_path(workspace: Path, chat_id: str) -> Path:
    """`_chats/<chat_id>.jsonl` — the event log for one unbound chat."""
    return unbound_chats_root(workspace) / f"{chat_id}.jsonl"


def unbound_chat_meta_path(workspace: Path, chat_id: str) -> Path:
    """`_chats/<chat_id>.meta.json` — sidecar holding {label, kind, created_at,
    sdk_session_id} for one unbound chat. Parallels `chat_meta_path` for
    project chats."""
    return unbound_chats_root(workspace) / f"{chat_id}.meta.json"


def unbound_chat_attachments_dir(workspace: Path, chat_id: str) -> Path:
    """`_chats/<chat_id>/attachments/` — paste/drop attachments for one
    unbound chat. Parallels `chat_attachments_dir` for project chats."""
    return unbound_chats_root(workspace) / chat_id / "attachments"


def unbound_chat_attachment_path(
    workspace: Path, chat_id: str, filename: str,
) -> Path:
    return unbound_chat_attachments_dir(workspace, chat_id) / filename


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


# --- multi-tenancy (Users & Teams, 2026-06-03) ------------------------------
# `_auth/` is GLOBAL (cross-team): callers MUST pass the TRUE workspace root
# (`settings.workspace_root`), never a per-team workspace. Projects live under
# `workspace_root/teams/{team_id}/{slug}/`; auth data sits beside `teams/` so it
# is shared by every tenant. Leading-underscore dir → skipped by project
# scanners (`pid_index`, `orphans`, `fork`) for free.
def auth_dir(workspace_root: Path) -> Path:
    return workspace_root / "_auth"


def users_path(workspace_root: Path) -> Path:
    return auth_dir(workspace_root) / "users.json"


def teams_path(workspace_root: Path) -> Path:
    return auth_dir(workspace_root) / "teams.json"


def pats_path(workspace_root: Path) -> Path:
    """Personal Access Tokens (headless `Authorization: Bearer`). Separate from
    `_keys.json` (the prod `/v1/extract` customer keys) — different blast
    radius: a PAT drives the whole `/lab/*` authoring surface as its user."""
    return auth_dir(workspace_root) / "pats.json"


def teams_root(workspace_root: Path) -> Path:
    """`workspace_root/teams/` — the parent of every per-team workspace."""
    return workspace_root / "teams"


def team_workspace_dir(workspace_root: Path, team_id: str) -> Path:
    """The per-team workspace that becomes the effective `workspace` handed to
    every existing path helper / tool. `team_workspace_dir(root, tid) / slug`
    is a project dir, structurally identical to the pre-tenancy layout."""
    return teams_root(workspace_root) / team_id


def reviewed_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "reviewed"


def reviewed_path(workspace: Path, slug: str, filename: str) -> Path:
    """Reviewed (ground-truth) JSON for one doc, keyed by filename."""
    return reviewed_dir(workspace, slug) / f"{filename}.json"


def pending_reviewed_dir(workspace: Path, slug: str) -> Path:
    """Pro-labeler draft drop zone. Glob-invisible to `reviewed/*.json` —
    `score()` / `/improve` / `/publish` / `readiness_check` never see these
    files. Promotion to `reviewed/` happens in `save_reviewed` after the
    boss saves their corrections (it atomically deletes the matching
    pending file in the same `project_lock`)."""
    return reviewed_dir(workspace, slug) / "_pending"


def pending_reviewed_path(workspace: Path, slug: str, filename: str) -> Path:
    return pending_reviewed_dir(workspace, slug) / f"{filename}.json"


def metrics_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / "metrics"


def metrics_path(workspace: Path, slug: str, name: str) -> Path:
    return metrics_dir(workspace, slug) / f"{name}.json"


def eval_dir(workspace: Path, slug: str, ts: str) -> Path:
    return metrics_dir(workspace, slug) / f"eval_{ts}"


def eval_summary_path(workspace: Path, slug: str, ts: str) -> Path:
    return eval_dir(workspace, slug, ts) / "summary.json"


def eval_cells_path(workspace: Path, slug: str, ts: str) -> Path:
    return eval_dir(workspace, slug, ts) / "cells.jsonl"


def eval_matrix_path(workspace: Path, slug: str, ts: str) -> Path:
    return eval_dir(workspace, slug, ts) / "matrix.csv"


def eval_meta_path(workspace: Path, slug: str, ts: str) -> Path:
    return eval_dir(workspace, slug, ts) / "meta.json"


def eval_judge_cache_dir(workspace: Path, slug: str) -> Path:
    return project_dir(workspace, slug) / ".eval_judge_cache"


def eval_judge_cache_path(workspace: Path, slug: str, sha256_hex: str) -> Path:
    return eval_judge_cache_dir(workspace, slug) / f"{sha256_hex}.json"


def eval_extract_cache_dir(
    workspace: Path, slug: str, schema_hash: str, model_id: str,
) -> Path:
    """Baseline-cache root for the autoresearch / tune inner-loop eval pass:
    `projects/{slug}/.eval_cache/{schema_hash}/{model_safe}/`.

    Content-addressed by (schema_hash, extract_model_id) on the dir, then by
    doc_content_sha on the leaf file — see `eval_extract_cache_path`. Unlike
    the `.cache/` render/textlayer/translate families this is **project-scoped**
    (the schema is a project's lab-editing artifact, not a pure function of doc
    bytes) and lives under the project dir as a dotfile so `docs/*` / version
    scanners skip it. Never copied into `versions/` or prod (red line: lab-side
    only). `model_id` is collapsed through `_safe_model_segment` so a Gemini
    `models/...` resource path can't smuggle a separator into the path."""
    return (
        project_dir(workspace, slug)
        / ".eval_cache"
        / schema_hash
        / _safe_model_segment(model_id)
    )


def eval_extract_cache_path(
    workspace: Path, slug: str, schema_hash: str, model_id: str, doc_sha: str,
) -> Path:
    """Per-doc baseline-cache leaf: `.../{doc_sha}.json`. Holds only the
    predictions `entities` list for that doc under the given schema+model —
    no bbox / coordinates / document body (red line)."""
    return eval_extract_cache_dir(
        workspace, slug, schema_hash, model_id,
    ) / f"{doc_sha}.json"


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
