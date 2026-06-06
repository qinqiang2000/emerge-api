"""LLM availability monitor — the "is the colleague awake?" watchdog.

emerge is a digital colleague whose value collapses the moment its underlying
LLMs stop answering. This package is a self-contained, non-functional watchdog
that periodically pokes each *configured* provider with a tiny health probe and
fires a 云之家 (yunzhijia) alert on an availability transition.

Design contract:
- **Decoupled.** Imports nothing from the lab tool registry / chat / jobs. The
  only coupling is *downward* into `app.provider.*` (to actually call an LLM)
  and a one-time read of `.env` (without which there is nothing to monitor).
- **Env-driven.** Probe targets are auto-derived from which provider keys exist
  in `.env` — no key, no probe. See `MonitorConfig.from_env`.
- **Economical.** Each probe is a single 1-shot structured call (retry off, tiny
  max_tokens) — a few input + a couple output tokens. Flap noise is absorbed by
  a consecutive-failure threshold, not by spending more tokens.
- **Two run modes, one core.** Embedded in the API process (env flag +
  `/lab/monitor/*` routes) or standalone (`python -m app.monitor run`).

Never reads/prints/commits secret *values* — error text routed to logs/alerts
is passed through `scrub_secrets` first.
"""
from app.monitor.alerter import AlertResult, YunzhijiaAlerter
from app.monitor.config import MonitorConfig, scrub_secrets
from app.monitor.monitor import LLMMonitor, get_monitor
from app.monitor.probes import ProbeResult, ProbeTarget, build_targets, run_probe

__all__ = [
    "AlertResult",
    "YunzhijiaAlerter",
    "MonitorConfig",
    "scrub_secrets",
    "LLMMonitor",
    "get_monitor",
    "ProbeResult",
    "ProbeTarget",
    "build_targets",
    "run_probe",
]
