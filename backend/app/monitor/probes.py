"""Health probes — the cheapest call that proves an LLM layer is alive.

A probe reuses the *real* extract path (structured JSON via tool-use / response
schema) so it fails for the same reasons a user's extract would: dead endpoint,
rotated/expired key, region outage, schema-mode disabled. It is made economical
by:
  - retry OFF (`retry_max_attempts=1`) — the monitor's own consecutive-fail
    threshold handles flapping, so we don't pay 3× per probe;
  - a 1-field schema + `max_tokens` 16 — a couple of output tokens;
  - a short timeout — a hung provider counts as down fast.

Targets are derived from which credentials exist in env (no key → no probe), so
the probe set auto-scopes to whatever this deploy is actually configured for.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.monitor.config import MonitorConfig, scrub_secrets
from app.provider.base import TextBlock

_PROBE_SYSTEM = (
    "You are an availability probe. Reply with the JSON object {\"pong\": \"ok\"} "
    "and nothing else."
)
_PROBE_SCHEMA = {
    "type": "object",
    "properties": {"pong": {"type": "string"}},
    "required": ["pong"],
}
_PROBE_PARAMS = {"max_tokens": 16, "temperature": 0.0}


def _probe_content() -> list[TextBlock]:
    return [TextBlock(text="ping")]


@dataclass
class ProbeTarget:
    name: str          # stable key: "google" | "anthropic" | "agent"
    kind: str          # "provider:google" | "provider:anthropic" | "agent"
    model_id: str | None = None
    min_interval: float = 0.0  # skip if checked more recently than this (0 = every sweep)


@dataclass
class ProbeResult:
    ok: bool
    latency_ms: float
    error: str = ""


def build_targets(cfg: MonitorConfig) -> list[ProbeTarget]:
    """Resolve the probe set from config: a provider is probed only if its key
    is present (and, when `targets_override` is set, only if it's allowlisted)."""
    selected = set(cfg.targets_override) if cfg.targets_override else None
    excluded = set(cfg.targets_exclude)

    def want(name: str) -> bool:
        if name in excluded:
            return False
        return selected is None or name in selected

    targets: list[ProbeTarget] = []
    if cfg.google_api_key and want("google"):
        targets.append(ProbeTarget("google", "provider:google", cfg.google_probe_model))
    # Anthropic direct-extract probe requires a configured gateway: hitting
    # api.anthropic.com directly is forbidden (MEMORY:feedback_anthropic_no_direct_api),
    # so with no ANTHROPIC_BASE_URL we skip rather than fall back to the direct URL.
    if cfg.anthropic_api_key and cfg.anthropic_base_url and want("anthropic"):
        targets.append(
            ProbeTarget("anthropic", "provider:anthropic", cfg.anthropic_probe_model)
        )
    if cfg.probe_agent and want("agent"):
        targets.append(
            ProbeTarget("agent", "agent", "claude_agent_sdk", min_interval=cfg.agent_min_interval)
        )
    return targets


async def run_probe(target: ProbeTarget, cfg: MonitorConfig) -> ProbeResult:
    """Execute one probe, never raising — failures become `ProbeResult(ok=False)`
    with a secret-scrubbed error string."""
    t0 = time.monotonic()
    try:
        if target.kind == "provider:google":
            await _probe_google(target.model_id or cfg.google_probe_model, cfg)
        elif target.kind == "provider:anthropic":
            await _probe_anthropic(target.model_id or cfg.anthropic_probe_model, cfg)
        elif target.kind == "agent":
            await _probe_agent(cfg)
        else:  # pragma: no cover — guarded by build_targets
            raise ValueError(f"unknown probe kind: {target.kind!r}")
        return ProbeResult(ok=True, latency_ms=(time.monotonic() - t0) * 1000)
    except Exception as e:  # noqa: BLE001 — a probe failure is the signal, not a bug
        msg = scrub_secrets(str(e) or type(e).__name__, cfg.secret_values())
        return ProbeResult(ok=False, latency_ms=(time.monotonic() - t0) * 1000, error=msg[:300])


async def _probe_google(model_id: str, cfg: MonitorConfig) -> None:
    from app.provider.google import GoogleProvider

    provider = GoogleProvider(
        api_key=cfg.google_api_key,
        proxy=cfg.google_proxy,
        timeout=cfg.probe_timeout,
        retry_max_attempts=1,
    )
    res = await provider.extract(
        model_id=model_id,
        system_prompt=_PROBE_SYSTEM,
        user_content=_probe_content(),
        response_schema=_PROBE_SCHEMA,
        params=_PROBE_PARAMS,
    )
    if not isinstance(res.raw_json, dict):
        raise RuntimeError("probe returned non-dict json")


async def _probe_anthropic(model_id: str, cfg: MonitorConfig) -> None:
    from app.provider.anthropic import AnthropicProvider

    provider = AnthropicProvider(
        api_key=cfg.anthropic_api_key,
        proxy=cfg.anthropic_proxy,
        base_url=cfg.anthropic_base_url or None,  # never direct api.anthropic.com
        timeout=cfg.probe_timeout,
        retry_max_attempts=1,
    )
    res = await provider.extract(
        model_id=model_id,
        system_prompt=_PROBE_SYSTEM,
        user_content=_probe_content(),
        response_schema=_PROBE_SCHEMA,
        params=_PROBE_PARAMS,
    )
    if not isinstance(res.raw_json, dict):
        raise RuntimeError("probe returned non-dict json")


async def _probe_agent(cfg: MonitorConfig) -> None:
    """Probe the Agent brain (`claude_agent_sdk`). Distinct failure domain from
    the Anthropic *provider* probe: the brain authenticates with the OAuth token
    / bundled CLI, not `ANTHROPIC_API_KEY`, so it can be down while the provider
    is up (expired token). Costs a CLI spawn — hence opt-in + coarser cadence.

    The agent's capability — including this test — is realised *only* through
    `.env`: the SDK/CLI reads `ANTHROPIC_BASE_URL`, `CLAUDE_PROXY` and the token
    straight from the environment, so we guarantee `.env` is loaded first and let
    the SDK route through the configured gateway (never api.anthropic.com direct)."""
    from app.monitor.config import ensure_env_loaded

    ensure_env_loaded()
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    # +15s slack over probe_timeout for the one-time CLI spawn / Node JIT.
    async with asyncio.timeout(cfg.probe_timeout + 15):
        async with ClaudeSDKClient(options=ClaudeAgentOptions(max_turns=1)) as client:
            await client.query("Reply with the single word: pong")
            got = False
            async for _msg in client.receive_response():
                got = True
            if not got:
                raise RuntimeError("agent brain returned no response")
