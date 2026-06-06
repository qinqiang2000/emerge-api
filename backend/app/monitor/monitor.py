"""LLMMonitor — the periodic sweep + per-target state machine + alert routing.

State machine per target (anti-flap + recovery + optional re-reminder):

    healthy ──fail×threshold──▶ DOWN  ──(send 不可用 alert)
       ▲                         │
       │                         ├──still down ≥ realert_after──▶ (re-remind)
       └────────ok───────────────┘  (send 恢复 alert)

A single transient blip never alerts (needs `fail_threshold` consecutive
fails); a flapping target alerts once on the way down and once on the way back
up. All side effects are best-effort — the loop never lets a probe or an alert
exception escape and kill the host process.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime

from app.monitor.alerter import AlertResult, YunzhijiaAlerter
from app.monitor.config import MonitorConfig
from app.monitor.probes import ProbeResult, ProbeTarget, build_targets, run_probe

log = logging.getLogger("emerge.monitor")


def _now_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60}s"
    return f"{s // 3600}h{(s % 3600) // 60}m"


@dataclass
class TargetState:
    name: str
    model_id: str | None
    healthy: bool = True            # optimistic: first boot assumes up, won't false-alert
    consecutive_fail: int = 0
    down_since: float | None = None
    last_alert_at: float | None = None
    last_error: str = ""
    last_checked: float | None = None
    last_latency_ms: float | None = None
    checks: int = 0
    fails: int = 0

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "model_id": self.model_id,
            "healthy": self.healthy,
            "consecutive_fail": self.consecutive_fail,
            "last_error": self.last_error,
            "last_checked": self.last_checked,
            "last_latency_ms": round(self.last_latency_ms, 1) if self.last_latency_ms else None,
            "down_since": self.down_since,
            "checks": self.checks,
            "fails": self.fails,
        }


def _build_alerter(cfg: MonitorConfig) -> YunzhijiaAlerter | None:
    if not cfg.webhook_url:
        return None
    return YunzhijiaAlerter(
        cfg.webhook_url,
        proxy=cfg.alert_proxy,
        timeout=cfg.alert_timeout,
        secrets=cfg.secret_values(),
    )


class LLMMonitor:
    def __init__(
        self,
        cfg: MonitorConfig | None = None,
        *,
        alerter: YunzhijiaAlerter | None = None,
    ) -> None:
        self.cfg = cfg or MonitorConfig.from_env()
        # `alerter` arg is the test seam; default builds from config (None if no webhook).
        self.alerter = alerter if alerter is not None else _build_alerter(self.cfg)
        self.targets: list[ProbeTarget] = build_targets(self.cfg)
        self.states: dict[str, TargetState] = {
            t.name: TargetState(t.name, t.model_id) for t in self.targets
        }
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.started_at: float | None = None

    # --- lifecycle -----------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> bool:
        if self.running:
            return False
        if not self.targets:
            log.warning(
                "monitor: no probe targets resolved from env "
                "(set GOOGLE_API_KEY / ANTHROPIC_API_KEY, or EMERGE_MONITOR_PROBE_AGENT=1)"
            )
        self._stop = asyncio.Event()
        self.started_at = time.time()
        self._task = asyncio.create_task(self._loop(), name="llm-monitor")
        log.warning(
            "monitor: started — targets=%s interval=%ss threshold=%s webhook=%s",
            [t.name for t in self.targets],
            self.cfg.interval,
            self.cfg.fail_threshold,
            "on" if self.alerter else "OFF",
        )
        return True

    async def stop(self) -> bool:
        if not self.running:
            return False
        self._stop.set()
        assert self._task is not None
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        log.warning("monitor: stopped")
        return True

    async def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                await self.sweep()
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.cfg.interval)
                except asyncio.TimeoutError:
                    pass  # interval elapsed → next sweep
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — the watchdog must never crash its host
            log.exception("monitor: loop crashed unexpectedly")

    # --- one sweep -----------------------------------------------------------
    async def sweep(self) -> dict[str, ProbeResult]:
        """Probe every *due* target concurrently and fold results into state."""
        now = time.time()
        due = [t for t in self.targets if self._due(t, now)]
        if not due:
            return {}
        results = await asyncio.gather(
            *(run_probe(t, self.cfg) for t in due), return_exceptions=True
        )
        out: dict[str, ProbeResult] = {}
        for target, res in zip(due, results):
            if isinstance(res, BaseException):
                res = ProbeResult(ok=False, latency_ms=0.0, error=f"probe crashed: {type(res).__name__}")
            out[target.name] = res
            await self._record(target, res)
        return out

    def _due(self, target: ProbeTarget, now: float) -> bool:
        state = self.states[target.name]
        if target.min_interval <= 0 or state.last_checked is None:
            return True
        return now - state.last_checked >= target.min_interval

    async def _record(self, target: ProbeTarget, res: ProbeResult) -> None:
        state = self.states[target.name]
        now = time.time()
        state.last_checked = now
        state.last_latency_ms = res.latency_ms
        state.checks += 1

        if res.ok:
            if not state.healthy:
                duration = now - state.down_since if state.down_since else 0.0
                log.warning("monitor: %s RECOVERED after %s", state.name, _fmt_duration(duration))
                await self._alert_recover(state, duration)
            state.healthy = True
            state.consecutive_fail = 0
            state.down_since = None
            state.last_alert_at = None
            state.last_error = ""
            return

        # failure
        state.fails += 1
        state.consecutive_fail += 1
        state.last_error = res.error
        log.warning(
            "monitor: %s probe FAILED (%d/%d): %s",
            state.name, state.consecutive_fail, self.cfg.fail_threshold, res.error,
        )
        if state.healthy and state.consecutive_fail >= self.cfg.fail_threshold:
            state.healthy = False
            state.down_since = now
            await self._alert_down(state)
            state.last_alert_at = now
        elif (
            not state.healthy
            and self.cfg.realert_after > 0
            and state.last_alert_at is not None
            and now - state.last_alert_at >= self.cfg.realert_after
        ):
            await self._alert_down(state, reminder=True)
            state.last_alert_at = now

    # --- alert composition ---------------------------------------------------
    async def _alert_down(self, state: TargetState, *, reminder: bool = False) -> None:
        tag = "持续不可用" if reminder else "不可用"
        down_for = ""
        if reminder and state.down_since:
            down_for = f"｜已中断 {_fmt_duration(time.time() - state.down_since)}"
        content = (
            f"【emerge告警】{state.name} LLM {tag}"
            f"｜model={state.model_id or '-'}"
            f"｜连续失败 {state.consecutive_fail} 次{down_for}"
            f"｜错误：{state.last_error or '-'}"
            f"｜host={self.cfg.host}｜{_now_str()}"
        )
        await self._send(content)

    async def _alert_recover(self, state: TargetState, duration_s: float) -> None:
        content = (
            f"【emerge恢复】{state.name} LLM 已恢复可用"
            f"｜model={state.model_id or '-'}"
            f"｜中断约 {_fmt_duration(duration_s)}"
            f"｜host={self.cfg.host}｜{_now_str()}"
        )
        await self._send(content)

    async def _send(self, content: str) -> AlertResult:
        if self.alerter is None:
            log.error("monitor: 告警未发送（未配置 EMERGE_ALERT_WEBHOOK_URL）：%s", content)
            return AlertResult(ok=False, transport_error="webhook not configured")
        try:
            return await self.alerter.send(content)
        except Exception as e:  # noqa: BLE001 — alert path must never crash the sweep
            log.exception("monitor: alert send raised")
            return AlertResult(ok=False, transport_error=type(e).__name__)

    async def send_test_alert(self) -> AlertResult:
        """Fire a clearly-marked test message — lets an operator verify the 云之家
        channel any time without faking an outage."""
        content = (
            f"【emerge测试】云之家告警通道连通性测试（非真实告警）"
            f"｜host={self.cfg.host}｜{_now_str()}"
        )
        return await self._send(content)

    # --- introspection -------------------------------------------------------
    def status_dict(self) -> dict:
        return {
            "running": self.running,
            "started_at": self.started_at,
            "interval": self.cfg.interval,
            "fail_threshold": self.cfg.fail_threshold,
            "webhook_configured": self.alerter is not None,
            "targets": [self.states[t.name].as_dict() for t in self.targets],
        }


# --- process-wide singleton (used by the API routes + startup hook) ----------
_monitor: LLMMonitor | None = None


def get_monitor() -> LLMMonitor:
    global _monitor
    if _monitor is None:
        _monitor = LLMMonitor()
    return _monitor
