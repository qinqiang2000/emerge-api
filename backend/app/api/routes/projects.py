import json
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.routes._safety import safe_slug
from app.config import get_settings
from app.tools.docs import list_docs
from app.tools.projects import list_projects
from app.tools.reviewed import list_reviewed
from app.workspace.paths import predictions_draft_dir, project_dir, project_json_path


router = APIRouter()


# Names hidden at every level of the project tree (the `@` mention browser).
# This is the allow-list inverse: anything *not* listed shows up. Kept
# deliberately narrow — agent and user share the same view of "useful
# artifacts", with internal-only state (chats / jobs / metrics / api keys)
# filtered out. Dotfiles (`.meta`, `.git`, anything starting with `.`) are
# filtered separately by the leading-dot rule.
_TREE_HIDDEN_NAMES = frozenset({
    "chats",
    "prompts",
    "models",
    "predictions",
    "jobs",
    "metrics",
    "experiments",
    "project.json",
})

# Inside `versions/`, expose published `v{N}.json` only — `_candidate/` is
# transient autoresearch candidate state and never user-actionable.
_VERSIONS_HIDDEN_NAMES = frozenset({"_candidate"})


@router.get("/lab/projects")
async def get_projects() -> list[dict]:
    settings = get_settings()
    return await list_projects(settings.workspace_root)


class _ForkProjectBody(BaseModel):
    # Field names kept for back-compat; values now carry slugs (the human-
    # readable folder handle). `src_pid` -> src_slug semantically.
    src_pid: str
    name: str
    include_docs: bool = False


@router.post("/lab/projects/fork")
async def post_fork_project(body: _ForkProjectBody) -> dict:
    safe_slug(body.src_pid)
    settings = get_settings()
    from app.tools.fork import ForkSourceNotFoundError, fork_project

    try:
        out = await fork_project(
            settings.workspace_root,
            src_slug=body.src_pid,
            name=body.name,
            include_docs=body.include_docs,
        )
    except ForkSourceNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    # Surface both shapes so existing FE wiring (project_id key) keeps working
    # while agent-4 migrates to `slug`. The pid is also included for audit.
    return {
        "project_id": out["slug"],
        "slug": out["slug"],
        "pid": out["project_id"],
    }


@router.get("/lab/projects/{slug}")
async def get_project(slug: str) -> dict:
    safe_slug(slug)
    settings = get_settings()
    from app.workspace.migrate import migrate_project_if_needed

    pj = project_json_path(settings.workspace_root, slug)
    if not pj.exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    await migrate_project_if_needed(settings.workspace_root, slug)
    blob = json.loads(pj.read_text())
    # `project_id` field in response is the slug (back-compat key); the
    # actual pid lives inside `blob["project_id"]`.
    return {"project_id": slug, **blob, "slug": slug}


@router.get("/lab/projects/{slug}/docs")
async def get_project_docs(slug: str) -> list[dict]:
    """List the project's docs with quick has-reviewed / has-prediction flags.

    Each item carries `filename` (the doc handle), `ext`, `page_count`,
    `sha256`, `uploaded_at`, and `original_name`. No `doc_id` — filename is
    the only handle now."""
    safe_slug(slug)
    settings = get_settings()
    docs = await list_docs(settings.workspace_root, slug)
    reviewed_names = {
        r["filename"] for r in await list_reviewed(settings.workspace_root, slug)
    }
    pdir = predictions_draft_dir(settings.workspace_root, slug)
    # prediction filenames live at `predictions/_draft/<filename>.json`; strip
    # only the trailing `.json` to recover the doc handle (which itself
    # already includes the doc's extension).
    pred_names: set[str] = set()
    if pdir.exists():
        for p in pdir.glob("*.json"):
            pred_names.add(p.name[:-len(".json")])
    out = []
    for d in docs:
        fn = d["filename"]
        out.append({
            **d,
            "has_reviewed": fn in reviewed_names,
            "has_prediction": fn in pred_names,
        })
    return out


