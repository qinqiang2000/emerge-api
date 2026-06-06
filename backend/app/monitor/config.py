"""Monitor configuration — resolved entirely from `.env` / process env.

Kept as a plain dataclass (not a pydantic `BaseSettings`) on purpose: the
monitor mixes two env namespaces — the `EMERGE_MONITOR_*` knobs *and* the raw
provider credentials (`GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, …, no prefix) that
the five-layer LLM stack already uses. A dataclass + explicit `from_env` reads
both without fighting pydantic's single-prefix model, and makes the standalone
CLI self-contained (it `load_dotenv`s the same `backend/.env` the API process
does, so monitoring works even when the web server is down).
"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dotenv import load_dotenv

# monitor/config.py → monitor → app → backend
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_ENV_PATH = _BACKEND_DIR / ".env"

# Cheapest model per provider that still exercises the real structured-output
# path users depend on. Overridable via env for deploys on a different catalog.
_DEFAULT_GOOGLE_PROBE_MODEL = "gemini-flash-lite-latest"
_DEFAULT_ANTHROPIC_PROBE_MODEL = "claude-haiku-4-5-20251001"


def ensure_env_loaded() -> None:
    """Load `backend/.env` into `os.environ` (idempotent, never overrides what's
    already exported). The agent brain (`claude_agent_sdk` → bundled CLI) realises
    its capability *only* from env — `ANTHROPIC_BASE_URL`, `CLAUDE_PROXY`,
    `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_API_KEY` — so any agent probe/test must
    guarantee these are present before spawning the SDK, never hardcode them, and
    never route around the configured gateway (MEMORY:feedback_anthropic_no_direct_api)."""
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=False)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def scrub_secrets(text: str, secrets: tuple[str, ...]) -> str:
    """Redact any known secret value occurring in `text` before it hits a log or
    an outbound alert. google-genai puts `?key=<API_KEY>` in the request URL, so
    a transport error can echo the key verbatim — this is the chokepoint that
    stops it leaking into 云之家 / logs (hard rule: never print secrets)."""
    out = text
    for s in secrets:
        if s and len(s) >= 6 and s in out:
            out = out.replace(s, "***")
    return out


@dataclass
class MonitorConfig:
    # --- alert channel (云之家 webhook) ---------------------------------------
    # Full webhook URL *including* yzjtoken. Empty → alerter disabled (the
    # monitor still probes and logs, it just can't notify).
    webhook_url: str = ""
    alert_proxy: str | None = None
    alert_timeout: float = 10.0

    # --- provider credentials (the thing that makes monitoring *possible*) ----
    google_api_key: str = ""
    google_proxy: str | None = None
    anthropic_api_key: str = ""
    anthropic_proxy: str | None = None
    # The Anthropic gateway. ALL Anthropic traffic routes through this — direct
    # api.anthropic.com is forbidden (MEMORY:feedback_anthropic_no_direct_api).
    # The anthropic provider probe sends to `{base_url}/v1/messages`; if unset,
    # `build_targets` skips the anthropic probe entirely (never falls back to the
    # direct URL). The agent-brain probe also relies on this via env.
    anthropic_base_url: str = ""

    # --- cadence / sensitivity ------------------------------------------------
    interval: float = 300.0          # seconds between sweeps
    probe_timeout: float = 20.0      # fast-fail; a hung provider is "down"
    fail_threshold: int = 2          # consecutive fails before alerting (anti-flap)
    realert_after: float = 3600.0    # re-remind if still down this long; 0 = once only

    # --- probe models ---------------------------------------------------------
    google_probe_model: str = _DEFAULT_GOOGLE_PROBE_MODEL
    anthropic_probe_model: str = _DEFAULT_ANTHROPIC_PROBE_MODEL

    # --- agent brain (claude_agent_sdk) — opt-in, it spawns the CLI -----------
    probe_agent: bool = False
    agent_min_interval: float = 1800.0  # coarser cadence so the CLI isn't hammered

    # --- selection / lifecycle ------------------------------------------------
    # Explicit allowlist override ("google,anthropic,agent"). Empty = auto from keys.
    targets_override: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = False            # auto-start inside the API process on boot
    host: str = ""                   # tag in alerts so multi-box deploys are distinguishable

    @classmethod
    def from_env(cls, *, load_env: bool = True) -> "MonitorConfig":
        """Build from `.env` + process env. `override=False` so anything already
        exported (tests, systemd EnvironmentFile, shell) wins over the file."""
        if load_env:
            ensure_env_loaded()
        targets_raw = os.getenv("EMERGE_MONITOR_TARGETS", "")
        targets = tuple(t.strip() for t in targets_raw.split(",") if t.strip())
        return cls(
            webhook_url=os.getenv("EMERGE_ALERT_WEBHOOK_URL", "").strip(),
            alert_proxy=os.getenv("EMERGE_ALERT_PROXY") or None,
            alert_timeout=_env_float("EMERGE_ALERT_TIMEOUT", 10.0),
            google_api_key=os.getenv("GOOGLE_API_KEY", "").strip(),
            google_proxy=os.getenv("GOOGLE_PROXY") or None,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
            anthropic_proxy=os.getenv("ANTHROPIC_PROXY") or None,
            anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL", "").strip(),
            interval=_env_float("EMERGE_MONITOR_INTERVAL", 300.0),
            probe_timeout=_env_float("EMERGE_MONITOR_TIMEOUT", 20.0),
            fail_threshold=_env_int("EMERGE_MONITOR_FAIL_THRESHOLD", 2),
            realert_after=_env_float("EMERGE_MONITOR_REALERT_AFTER", 3600.0),
            google_probe_model=os.getenv(
                "EMERGE_MONITOR_GOOGLE_MODEL", _DEFAULT_GOOGLE_PROBE_MODEL
            ),
            anthropic_probe_model=os.getenv(
                "EMERGE_MONITOR_ANTHROPIC_MODEL", _DEFAULT_ANTHROPIC_PROBE_MODEL
            ),
            probe_agent=_env_bool("EMERGE_MONITOR_PROBE_AGENT", False),
            agent_min_interval=_env_float("EMERGE_MONITOR_AGENT_INTERVAL", 1800.0),
            targets_override=targets,
            enabled=_env_bool("EMERGE_MONITOR_ENABLED", False),
            host=os.getenv("EMERGE_MONITOR_HOST") or socket.gethostname(),
        )

    def secret_values(self) -> tuple[str, ...]:
        """All secret strings to redact from outbound text (keys + webhook token)."""
        out: list[str] = []
        for s in (self.google_api_key, self.anthropic_api_key):
            if s:
                out.append(s)
        if self.webhook_url:
            token = parse_qs(urlsplit(self.webhook_url).query).get("yzjtoken", [""])[0]
            if token:
                out.append(token)
        return tuple(out)
