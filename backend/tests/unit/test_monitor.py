"""Unit tests for the LLM availability monitor.

No network: the alerter is driven with an httpx.MockTransport, the state machine
is driven by hand-fed ProbeResults, and a FakeAlerter captures outbound content.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.monitor.alerter import AlertResult, YunzhijiaAlerter
from app.monitor.config import MonitorConfig, scrub_secrets
from app.monitor.monitor import LLMMonitor
from app.monitor.probes import ProbeResult, build_targets, run_probe


# --- alerter response taxonomy ----------------------------------------------
def _alerter(handler) -> YunzhijiaAlerter:
    return YunzhijiaAlerter(
        "https://yunzhijia.test/webhook?yzjtoken=tok",
        transport=httpx.MockTransport(handler),
        secrets=("supersecretkey",),
    )


async def test_alert_delivered_on_success():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"success": True, "errorCode": 0, "errorMsg": "ok"})

    res = await _alerter(handler).send("hello")
    assert res.ok and res.error_code == 0
    assert captured["body"] == {"content": "hello"}


async def test_alert_business_failure_when_errorcode_nonzero():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "errorCode": 110, "errorMsg": "bad token"})

    res = await _alerter(handler).send("x")
    assert not res.ok and res.error_code == 110
    assert "110" in res.reason()


async def test_alert_http_5xx_is_transport_failure():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    res = await _alerter(handler).send("x")
    assert not res.ok and res.http_status == 503


async def test_alert_secret_scrubbed_from_error_text():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom key=supersecretkey leaked")

    res = await _alerter(handler).send("x")
    assert "supersecretkey" not in res.error_msg
    assert "***" in res.error_msg


async def test_alert_transport_exception_is_send_failure():
    # The alert channel itself is down (DNS/conn refused) — must not raise, and
    # must report a transport failure so the broken channel is visible.
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    res = await _alerter(handler).send("x")
    assert not res.ok
    assert res.transport_error
    assert "transport" in res.reason()


async def test_alert_2xx_but_non_json_is_failure():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway login</html>")

    res = await _alerter(handler).send("x")
    assert not res.ok
    assert res.error_msg == "non-json response"


def test_scrub_secrets_redacts_known_values():
    assert scrub_secrets("url?key=abcdef123", ("abcdef123",)) == "url?key=***"
    # too-short secrets are left alone (avoid clobbering common substrings)
    assert scrub_secrets("abc", ("abc",)) == "abc"


# --- target resolution from env ---------------------------------------------
def test_build_targets_scopes_to_present_keys():
    assert {t.name for t in build_targets(MonitorConfig())} == set()
    cfg = MonitorConfig(
        google_api_key="g", anthropic_api_key="a", anthropic_base_url="https://gw.test"
    )
    assert {t.name for t in build_targets(cfg)} == {"google", "anthropic"}


def test_anthropic_probe_skipped_without_gateway():
    # No ANTHROPIC_BASE_URL → never probe (direct api.anthropic.com is forbidden).
    cfg = MonitorConfig(google_api_key="g", anthropic_api_key="a")
    assert {t.name for t in build_targets(cfg)} == {"google"}


def test_build_targets_respects_override_allowlist():
    cfg = MonitorConfig(
        google_api_key="g",
        anthropic_api_key="a",
        anthropic_base_url="https://gw.test",
        targets_override=("google",),
    )
    assert {t.name for t in build_targets(cfg)} == {"google"}


def test_build_targets_excludes_named_probes():
    # Subtractive: drop google, keep everything else auto-derived (incl. agent).
    cfg = MonitorConfig(
        google_api_key="g",
        anthropic_api_key="a",
        anthropic_base_url="https://gw.test",
        probe_agent=True,
        targets_exclude=("google",),
    )
    assert {t.name for t in build_targets(cfg)} == {"anthropic", "agent"}


def test_probe_agent_target_is_opt_in():
    cfg = MonitorConfig(probe_agent=True, agent_min_interval=1800)
    targets = build_targets(cfg)
    assert [t.name for t in targets] == ["agent"]
    assert targets[0].min_interval == 1800


# --- state machine: anti-flap, down, recover --------------------------------
class FakeAlerter:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str) -> AlertResult:
        self.sent.append(content)
        return AlertResult(ok=True)


def _monitor(**cfg_kw) -> tuple[LLMMonitor, FakeAlerter]:
    cfg = MonitorConfig(anthropic_api_key="x", anthropic_base_url="https://gw.test", **cfg_kw)
    fake = FakeAlerter()
    return LLMMonitor(cfg, alerter=fake), fake


async def test_single_blip_below_threshold_does_not_alert():
    monitor, fake = _monitor(fail_threshold=2)
    target = monitor.targets[0]
    await monitor._record(target, ProbeResult(ok=False, latency_ms=1.0, error="blip"))
    assert fake.sent == []
    assert monitor.states["anthropic"].healthy is True


async def test_alerts_once_down_then_once_on_recovery():
    monitor, fake = _monitor(fail_threshold=2, realert_after=0)
    target = monitor.targets[0]

    await monitor._record(target, ProbeResult(ok=False, latency_ms=1.0, error="boom"))
    await monitor._record(target, ProbeResult(ok=False, latency_ms=1.0, error="boom"))
    assert len(fake.sent) == 1 and "不可用" in fake.sent[0]
    assert monitor.states["anthropic"].healthy is False

    # still down → no second alert when realert disabled
    await monitor._record(target, ProbeResult(ok=False, latency_ms=1.0, error="boom"))
    assert len(fake.sent) == 1

    # recovery → exactly one recover alert
    await monitor._record(target, ProbeResult(ok=True, latency_ms=1.0))
    assert len(fake.sent) == 2 and "恢复" in fake.sent[1]
    assert monitor.states["anthropic"].healthy is True


async def test_no_webhook_send_returns_not_configured():
    monitor = LLMMonitor(MonitorConfig(anthropic_api_key="x"))  # no webhook → alerter None
    assert monitor.alerter is None
    res = await monitor.send_test_alert()
    assert not res.ok and "not configured" in res.transport_error


# --- probe failures: the *monitored* channel going down ----------------------
class _RaisingProvider:
    """Stand-in for a dead provider endpoint, returning an error that embeds the
    API key (mimics google-genai echoing `?key=...` in transport errors)."""

    def __init__(self, **_kw) -> None:
        pass

    async def extract(self, **_kw):
        raise RuntimeError("503 upstream unavailable key=SEKRET-1234567")


async def test_run_probe_reports_down_and_scrubs_secret(monkeypatch):
    monkeypatch.setattr("app.provider.google.GoogleProvider", _RaisingProvider)
    cfg = MonitorConfig(google_api_key="SEKRET-1234567")
    target = build_targets(cfg)[0]

    res = await run_probe(target, cfg)
    assert res.ok is False
    assert res.latency_ms >= 0
    assert "SEKRET-1234567" not in res.error  # never leak the key into state/alerts
    assert "***" in res.error


async def test_sweep_alerts_when_probe_keeps_failing(monkeypatch):
    monitor, fake = _monitor(fail_threshold=2, realert_after=0)

    async def _down(_target, _cfg):
        return ProbeResult(ok=False, latency_ms=1.0, error="endpoint dead")

    monkeypatch.setattr("app.monitor.monitor.run_probe", _down)
    await monitor.sweep()  # 1st fail — below threshold, no alert
    assert fake.sent == []
    await monitor.sweep()  # 2nd consecutive fail — DOWN alert fires
    assert len(fake.sent) == 1 and "不可用" in fake.sent[0]


class _BoomAlerter:
    async def send(self, _content: str):
        raise RuntimeError("alerter blew up")


async def test_send_swallows_alerter_exception_mid_outage():
    # An outage AND a broken alert channel must not crash the sweep loop.
    monitor = LLMMonitor(
        MonitorConfig(anthropic_api_key="x", anthropic_base_url="https://gw.test"),
        alerter=_BoomAlerter(),
    )
    res = await monitor._send("down!")
    assert not res.ok
    assert res.transport_error == "RuntimeError"


async def test_min_interval_target_not_reprobed_within_window(monkeypatch):
    cfg = MonitorConfig(probe_agent=True, agent_min_interval=9999)
    monitor = LLMMonitor(cfg, alerter=FakeAlerter())
    calls = {"n": 0}

    async def _ok(_target, _cfg):
        calls["n"] += 1
        return ProbeResult(ok=True, latency_ms=1.0)

    monkeypatch.setattr("app.monitor.monitor.run_probe", _ok)
    await monitor.sweep()
    await monitor.sweep()  # within min_interval → skipped
    assert calls["n"] == 1


async def test_status_dict_shape():
    monitor, _ = _monitor()
    status = monitor.status_dict()
    assert status["running"] is False
    assert status["webhook_configured"] is True  # FakeAlerter injected
    assert [t["name"] for t in status["targets"]] == ["anthropic"]
