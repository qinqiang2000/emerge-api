from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Repo root: backend/app/config.py → backend/app → backend → emerge.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _default_ingest_roots() -> tuple[Path, ...]:
    """Built-in allowlist for `ingest_local_path` / `POST /lab/.../ingest-local`.

    The set covers the dump zones an emerge user will reach for on a lab
    machine: `/tmp` (one-off scratch), `~/Downloads` / `~/Desktop` /
    `~/Documents` (where users park batches of receipts), and the repo root
    itself (so fixture folders inside this project can be ingested without
    extra config). Custom roots are appended via `EMERGE_INGEST_LOCAL_EXTRA_ROOTS`
    — a colon-separated list of absolute paths — but never replace these.
    """
    home = Path.home()
    return (
        Path("/tmp"),
        home / "Downloads",
        home / "Desktop",
        home / "Documents",
        _REPO_ROOT,
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMERGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    workspace_root: Path = Path("./workspace")
    default_extract_model: str = "gemini-2.5-flash"
    default_agent_model: str = "claude-sonnet-4-6"
    # Pro-labeler model. None = label_docs refuses with `labeler_model_not_configured`
    # unless the caller passes an explicit override or sets `project.json.labeler_model`.
    default_labeler_model: str | None = None
    # Translator model — drives the review-mode `translate_page` path (text-only
    # for electronic PDFs, vision for scanned). Independent of extract / labeler
    # / proposer; bbox + spans are review-UX only and never feed the extract
    # prompt (hard rule). Per-project override lives at
    # `project.json.translate_model`; this env value is the fallback. Defaults
    # to `gemini-flash-lite-latest` because translate is high-volume / cheap.
    default_translate_model: str = "gemini-flash-lite-latest"
    log_level: str = "INFO"

    # Colon-separated absolute paths appended to the built-in ingest allowlist.
    # Empty by default; set in deploy env to whitelist e.g. a shared scan drop.
    ingest_local_extra_roots: str = ""

    llm_judge_model: str = "gemini-flash-lite-latest"
    llm_judge_budget_per_eval: int = 200

    def ingest_allowlist(self) -> tuple[Path, ...]:
        """Resolve the combined ingest-local allowlist (defaults + env extras).

        Each entry is `.resolve()`d once so the path-prefix check in
        `ingest_local_path` works against canonical absolute paths (and so
        symlinks pointing outside the allowlist are caught). Non-existent
        defaults are kept — `~/Documents` may not exist on a CI box, but we
        still want the symbolic intent recorded; the per-call existence check
        will produce the right error message.
        """
        defaults = list(_default_ingest_roots())
        extras: list[Path] = []
        if self.ingest_local_extra_roots:
            for raw in self.ingest_local_extra_roots.split(":"):
                token = raw.strip()
                if not token:
                    continue
                extras.append(Path(token).expanduser())
        merged: list[Path] = []
        seen: set[str] = set()
        for p in defaults + extras:
            try:
                resolved = p.expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            merged.append(resolved)
        return tuple(merged)


def get_settings() -> Settings:
    return Settings()