def _validate_tree_dir(rel: str) -> PurePosixPath:
    """Validate a project-relative `dir` argument for `/tree`.

    Returns the validated POSIX path (empty for project root). Raises
    HTTPException(400) for absolute paths, leading slash, traversal segments,
    or any non-string input. Resolved-outside checks are done at the caller
    level once the project root is known."""
    if not isinstance(rel, str):
        raise HTTPException(status_code=400, detail="invalid dir")
    if rel == "":
        return PurePosixPath()
    if rel.startswith("/") or rel.startswith("\\"):
        raise HTTPException(status_code=400, detail="invalid dir")
    # Reject any traversal segment up front; PurePosixPath happily normalises
    # `a/../b` to `b`, but for our security model we want it firmly out.
    parts = rel.split("/")
    for seg in parts:
        if seg in ("", ".", ".."):
            raise HTTPException(status_code=400, detail="invalid dir")
    return PurePosixPath(rel)


def _is_tree_visible(name: str, parent_rel: PurePosixPath) -> bool:
    """Allow-list filter for the `@` mention browser. Hides dotfiles, the
    internal-only top-level directories, and `versions/_candidate/`."""
    if name.startswith("."):
        return False
    if parent_rel == PurePosixPath() and name in _TREE_HIDDEN_NAMES:
        return False
    if parent_rel == PurePosixPath("versions") and name in _VERSIONS_HIDDEN_NAMES:
        return False
    return True


@router.get("/lab/projects/{slug}/tree")
async def get_project_tree(slug: str, dir: str = "") -> list[dict]:
    """Browse the project workspace as a filtered tree. Powers the composer
    `@` mention picker.

    - `dir`: project-relative POSIX path; `""` is the project root.
    - Returns `[{name, kind: "file"|"dir", path}]`, dirs first then files,
      both case-insensitive alphabetical.
    - Filters out internal-only artifacts (chats, prompts, models,
      predictions, jobs, metrics, experiments, project.json, dotfiles,
      versions/_candidate).
    - 400 on traversal / absolute / non-relative `dir`; 404 if the dir
      doesn't exist.
    """
    safe_slug(slug)
    rel = _validate_tree_dir(dir)
    settings = get_settings()
    root = project_dir(settings.workspace_root, slug).resolve()
    if not root.exists():
        raise HTTPException(status_code=404, detail="project_not_found")

    target = (root / Path(*rel.parts)).resolve() if rel.parts else root
    # Defense in depth: even with the segment-level checks above, ensure the
    # final resolved path is still inside the project root (handles symlinks).
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid dir")

    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="dir_not_found")

    dirs: list[dict] = []
    files: list[dict] = []
    for child in target.iterdir():
        name = child.name
        if not _is_tree_visible(name, rel):
            continue
        child_rel = (rel / name).as_posix() if rel.parts else name
        if child.is_dir():
            dirs.append({"name": name, "kind": "dir", "path": child_rel})
        elif child.is_file():
            files.append({"name": name, "kind": "file", "path": child_rel})
        # Symlinks pointing at non-existent / non-dir-non-file: silently skip.

    dirs.sort(key=lambda x: x["name"].lower())
    files.sort(key=lambda x: x["name"].lower())
    return dirs + files


@router.get("/lab/projects/{slug}/schema")
async def get_project_schema(slug: str) -> list[dict]:
    safe_slug(slug)
    settings = get_settings()
    from app.tools.schema import read_schema
    from app.workspace.migrate import migrate_project_if_needed

    pj = project_json_path(settings.workspace_root, slug)
    if not pj.exists():
        raise HTTPException(status_code=404, detail="schema_not_found")
    await migrate_project_if_needed(settings.workspace_root, slug)
    fields = await read_schema(settings.workspace_root, slug)
    return [f.model_dump(mode="json") for f in fields]
