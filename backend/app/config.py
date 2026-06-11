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
    # Headless (stdio/remote) MCP tool surface. "minimal" (default) exposes the
    # ws_* filesystem bus + invariant/LLM verbs (~28 tools); "full" exposes every
    # headless tool (~58). Experiment (2026-06-10): a Cowork user runs 10+
    # connectors, so context pressure is real — minimal bets that generic file
    # verbs cover the long tail. Flip to "full" to revert, no redeploy of data.
    mcp_surface: str = "minimal"
    # MCP Apps (ui:// HTML in chat) — B5a hello-world gate, default OFF. When
    # on, read_audit_report's tools/list entry carries _meta.ui.resourceUri and
    # the hello app resource is served. Flip ON only to dogfood Claude Desktop
    # rendering (plans/2026-06-11-audit-board.md §B5a); B5b board app waits on
    # that gate.
    mcp_apps: bool = False
    # Bootstrap seed for `models/m_default.json` when `create_project` runs.
    # Read EXACTLY ONCE per project — the value gets baked into the freshly
    # minted `m_default` ModelConfig (`provider_model_id`) plus stamped on
    # legacy migrate (`_migrate_to_m91` when an old project.json carries no
    # `extract_model` field). Updating this env var afterwards has NO effect
    # on existing projects: their runtime extract LLM resolves through
    # `project.json.active_model_id → models/{mid}.json` (see
    # `tools/extract.py`'s `read_active_model`), which never re-reads this
    # setting. To change the model an existing project uses, edit
    # `models/{mid}.json` or run `switch_active_model` / `/compare`.
    default_extract_model: str = "gemini-2.5-flash"
    default_agent_model: str = "claude-sonnet-4-6"
    # Pro-labeler model. None = label_docs refuses with `labeler_model_not_configured`
    # unless the caller passes an explicit override or sets `project.json.labeler_model`.
    default_labeler_model: str | None = None
    # Proposer model for autoresearch. Real runtime fallback (unlike
    # `default_extract_model` which is bootstrap-only seed): resolved at
    # `JobRunner` start per-project as
    #   per-job override → project.json.autoresearch_proposer_model →
    #   project.json.active_model_id → THIS env → ProposerNotConfiguredError
    # so an in-flight env edit takes effect on the next `/improve` job.
    # Default None means "fall back to the project's active extract model"
    # which matches the pre-fix behaviour of routing autoresearch through
    # whatever model the project itself uses.
    default_proposer_model: str | None = None
    # Translator model — drives the review-mode `translate_page` path (text-only
    # for electronic PDFs, vision for scanned). Independent of extract / labeler
    # / proposer; bbox + spans are review-UX only and never feed the extract
    # prompt (hard rule). Per-project override lives at
    # `project.json.translate_model`; this env value is the fallback. Defaults
    # to `gemini-flash-lite-latest` because translate is high-volume / cheap.
    default_translate_model: str = "gemini-flash-lite-latest"
    # OCR model for the review text-layer (scanned-page span recovery in
    # `textlayer._ocr_extract_spans`). DECOUPLED from translate on purpose: OCR
    # needs document-recognition strength, and flash-lite emits truncated /
    # malformed JSON on dense scanned pages → 0 spans → "完全没定位" (see INSIGHTS
    # "locate needs a TEXT LAYER"). Pinned to `gemini-2.5-flash`: gemini-flash-latest
    # rolled forward to 3.5-flash (pricier + doc-recognition regression), and
    # flash-lite is too weak — so neither is used for OCR. The call runs with
    # `thinking_budget=0` (transcription needs no reasoning; see textlayer.py).
    # The offline backfill (warm_textlayer.py) runs this same model on GCP/Vertex;
    # live prod runs it on AI Studio. Override per-deploy with `EMERGE_DEFAULT_OCR_MODEL`.
    default_ocr_model: str = "gemini-2.5-flash"
    log_level: str = "INFO"

    # Colon-separated absolute paths appended to the built-in ingest allowlist.
    # Empty by default; set in deploy env to whitelist e.g. a shared scan drop.
    ingest_local_extra_roots: str = ""

    llm_judge_model: str = "gemini-flash-lite-latest"
    llm_judge_budget_per_eval: int = 200

    # --- Users & Teams (2026-06-03) ----------------------------------------
    # Signed-cookie session secret. Dev default is intentionally insecure —
    # set EMERGE_SECRET_KEY in any real deploy. (Efficiency/UX over security,
    # see MEMORY:priorities-efficiency-experience-over-security — but a shared
    # process-wide signing key still must not be the literal default in prod.)
    secret_key: str = "dev-insecure-change-me"
    # Persistent login: 90-day rolling cookie so closing the browser never
    # forces a re-login (hard UX requirement). Only explicit logout ends it.
    session_max_age: int = 90 * 24 * 60 * 60
    # Name of the team that existing pre-tenancy projects migrate into.
    bootstrap_team_name: str = "Default Team"
    # Public origin this server is reachable at (e.g. https://abc.ngrok.app or
    # the prod domain). REQUIRED to enable the OAuth 2.0 custom-connector flow
    # (P2): it is the OAuth `issuer` advertised in `.well-known` metadata and
    # the base of the consent-redirect URL, so it must be the exact HTTPS origin
    # the Claude client sees. Empty → OAuth AS is not mounted and teammates
    # onboard via the P1 `?token=` PAT URL instead. No trailing slash needed.
    public_base_url: str = ""
    # First-boot superuser seed (optional). When both are set and no superuser
    # exists yet, `create_superuser` bootstrap mints one. Never logged.
    superuser_email: str | None = None
    superuser_password: str | None = None

    # Max in-flight per-doc extract calls during one autoresearch eval pass
    # (`score_with_schema` fans out across all reviewed docs). Lab tool, no
    # token budget — this only bounds provider-side rate limits / connection
    # pressure, not cost. 1 == the old strictly-sequential behaviour.
    eval_extract_concurrency: int = 8

    # Baseline cache for the autoresearch / tune inner-loop eval pass. When on,
    # `score_with_schema` content-addresses each per-doc extract by
    # (schema_hash, extract_model_id, doc_content_sha) and skips the LLM call on
    # a hit — so re-running a turn whose schema+model+docs are unchanged costs
    # zero provider round-trips. Pure lab-side artifact under
    # `projects/{slug}/.eval_cache/`; never written into `versions/` or prod.
    # Off == always re-extract (the pre-cache behaviour).
    eval_cache: bool = True

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
